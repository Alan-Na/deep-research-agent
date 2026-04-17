from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.agents.base import AgentDefinition, ToolDefinition
from app.config import get_settings
from app.schemas import AgentResult, EventItem, EvidenceItem, ResearchBrief
from app.utils.http import build_headers, request_json
from app.utils.logging import get_logger
from app.utils.text import dedupe_items, normalize_name, normalize_whitespace, truncate_text
from app.utils.time import days_ago_iso

logger = get_logger(__name__)

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


EVENT_KEYWORDS = {
    "earnings": ["业绩", "年报", "季报", "营收", "净利润", "dividend", "earnings", "guidance"],
    "product_release": ["发布", "新品", "产品", "平台", "launch", "release"],
    "regulation": ["监管", "问询", "处罚", "停牌", "regulation", "probe"],
    "lawsuit": ["诉讼", "仲裁", "违法", "lawsuit", "litigation"],
    "partnership": ["合作", "签约", "订单", "partnership", "joint"],
    "layoff": ["裁员", "优化", "layoff"],
    "financing": ["融资", "定增", "回购", "债券", "募资", "financing", "buyback"],
    "accident": ["事故", "召回", "火灾", "停产", "安全", "accident", "recall"],
}
POSITIVE_WORDS = ["增长", "超预期", "中标", "合作", "新产品", "分红", "盈利", "record", "beat", "upgrade"]
NEGATIVE_WORDS = ["下降", "亏损", "调查", "处罚", "风险", "诉讼", "裁员", "事故", "miss", "downgrade"]


def news_risk_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_name="news_risk",
        description="Cluster news into scored events and judge noise versus catalysts.",
        enabled_capabilities=[
            "fetch_company_news",
            "dedupe_cluster_news",
            "classify_news_events",
            "score_merged_events",
        ],
        tool_registry={
            "fetch_company_news": ToolDefinition(
                name="fetch_company_news",
                description="Fetch raw company news from Eastmoney or NewsAPI.",
                handler=_fetch_company_news,
            ),
            "dedupe_cluster_news": ToolDefinition(
                name="dedupe_cluster_news",
                description="Dedupe headlines and merge near-duplicate news into topic clusters.",
                handler=_dedupe_cluster_news,
            ),
            "classify_news_events": ToolDefinition(
                name="classify_news_events",
                description="Classify merged clusters into event types and narratives.",
                handler=_classify_news_events,
            ),
            "score_merged_events": ToolDefinition(
                name="score_merged_events",
                description="Score impact/confidence and determine noise versus catalyst horizon.",
                handler=_score_merged_events,
            ),
        },
        output_model=AgentResult,
        finalize_handler=_finalize_news_risk_agent,
        timeout_seconds=get_settings().agent_timeout_seconds,
        max_steps=get_settings().agent_max_steps,
    )


def _fetch_company_news(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    articles: list[dict[str, Any]] = []
    if brief.market == "A_SHARE" and brief.instrument.symbol and ak is not None:
        try:
            frame = ak.stock_news_em(symbol=brief.instrument.symbol)
            for _, row in frame.head(get_settings().max_news_articles).iterrows():
                articles.append(
                    {
                        "title": normalize_whitespace(str(row.get("新闻标题") or "")),
                        "summary": normalize_whitespace(str(row.get("新闻内容") or "")),
                        "date": str(row.get("发布时间") or "")[:19],
                        "source": str(row.get("文章来源") or ""),
                        "url": str(row.get("新闻链接") or ""),
                    }
                )
        except Exception:
            logger.exception("A-share news fetch failed for %s.", brief.company_name)

    if not articles and get_settings().newsapi_key:
        payload = request_json(
            "https://newsapi.org/v2/everything",
            params={
                "q": brief.company_name,
                "from": days_ago_iso(get_settings().news_days),
                "sortBy": "publishedAt",
                "pageSize": get_settings().max_news_articles,
            },
            headers={"X-Api-Key": get_settings().newsapi_key, **build_headers()},
        )
        for item in payload.get("articles", []):
            articles.append(
                {
                    "title": normalize_whitespace(str(item.get("title") or "")),
                    "summary": normalize_whitespace(str(item.get("description") or item.get("content") or "")),
                    "date": str(item.get("publishedAt") or ""),
                    "source": str((item.get("source") or {}).get("name") or ""),
                    "url": str(item.get("url") or ""),
                }
            )

    deduped = dedupe_items(
        [item for item in articles if item.get("title") and item.get("url")],
        lambda item: f"{normalize_name(item['title'])}|{item['url']}",
    )
    evidence = [
        EvidenceItem(
            agent_name="news_risk",
            source_type="news_article",
            category="news_article",
            title=item["title"],
            date=item.get("date"),
            url=item.get("url"),
            snippet=truncate_text(item.get("summary") or item["title"], 260),
            metadata={"source": item.get("source")},
        ).model_dump()
        for item in deduped[:10]
    ]
    return {
        "summary": f"Fetched {len(deduped)} raw news articles.",
        "payload": {"articles": deduped},
        "evidence": evidence,
    }


def _dedupe_cluster_news(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    articles = scratchpad.get("payload", {}).get("articles") or []
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    company_tokens = set(normalize_name(brief.company_name).split())
    for item in articles:
        tokens = [token for token in normalize_name(item["title"]).split() if token not in company_tokens]
        key = " ".join(tokens[:6]) or normalize_name(item["title"])
        clusters[key].append(item)
    merged_clusters = [
        {
            "cluster_key": cluster_key,
            "count": len(items),
            "representative": items[0],
            "items": items,
        }
        for cluster_key, items in clusters.items()
    ]
    merged_clusters.sort(key=lambda item: (item["count"], item["representative"].get("date") or ""), reverse=True)
    return {
        "summary": f"Merged {len(articles)} articles into {len(merged_clusters)} topic clusters.",
        "payload": {"clusters": merged_clusters},
    }


def _classify_news_events(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    clusters = scratchpad.get("payload", {}).get("clusters") or []
    events: list[dict[str, Any]] = []
    for cluster in clusters[:8]:
        representative = cluster["representative"]
        combined_text = " ".join(
            [
                representative.get("title") or "",
                representative.get("summary") or "",
                " ".join(item.get("title") or "" for item in cluster["items"][1:3]),
            ]
        )
        category = _classify_category(combined_text)
        sentiment = _classify_sentiment(combined_text)
        events.append(
            {
                "title": representative["title"],
                "category": category,
                "sentiment": sentiment,
                "summary": truncate_text(representative.get("summary") or representative["title"], 220),
                "date": representative.get("date"),
                "count": cluster["count"],
                "source_ids": [item.get("url") for item in cluster["items"] if item.get("url")][:5],
            }
        )
    return {
        "summary": f"Classified {len(events)} merged news events.",
        "payload": {"classified_events": events},
    }


def _score_merged_events(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    classified_events = scratchpad.get("payload", {}).get("classified_events") or []
    scored_events: list[dict[str, Any]] = []
    for item in classified_events:
        category = item["category"]
        cluster_count = int(item.get("count") or 1)
        impact = min(1.0, 0.35 + (cluster_count * 0.1) + _category_weight(category))
        confidence = min(1.0, 0.45 + (cluster_count * 0.08))
        horizon = _classify_horizon(category, item["sentiment"], impact)
        scored_events.append(
            {
                **item,
                "impact_score": round(impact, 2),
                "confidence_score": round(confidence, 2),
                "horizon": horizon,
            }
        )
    scored_events.sort(key=lambda item: (item["impact_score"], item["confidence_score"]), reverse=True)
    return {
        "summary": f"Scored {len(scored_events)} news events for impact and confidence.",
        "payload": {"scored_events": scored_events},
    }


def _finalize_news_risk_agent(
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
    observations: list[Any],
) -> AgentResult:
    payload = dict(scratchpad.get("payload") or {})
    scored_events = payload.get("scored_events") or []
    events = [
        EventItem.model_validate({key: value for key, value in item.items() if key in EventItem.model_fields})
        for item in scored_events
    ]
    positive = len([item for item in scored_events if item["sentiment"] == "positive"])
    negative = len([item for item in scored_events if item["sentiment"] == "negative"])
    dominant_narrative = "事件驱动偏中性。"
    signal_bias = "neutral"
    if positive > negative:
        dominant_narrative = "近期新闻更偏向正向催化。"
        signal_bias = "positive"
    elif negative > positive:
        dominant_narrative = "近期新闻更偏向风险事件。"
        signal_bias = "negative"
    status = "success" if scored_events else "partial"
    warning = None if scored_events else "No usable news events were classified."
    if scratchpad.get("errors"):
        status = "partial"
        error_warning = " | ".join(str(item) for item in scratchpad["errors"][:2])
        warning = f"{warning + ' ' if warning else ''}Capability fallback triggered: {error_warning}"
    return AgentResult(
        agent_name="news_risk",
        applicable=True,
        status=status,
        summary=f"News/Risk Agent 已完成新闻聚类与事件打分。{dominant_narrative}",
        key_points=[
            f"{item.title} | {item.category} | impact {item.impact_score} | confidence {item.confidence_score}"
            for item in events[:5]
        ],
        payload={
            "dominant_narrative": dominant_narrative,
            "signal_bias": signal_bias,
            "events": [item.model_dump() for item in events],
        },
        events=events,
        evidence=[EvidenceItem.model_validate(item) for item in scratchpad.get("evidence", [])],
        warning=warning,
        observations=observations,
    )


def _classify_category(text: str) -> str:
    lowered = normalize_name(text)
    for category, keywords in EVENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "earnings"


def _classify_sentiment(text: str) -> str:
    lowered = normalize_name(text)
    if any(keyword in lowered for keyword in NEGATIVE_WORDS):
        return "negative"
    if any(keyword in lowered for keyword in POSITIVE_WORDS):
        return "positive"
    return "neutral"


def _category_weight(category: str) -> float:
    mapping = {
        "earnings": 0.18,
        "product_release": 0.16,
        "regulation": 0.22,
        "lawsuit": 0.22,
        "partnership": 0.18,
        "layoff": 0.2,
        "financing": 0.18,
        "accident": 0.24,
    }
    return mapping.get(category, 0.12)


def _classify_horizon(category: str, sentiment: str, impact: float) -> str:
    if category in {"earnings"} and impact < 0.7:
        return "short_term_noise"
    if category in {"product_release", "partnership", "financing"} and sentiment == "positive":
        return "mid_term_catalyst"
    if category in {"regulation", "lawsuit", "layoff", "accident"}:
        return "mid_term_catalyst"
    return "mid_term_catalyst" if impact >= 0.72 else "short_term_noise"
