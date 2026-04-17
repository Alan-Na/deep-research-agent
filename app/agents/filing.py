from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import requests

from app.agents.base import AgentDefinition, ToolDefinition
from app.config import get_settings
from app.schemas import AgentResult, EvidenceItem, ResearchBrief
from app.tools.filing import SecEdgarAdapter
from app.utils.http import build_headers
from app.utils.logging import get_logger
from app.utils.text import dedupe_items, normalize_whitespace, truncate_text
from app.utils.time import utc_now

logger = get_logger(__name__)

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


FINANCIAL_FACT_PATTERNS = {
    "revenue": [r"营业总收入[^\d]{0,8}([\d,.]+)", r"营业收入[^\d]{0,8}([\d,.]+)"],
    "net_income": [r"归属于上市公司股东的净利润[^\d]{0,8}([\d,.]+)", r"归母净利润[^\d]{0,8}([\d,.]+)"],
    "operating_cash_flow": [r"经营活动产生的现金流量净额[^\d]{0,8}([\d,.]+)"],
    "eps": [r"基本每股收益[^\d]{0,8}([\d,.]+)"],
}


@dataclass
class FilingDocument:
    provider: str
    filing_type: str
    title: str
    filed_at: str
    url: str
    text: str


class AShareDisclosureProvider:
    base_url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    static_prefix = "http://static.cninfo.com.cn/"

    def fetch_recent_documents(self, brief: ResearchBrief, limit: int = 3) -> list[FilingDocument]:
        query = brief.instrument.symbol or brief.company_name
        categories = ["年报", "半年报", "一季报", "三季报"]
        announcements: list[dict[str, Any]] = []
        for category in categories:
            payload = {
                "pageNum": 1,
                "pageSize": 15,
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
                "searchkey": query,
                "secid": "",
                "category": _cninfo_category(category),
                "trade": "",
                "seDate": f"{utc_now().year - 3}-01-01~{utc_now().date().isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            response = requests.post(self.base_url, data=payload, headers=build_headers(), timeout=get_settings().request_timeout)
            response.raise_for_status()
            data = response.json()
            announcements.extend(data.get("announcements", []))

        documents: list[FilingDocument] = []
        seen_urls: set[str] = set()
        for announcement in sorted(announcements, key=lambda item: item.get("announcementTime", 0), reverse=True):
            symbol = str(announcement.get("secCode") or "")
            if brief.instrument.symbol and symbol and symbol != brief.instrument.symbol:
                continue
            title = normalize_whitespace(re.sub(r"<[^>]+>", "", str(announcement.get("announcementTitle") or "")))
            filed_at = _millis_to_iso(announcement.get("announcementTime"))
            adjunct = str(announcement.get("adjunctUrl") or "").strip("/")
            if not adjunct:
                continue
            url = f"{self.static_prefix}{adjunct}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            text = _extract_document_text(url)
            if not text:
                text = title
            filing_type = _infer_filing_type(title)
            documents.append(
                FilingDocument(
                    provider="cninfo",
                    filing_type=filing_type,
                    title=title,
                    filed_at=filed_at,
                    url=url,
                    text=text,
                )
            )
            if len(documents) >= limit:
                break
        return documents


class SecProviderRegistry:
    def __init__(self) -> None:
        self.sec = SecEdgarAdapter()

    def fetch_recent_documents(self, brief: ResearchBrief, limit: int = 3) -> list[FilingDocument]:
        filings = self.sec.fetch_recent_filings(brief.company_name, ticker=brief.instrument.symbol, limit=limit)
        return [
            FilingDocument(
                provider="sec",
                filing_type=item.form,
                title=item.title,
                filed_at=item.filed_at,
                url=item.url,
                text=item.text,
            )
            for item in filings
        ]


def filing_agent_definition() -> AgentDefinition:
    a_share_provider = AShareDisclosureProvider()
    sec_registry = SecProviderRegistry()
    return AgentDefinition(
        agent_name="filing",
        description="Analyse filings/disclosures with provider registry and structured fact extraction.",
        enabled_capabilities=[
            "discover_documents",
            "parse_documents",
            "extract_structured_facts",
            "build_memo_insights",
        ],
        tool_registry={
            "discover_documents": ToolDefinition(
                name="discover_documents",
                description="Discover latest annual/interim disclosure documents from the active market provider.",
                handler=lambda brief, shared, scratchpad: _discover_documents(a_share_provider, sec_registry, brief),
            ),
            "parse_documents": ToolDefinition(
                name="parse_documents",
                description="Parse disclosure text into normalized excerpts for downstream extraction.",
                handler=_parse_documents,
            ),
            "extract_structured_facts": ToolDefinition(
                name="extract_structured_facts",
                description="Extract financial headline facts and risk snippets from parsed disclosure text.",
                handler=_extract_structured_facts,
            ),
            "build_memo_insights": ToolDefinition(
                name="build_memo_insights",
                description="Summarize disclosure takeaways in memo-ready language.",
                handler=_build_memo_insights,
            ),
        },
        output_model=AgentResult,
        finalize_handler=_finalize_filing_agent,
        timeout_seconds=get_settings().agent_timeout_seconds,
        max_steps=get_settings().agent_max_steps,
    )


def _discover_documents(
    a_share_provider: AShareDisclosureProvider,
    sec_registry: SecProviderRegistry,
    brief: ResearchBrief,
) -> dict[str, Any]:
    if brief.market == "A_SHARE":
        documents = a_share_provider.fetch_recent_documents(brief, limit=get_settings().filing_max_documents)
    elif brief.market == "US":
        documents = sec_registry.fetch_recent_documents(brief, limit=get_settings().filing_max_documents)
    else:
        documents = []

    payload = [document.__dict__ for document in documents]
    return {
        "summary": f"Discovered {len(documents)} recent disclosure documents.",
        "payload": {"documents": payload},
    }


def _parse_documents(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    raw_documents = scratchpad.get("payload", {}).get("documents") or []
    parsed_documents = []
    evidence = []
    for item in raw_documents:
        text = normalize_whitespace(str(item.get("text") or ""))
        excerpts = _extract_interesting_sentences(text)
        parsed_documents.append({**item, "parsed_excerpt": excerpts})
        evidence.append(
            EvidenceItem(
                agent_name="filing",
                source_type="disclosure_document",
                category="filing_excerpt",
                title=str(item.get("title") or "Disclosure"),
                date=item.get("filed_at"),
                url=item.get("url"),
                snippet=truncate_text(excerpts or text or str(item.get("title") or ""), 320),
                metadata={"provider": item.get("provider"), "filing_type": item.get("filing_type")},
            ).model_dump()
        )
    return {
        "summary": f"Parsed {len(parsed_documents)} disclosure texts into normalized excerpts.",
        "payload": {"parsed_documents": parsed_documents},
        "evidence": evidence,
    }


def _extract_structured_facts(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    parsed_documents = scratchpad.get("payload", {}).get("parsed_documents") or []
    structured_facts: dict[str, Any] = {
        "revenue": None,
        "net_income": None,
        "operating_cash_flow": None,
        "eps": None,
        "key_risks": [],
        "supporting_documents": [],
    }
    for item in parsed_documents:
        text = str(item.get("parsed_excerpt") or item.get("text") or "")
        structured_facts["supporting_documents"].append(
            {
                "title": item.get("title"),
                "filed_at": item.get("filed_at"),
                "url": item.get("url"),
                "provider": item.get("provider"),
                "filing_type": item.get("filing_type"),
            }
        )
        for field, patterns in FINANCIAL_FACT_PATTERNS.items():
            if structured_facts.get(field):
                continue
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    structured_facts[field] = match.group(1)
                    break
        risk_lines = [sentence for sentence in _extract_interesting_sentences(text).split("。") if "风险" in sentence][:3]
        structured_facts["key_risks"].extend(risk_lines)
    structured_facts["key_risks"] = dedupe_items(
        [item for item in structured_facts["key_risks"] if item],
        lambda item: normalize_whitespace(item),
    )[:5]
    return {
        "summary": "Extracted filing headline facts and risk references.",
        "payload": {"structured_facts": structured_facts},
    }


def _build_memo_insights(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    facts = scratchpad.get("payload", {}).get("structured_facts") or {}
    documents = scratchpad.get("payload", {}).get("documents") or []
    insights = {
        "takeaways": [],
        "summary": "",
        "signal_bias": "neutral",
    }
    if facts.get("revenue"):
        insights["takeaways"].append(f"披露文件中提到营业收入 {facts['revenue']}")
    if facts.get("net_income"):
        insights["takeaways"].append(f"披露文件中提到归母净利润 {facts['net_income']}")
    if facts.get("operating_cash_flow"):
        insights["takeaways"].append(f"经营现金流量净额 {facts['operating_cash_flow']}")
    if facts.get("key_risks"):
        insights["takeaways"].append(f"披露文本提及风险点 {len(facts['key_risks'])} 条")

    if facts.get("net_income") and facts.get("operating_cash_flow"):
        insights["signal_bias"] = "positive"
    elif facts.get("key_risks"):
        insights["signal_bias"] = "negative"

    document_headline = documents[0]["title"] if documents else "近期披露"
    insights["summary"] = (
        f"Filing Agent 基于 {document_headline} 等披露文件抽取了财务与风险线索，"
        f"当前更偏向 {insights['signal_bias']} 信号。"
    )
    return {
        "summary": "Built memo insights from disclosure facts.",
        "payload": {"memo_insights": insights},
    }


def _finalize_filing_agent(
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
    observations: list[Any],
) -> AgentResult:
    payload = dict(scratchpad.get("payload") or {})
    documents = payload.get("documents") or []
    facts = payload.get("structured_facts") or {}
    memo_insights = payload.get("memo_insights") or {}
    status = "success" if documents else "partial"
    reason = None if documents else "No disclosure documents were found for the target."
    warning = None
    if documents and not any(facts.get(key) for key in ("revenue", "net_income", "operating_cash_flow", "eps")):
        warning = "Structured extraction from disclosures was weak; memo will rely on document titles and limited excerpts."
        status = "partial"
    if scratchpad.get("errors"):
        status = "partial"
        error_warning = " | ".join(str(item) for item in scratchpad["errors"][:2])
        warning = f"{warning + ' ' if warning else ''}Capability fallback triggered: {error_warning}"

    key_points = list(memo_insights.get("takeaways") or [])
    if not key_points and documents:
        key_points = [f"已获取 {len(documents)} 份近期披露文件。"]

    return AgentResult(
        agent_name="filing",
        applicable=brief.market in {"A_SHARE", "US"},
        status=status,
        summary=str(memo_insights.get("summary") or "Filing Agent completed."),
        key_points=key_points,
        metrics={"provider": documents[0]["provider"] if documents else None},
        payload={
            "provider": documents[0]["provider"] if documents else None,
            "documents": documents,
            "structured_facts": facts,
            "memo_insights": memo_insights,
            "signal_bias": memo_insights.get("signal_bias", "neutral"),
        },
        evidence=[EvidenceItem.model_validate(item) for item in scratchpad.get("evidence", [])],
        warning=warning,
        reason=reason,
        observations=observations,
    )


def _extract_document_text(url: str) -> str:
    try:
        response = requests.get(url, headers=build_headers(), timeout=get_settings().request_timeout)
        response.raise_for_status()
    except Exception:
        logger.exception("Failed to download disclosure document: %s", url)
        return ""

    lower_url = url.lower()
    if lower_url.endswith(".pdf") and PdfReader is not None:
        try:
            reader = PdfReader(BytesIO(response.content))
            pages = []
            for page in reader.pages[:20]:
                pages.append(page.extract_text() or "")
            return normalize_whitespace("\n".join(pages))
        except Exception:
            logger.exception("Failed to parse PDF disclosure document: %s", url)
            return ""
    try:
        return normalize_whitespace(response.text)
    except Exception:
        return ""


def _infer_filing_type(title: str) -> str:
    for filing_type in ["年报", "半年报", "一季报", "三季报"]:
        if filing_type in title:
            return filing_type
    return "公告"


def _extract_interesting_sentences(text: str) -> str:
    if not text:
        return ""
    separators = re.split(r"[。；;\n]", text)
    picked = []
    for sentence in separators:
        candidate = normalize_whitespace(sentence)
        if not candidate:
            continue
        if any(keyword in candidate for keyword in ["营业收入", "归属于上市公司股东", "净利润", "现金流", "风险", "产能", "渠道", "需求"]):
            picked.append(candidate)
        if len(picked) >= 8:
            break
    if not picked:
        return truncate_text(text, 600)
    return "。".join(picked)


def _millis_to_iso(value: Any) -> str | None:
    try:
        millis = int(value)
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).date().isoformat()
    except Exception:
        return None


def _cninfo_category(category: str) -> str:
    mapping = {
        "年报": "category_ndbg_szsh;",
        "半年报": "category_bndbg_szsh;",
        "一季报": "category_yjdbg_szsh;",
        "三季报": "category_sjdbg_szsh;",
    }
    return mapping.get(category, "")
