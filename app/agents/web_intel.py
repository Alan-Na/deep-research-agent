from __future__ import annotations

import re
from typing import Any

from app.agents.base import AgentDefinition, ToolDefinition
from app.config import get_settings
from app.schemas import AgentResult, EvidenceItem, InstrumentInfo, ResearchBrief
from app.tools.website import DefaultWebsiteDiscoveryAdapter, RequestsWebsiteCrawler
from app.utils.text import normalize_whitespace, truncate_text


def web_intel_agent_definition() -> AgentDefinition:
    discovery = DefaultWebsiteDiscoveryAdapter()
    crawler = RequestsWebsiteCrawler()
    return AgentDefinition(
        agent_name="web_intel",
        description="Analyse official website, IR pages, products, and company positioning.",
        enabled_capabilities=[
            "discover_official_site",
            "crawl_ir_pages",
            "extract_product_business",
            "extract_competitive_language",
        ],
        tool_registry={
            "discover_official_site": ToolDefinition(
                name="discover_official_site",
                description="Discover the official company website.",
                handler=lambda brief, shared, scratchpad: _discover_official_site(discovery, brief),
            ),
            "crawl_ir_pages": ToolDefinition(
                name="crawl_ir_pages",
                description="Crawl a small set of official and IR pages from the website.",
                handler=lambda brief, shared, scratchpad: _crawl_pages(crawler, brief, scratchpad),
            ),
            "extract_product_business": ToolDefinition(
                name="extract_product_business",
                description="Extract product, business model, and IR highlights from crawled pages.",
                handler=_extract_product_business,
            ),
            "extract_competitive_language": ToolDefinition(
                name="extract_competitive_language",
                description="Extract positioning and competitive language from the official site.",
                handler=_extract_competitive_language,
            ),
        },
        output_model=AgentResult,
        finalize_handler=_finalize_web_intel_agent,
        timeout_seconds=get_settings().agent_timeout_seconds,
        max_steps=get_settings().agent_max_steps,
    )


def _discover_official_site(discovery: DefaultWebsiteDiscoveryAdapter, brief: ResearchBrief) -> dict[str, Any]:
    instrument = brief.instrument
    url = discovery.discover(
        brief.company_name,
        {
            "website_url": instrument.website_url,
            "ticker": instrument.symbol,
            "market": instrument.market,
        },
    )
    return {
        "summary": f"Resolved official site to {url or 'unavailable'}.",
        "payload": {"official_website": url},
    }


def _crawl_pages(
    crawler: RequestsWebsiteCrawler,
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    url = scratchpad.get("payload", {}).get("official_website")
    if not url:
        return {"summary": "Skipped website crawl because the official site was not resolved."}
    pages = crawler.crawl(url, max_pages=get_settings().max_website_pages)
    serialized_pages = [{"title": page.title, "url": page.url, "text": page.text} for page in pages]
    evidence = [
        EvidenceItem(
            agent_name="web_intel",
            source_type="official_website",
            category="website_page",
            title=page.title,
            date=None,
            url=page.url,
            snippet=truncate_text(page.text, 320),
            metadata={"page_url": page.url},
        ).model_dump()
        for page in pages
    ]
    return {
        "summary": f"Crawled {len(serialized_pages)} pages from the official site.",
        "payload": {"pages": serialized_pages},
        "evidence": evidence,
    }


def _extract_product_business(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    pages = scratchpad.get("payload", {}).get("pages") or []
    product_points: list[str] = []
    ir_highlights: list[str] = []
    summaries: list[str] = []
    for page in pages:
        text = normalize_whitespace(str(page.get("text") or ""))
        title = str(page.get("title") or "")
        if any(keyword in title.lower() for keyword in ["investor", "ir", "投资者", "公告", "新闻"]):
            ir_highlights.append(f"{title}: {truncate_text(text, 120)}")
        if any(keyword in text for keyword in ["产品", "平台", "解决方案", "品牌", "业务", "客户"]):
            product_points.append(f"{title}: {truncate_text(text, 140)}")
        if text:
            summaries.append(f"{title}: {truncate_text(text, 160)}")
    return {
        "summary": "Extracted product and IR signals from the crawled website pages.",
        "payload": {
            "product_points": product_points[:5],
            "ir_highlights": ir_highlights[:5],
            "website_summary_blocks": summaries[:5],
        },
    }


def _extract_competitive_language(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    pages = scratchpad.get("payload", {}).get("pages") or []
    positioning: list[str] = []
    for page in pages:
        text = normalize_whitespace(str(page.get("text") or ""))
        sentences = re.split(r"[。；;\n]", text)
        for sentence in sentences:
            candidate = normalize_whitespace(sentence)
            if len(candidate) < 12:
                continue
            if any(keyword in candidate for keyword in ["领先", "龙头", "平台", "生态", "高端", "技术", "研发", "产能"]):
                positioning.append(candidate)
            if len(positioning) >= 5:
                break
        if len(positioning) >= 5:
            break
    return {
        "summary": "Extracted company positioning and competitive language from official pages.",
        "payload": {"positioning": positioning[:5]},
    }


def _finalize_web_intel_agent(
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
    observations: list[Any],
) -> AgentResult:
    payload = dict(scratchpad.get("payload") or {})
    product_points = list(payload.get("product_points") or [])
    ir_highlights = list(payload.get("ir_highlights") or [])
    positioning = list(payload.get("positioning") or [])
    pages = payload.get("pages") or []
    official_website = payload.get("official_website")
    signal = "positive" if ir_highlights or product_points else "neutral"
    status = "success" if official_website and pages else "partial"
    summary = (
        f"Web Intelligence Agent 已完成官网与 IR 信息抽取，"
        f"识别到 {len(product_points)} 条产品/业务线索，"
        f"{len(ir_highlights)} 条 IR/公告线索。"
    )
    warning = None if official_website else "Official website discovery was weak; website intelligence is partial."
    if scratchpad.get("errors"):
        status = "partial"
        error_warning = " | ".join(str(item) for item in scratchpad["errors"][:2])
        warning = f"{warning + ' ' if warning else ''}Capability fallback triggered: {error_warning}"
    return AgentResult(
        agent_name="web_intel",
        applicable=True,
        status=status,
        summary=summary,
        key_points=[*product_points[:3], *ir_highlights[:2], *positioning[:2]][:6],
        payload={
            "official_website": official_website,
            "product_points": product_points,
            "ir_highlights": ir_highlights,
            "positioning": positioning,
            "signal_bias": signal,
        },
        evidence=[EvidenceItem.model_validate(item) for item in scratchpad.get("evidence", [])],
        warning=warning,
        observations=observations,
    )
