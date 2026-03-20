from __future__ import annotations

import json
from collections import defaultdict

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.llm import get_chat_model, get_embedding_model, is_llm_available
from app.prompts import FILING_ANALYSIS_SYSTEM_PROMPT, FILING_ANALYSIS_USER_PROMPT
from app.schemas import EvidenceCard, FilingInsights
from app.tools.base import FilingDocumentRecord
from app.utils.logging import get_logger
from app.utils.text import dedupe_items, normalize_name, truncate_text

logger = get_logger(__name__)

RAG_QUERIES = {
    "operating_performance": "recent operating performance, revenue trend, profitability, demand and execution",
    "risk_factors": "recent risk factors, headwinds, uncertainty, legal, regulatory, macro and competitive risks",
    "management_commentary": "management commentary, executive discussion, priorities, strategy and operating tone",
    "guidance_changes": "guidance changes, outlook, forecast, expectation, full year and next quarter outlook",
}


def _build_langchain_documents(filings: list[FilingDocumentRecord]) -> list[Document]:
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        separators=["\n\n", "\n", ". ", " "],
    )

    documents: list[Document] = []
    for filing in filings:
        chunks = splitter.split_text(filing.text)
        for chunk in chunks:
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "form": filing.form,
                        "filed_at": filing.filed_at,
                        "title": filing.title,
                        "url": filing.url,
                    },
                )
            )
    return documents


def _keyword_retrieve(documents: list[Document], query: str, top_k: int = 4) -> list[Document]:
    # 中文注释：当向量检索不可用时，使用简单的关键词重排兜底。
    query_tokens = {token for token in normalize_name(query).split() if token}
    scored: list[tuple[int, Document]] = []
    for doc in documents:
        content = normalize_name(doc.page_content)
        score = sum(1 for token in query_tokens if token and token in content)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


def _retrieve_context(documents: list[Document]) -> dict[str, list[dict[str, str]]]:
    if not documents:
        return {}

    bundles: dict[str, list[dict[str, str]]] = defaultdict(list)

    try:
        vector_store = None
        if is_llm_available():
            vector_store = FAISS.from_documents(documents, get_embedding_model())

        for key, query in RAG_QUERIES.items():
            if vector_store is not None:
                retrieved = vector_store.similarity_search(query, k=4)
            else:
                retrieved = _keyword_retrieve(documents, query, top_k=4)

            for doc in retrieved:
                bundles[key].append(
                    {
                        "title": doc.metadata.get("title", ""),
                        "form": doc.metadata.get("form", ""),
                        "filed_at": doc.metadata.get("filed_at", ""),
                        "url": doc.metadata.get("url", ""),
                        "snippet": truncate_text(doc.page_content, max_chars=450),
                    }
                )
    except Exception:
        logger.exception("Vector retrieval failed. Falling back to keyword retrieval.")
        for key, query in RAG_QUERIES.items():
            retrieved = _keyword_retrieve(documents, query, top_k=4)
            for doc in retrieved:
                bundles[key].append(
                    {
                        "title": doc.metadata.get("title", ""),
                        "form": doc.metadata.get("form", ""),
                        "filed_at": doc.metadata.get("filed_at", ""),
                        "url": doc.metadata.get("url", ""),
                        "snippet": truncate_text(doc.page_content, max_chars=450),
                    }
                )

    return bundles


def _heuristic_filing_insights(company_name: str, context_bundle: dict[str, list[dict[str, str]]]) -> FilingInsights:
    # 中文注释：无模型时尽量从检索片段拼出可读结论。
    def first_snippet(section: str) -> str:
        items = context_bundle.get(section, [])
        if not items:
            return "Evidence is weak for this topic."
        return items[0]["snippet"]

    return FilingInsights(
        summary=f"Recent filing review for {company_name} was generated with heuristic fallback.",
        operating_performance=first_snippet("operating_performance"),
        risk_factors=[item["snippet"] for item in context_bundle.get("risk_factors", [])[:3]] or ["Evidence is weak for risk factors."],
        management_commentary=first_snippet("management_commentary"),
        guidance_changes=first_snippet("guidance_changes"),
    )


def _build_evidence_cards(context_bundle: dict[str, list[dict[str, str]]]) -> list[EvidenceCard]:
    cards: list[EvidenceCard] = []
    for section_name, items in context_bundle.items():
        for item in items[:2]:
            cards.append(
                EvidenceCard(
                    module="filing",
                    source_type="sec_filing",
                    title=item["title"] or f"SEC filing snippet: {section_name}",
                    date=item.get("filed_at") or None,
                    snippet=item["snippet"],
                    url=item.get("url") or None,
                )
            )
    return dedupe_items(cards, lambda card: f"{card.url}|{card.title}|{card.date}|{card.snippet}")


def extract_filing_insights(
    company_name: str,
    filings: list[FilingDocumentRecord],
) -> tuple[FilingInsights, list[EvidenceCard]]:
    documents = _build_langchain_documents(filings)
    context_bundle = _retrieve_context(documents)
    evidence_cards = _build_evidence_cards(context_bundle)

    if not is_llm_available():
        logger.warning("Filing RAG fallback triggered because OPENAI_API_KEY is missing.")
        return _heuristic_filing_insights(company_name, context_bundle), evidence_cards

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", FILING_ANALYSIS_SYSTEM_PROMPT),
            ("human", FILING_ANALYSIS_USER_PROMPT),
        ]
    )

    try:
        llm = get_chat_model(temperature=0.0)
        structured_llm = llm.with_structured_output(FilingInsights, method="json_schema")
        result = (prompt | structured_llm).invoke(
            {
                "company_name": company_name,
                "context_bundle": json.dumps(context_bundle, ensure_ascii=False, indent=2),
            }
        )
        return FilingInsights.model_validate(result), evidence_cards
    except Exception:
        logger.exception("Filing analysis LLM failed. Falling back to heuristic synthesis.")
        return _heuristic_filing_insights(company_name, context_bundle), evidence_cards
