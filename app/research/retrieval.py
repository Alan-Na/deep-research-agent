from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.llm import get_embedding_model, is_llm_available
from app.schemas import AgentResult, Citation, CriticSummary, EvidenceItem, EventItem, InvestmentMemo
from app.utils.text import dedupe_items, normalize_name, tokenize_for_similarity, truncate_text
from app.utils.time import is_recent

SOURCE_WEIGHT = {
    "disclosure_document": 1.0,
    "financial_abstract": 0.95,
    "official_website": 0.82,
    "market_data": 0.8,
    "market_profile": 0.72,
    "news_article": 0.68,
    "agent_summary": 0.55,
}


@dataclass
class RetrievalDocument:
    id: str
    agent_name: str
    source_type: str
    category: str
    title: str
    url: str | None
    date: str | None
    content: str
    metadata: dict[str, Any]


@dataclass
class RetrievalChunk:
    id: str
    document_id: str
    agent_name: str
    source_type: str
    category: str
    title: str
    url: str | None
    date: str | None
    content: str
    chunk_index: int
    metadata: dict[str, Any]
    embedding: list[float] | None = None


def build_evidence_index(
    agent_results: dict[str, AgentResult],
) -> tuple[list[EvidenceItem], list[EventItem], dict[str, Any]]:
    evidence_items: list[EvidenceItem] = []
    event_items: list[EventItem] = []
    partial_or_failed_agents: list[str] = []
    signal_biases: dict[str, str] = {}
    warnings: list[str] = []

    for agent_name, result in agent_results.items():
        evidence_items.extend(result.evidence)
        event_items.extend(result.events)
        if result.status in {"partial", "failed", "skipped"}:
            partial_or_failed_agents.append(agent_name)
        signal_bias = result.payload.get("signal_bias")
        if isinstance(signal_bias, str):
            signal_biases[agent_name] = signal_bias
        if result.warning:
            warnings.append(f"{agent_name}: {result.warning}")
        elif result.reason and result.status != "success":
            warnings.append(f"{agent_name}: {result.reason}")

    evidence_items = _dedupe_evidence(evidence_items)
    event_items, duplicate_event_ratio = _dedupe_events(event_items)
    coverage = {
        "valid_agent_count": len([item for item in agent_results.values() if item.status in {"success", "partial"} and (item.summary or item.evidence)]),
        "evidence_count": len(evidence_items),
        "event_count": len(event_items),
        "has_recent_evidence": any(is_recent(item.date, get_settings().recent_days_threshold) for item in evidence_items),
        "partial_or_failed_agents": partial_or_failed_agents,
        "signal_biases": signal_biases,
        "duplicate_event_ratio": duplicate_event_ratio,
        "warnings": warnings,
    }
    if coverage["valid_agent_count"] < 2:
        coverage["warnings"].append("Coverage warning: fewer than two agents produced meaningful output.")
    if coverage["evidence_count"] < get_settings().minimum_evidence_cards:
        coverage["warnings"].append("Coverage warning: evidence volume is thin for a confident investment stance.")
    if not coverage["has_recent_evidence"]:
        coverage["warnings"].append("Coverage warning: recent evidence is weak or missing.")
    return evidence_items, event_items, coverage


def build_documents_and_chunks(agent_results: dict[str, AgentResult]) -> tuple[list[RetrievalDocument], list[RetrievalChunk]]:
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        separators=["\n\n", "\n", "。", ". ", "; ", " "],
    )

    documents: list[RetrievalDocument] = []
    chunks: list[RetrievalChunk] = []

    for agent_name, result in agent_results.items():
        summary_content = "\n".join(
            [
                result.summary,
                *result.key_points,
                *(event.summary for event in result.events[:3]),
            ]
        ).strip()
        if summary_content:
            document = RetrievalDocument(
                id=str(uuid.uuid4()),
                agent_name=agent_name,
                source_type="agent_summary",
                category="agent_summary",
                title=f"{agent_name} agent summary",
                url=None,
                date=result.finished_at,
                content=summary_content,
                metadata={"agent_name": agent_name},
            )
            documents.append(document)
            chunks.extend(_chunk_document(document, splitter))

        for evidence in result.evidence:
            document = RetrievalDocument(
                id=str(uuid.uuid4()),
                agent_name=evidence.agent_name,
                source_type=evidence.source_type,
                category=evidence.category,
                title=evidence.title,
                url=evidence.url,
                date=evidence.date,
                content=evidence.snippet,
                metadata=evidence.metadata,
            )
            documents.append(document)
            chunks.extend(_chunk_document(document, splitter))

        for event in result.events:
            document = RetrievalDocument(
                id=str(uuid.uuid4()),
                agent_name=agent_name,
                source_type="event_timeline",
                category=event.category,
                title=event.title,
                url=event.source_ids[0] if event.source_ids else None,
                date=event.date,
                content=event.summary,
                metadata={"horizon": event.horizon, "impact_score": event.impact_score},
            )
            documents.append(document)
            chunks.extend(_chunk_document(document, splitter))

    _embed_chunks(chunks)
    return documents, chunks


def bind_citations_to_memo(
    memo: InvestmentMemo,
    chunks: list[RetrievalChunk],
    coverage: dict[str, Any],
) -> InvestmentMemo:
    claims = _memo_claims(memo)
    citations: list[Citation] = []
    cited_claims: set[str] = set()
    agent_citation_counts: dict[str, int] = {}

    for claim in claims:
        matches = search_hybrid_chunks(claim, chunks, top_k=2)
        for match in matches:
            citations.append(
                Citation(
                    claim=claim,
                    agent_name=match.agent_name,
                    source_type=match.source_type,
                    category=match.category,
                    title=match.title,
                    snippet=truncate_text(match.content, 320),
                    url=match.url,
                    date=match.date,
                    score=round(_chunk_score(claim, match), 4),
                    chunk_id=match.id,
                    document_id=match.document_id,
                )
            )
            cited_claims.add(claim)
            agent_citation_counts[match.agent_name] = agent_citation_counts.get(match.agent_name, 0) + 1

    updated_outputs = dict(memo.agent_outputs)
    for agent_name, output in updated_outputs.items():
        enriched = dict(output)
        enriched["citations_count"] = agent_citation_counts.get(agent_name, 0)
        updated_outputs[agent_name] = enriched

    critic_summary = evaluate_memo(memo, citations, coverage)
    limitations = list(dict.fromkeys([*memo.limitations, *critic_summary.warnings]))
    updated_memo = memo.model_copy(
        update={
            "agent_outputs": updated_outputs,
            "citations": citations,
            "critic_summary": critic_summary,
            "limitations": limitations[:10],
        }
    )
    if not critic_summary.stance_supported and updated_memo.stance != "neutral":
        updated_memo = updated_memo.model_copy(
            update={
                "stance": "neutral",
                "stance_confidence": min(updated_memo.stance_confidence, 0.45),
                "limitations": list(
                    dict.fromkeys(
                        [
                            *updated_memo.limitations,
                            "Critic downgraded the stance to neutral because evidence support was not strong enough.",
                        ]
                    )
                )[:10],
            }
        )
    return updated_memo


def evaluate_memo(
    memo: InvestmentMemo,
    citations: list[Citation],
    coverage: dict[str, Any],
) -> CriticSummary:
    claims = _memo_claims(memo)
    claim_count = len(claims) or 1
    citation_coverage_score = min(len({item.claim for item in citations}) / claim_count, 1.0)
    freshness_hits = [item for item in citations if is_recent(item.date, get_settings().recent_days_threshold)]
    freshness_score = len(freshness_hits) / len(citations) if citations else 0.0
    duplicate_event_bias_score = max(0.0, 1.0 - float(coverage.get("duplicate_event_ratio") or 0.0))

    signal_biases = coverage.get("signal_biases") or {}
    positive = len([value for value in signal_biases.values() if value == "positive"])
    negative = len([value for value in signal_biases.values() if value == "negative"])
    total = max(len(signal_biases), 1)
    disagreement = min(positive, negative)
    consistency_score = max(0.0, 1.0 - (disagreement / total))

    warnings: list[str] = list(coverage.get("warnings") or [])
    if citation_coverage_score < 0.65:
        warnings.append("Critic warning: thesis coverage by citations is weak.")
    if freshness_score < 0.5:
        warnings.append("Critic warning: too much cited evidence is stale.")
    if consistency_score < 0.55:
        warnings.append("Critic warning: agents disagree materially on the investment picture.")
    if duplicate_event_bias_score < 0.7:
        warnings.append("Critic warning: duplicate news clusters may be overweighting one narrative.")

    stance_supported = (
        citation_coverage_score >= 0.65
        and freshness_score >= 0.45
        and consistency_score >= 0.5
        and int(coverage.get("valid_agent_count") or 0) >= 2
        and bool(coverage.get("has_recent_evidence"))
    )

    if memo.stance == "bullish" and negative > positive:
        stance_supported = False
        warnings.append("Critic warning: bearish signals outweigh bullish signals, so a bullish stance is not supported.")
    if memo.stance == "bearish" and positive > negative:
        stance_supported = False
        warnings.append("Critic warning: bullish signals outweigh bearish signals, so a bearish stance is not supported.")

    return CriticSummary(
        citation_coverage_score=round(citation_coverage_score, 4),
        freshness_score=round(freshness_score, 4),
        consistency_score=round(consistency_score, 4),
        duplicate_event_bias_score=round(duplicate_event_bias_score, 4),
        stance_supported=stance_supported,
        warnings=list(dict.fromkeys(warnings)),
    )


def search_hybrid_chunks(query: str, chunks: list[RetrievalChunk], top_k: int = 5) -> list[RetrievalChunk]:
    query_embedding = _query_embedding(query)
    scored = [(chunk, _chunk_score(query, chunk, query_embedding)) for chunk in chunks]
    ranked = sorted(scored, key=lambda item: item[1], reverse=True)
    return [chunk for chunk, score in ranked[:top_k] if score > 0]


def _chunk_document(document: RetrievalDocument, splitter: RecursiveCharacterTextSplitter) -> list[RetrievalChunk]:
    parts = splitter.split_text(document.content) or [document.content]
    chunks: list[RetrievalChunk] = []
    for index, part in enumerate(parts):
        content = truncate_text(part, max_chars=get_settings().rag_chunk_size)
        if not content:
            continue
        chunks.append(
            RetrievalChunk(
                id=str(uuid.uuid4()),
                document_id=document.id,
                agent_name=document.agent_name,
                source_type=document.source_type,
                category=document.category,
                title=document.title,
                url=document.url,
                date=document.date,
                content=content,
                chunk_index=index,
                metadata=document.metadata,
            )
        )
    return chunks


def _embed_chunks(chunks: list[RetrievalChunk]) -> None:
    if not chunks or not is_llm_available():
        return
    try:
        vectors = get_embedding_model().embed_documents([chunk.content for chunk in chunks])
        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = vector
    except Exception:
        for chunk in chunks:
            chunk.embedding = None


def _chunk_score(query: str, chunk: RetrievalChunk, query_embedding: list[float] | None = None) -> float:
    query_tokens = tokenize_for_similarity(query)
    chunk_tokens = tokenize_for_similarity(chunk.content)
    lexical_overlap = len(query_tokens & chunk_tokens)
    lexical_score = lexical_overlap / max(len(query_tokens), 1)

    phrase_bonus = 0.0
    normalized_query = normalize_name(query)
    normalized_content = normalize_name(chunk.content)
    if normalized_query and normalized_query in normalized_content:
        phrase_bonus += 0.45

    source_weight = SOURCE_WEIGHT.get(chunk.source_type, 0.45)
    freshness_bonus = 0.12 if is_recent(chunk.date, get_settings().recent_days_threshold) else 0.0

    vector_score = 0.0
    if chunk.embedding and query_embedding:
        vector_score = _cosine_similarity(query_embedding, chunk.embedding)

    return lexical_score + phrase_bonus + freshness_bonus + (source_weight * 0.35) + (vector_score * 0.35)


def _query_embedding(query: str) -> list[float] | None:
    if not is_llm_available():
        return None
    try:
        return get_embedding_model().embed_query(query)
    except Exception:
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _memo_claims(memo: InvestmentMemo) -> list[str]:
    return [
        memo.thesis,
        *memo.bull_case,
        *memo.bear_case,
        *memo.key_catalysts,
        *memo.key_risks,
        memo.valuation_view,
        *memo.watch_items,
    ]


def _dedupe_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    deduped = dedupe_items(
        items,
        lambda item: f"{item.agent_name}|{item.category}|{item.title}|{item.url}|{item.date}|{item.snippet}",
    )
    return deduped


def _dedupe_events(items: list[EventItem]) -> tuple[list[EventItem], float]:
    total = len(items)
    deduped = dedupe_items(
        items,
        lambda item: f"{item.category}|{normalize_name(item.title)}|{item.date}",
    )
    duplicate_ratio = 0.0
    if total:
        duplicate_ratio = max(0.0, (total - len(deduped)) / total)
    return deduped, duplicate_ratio


# Compatibility aliases for deprecated imports.
bind_citations_to_report = bind_citations_to_memo
