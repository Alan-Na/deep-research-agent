from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Any

from app.agents.base import AgentDefinition, ToolDefinition
from app.agents.web_intel import (
    _crawl_pages,
    _discover_official_site,
    _extract_competitive_language,
    _extract_product_business,
)
from app.config import get_settings
from app.schemas import (
    AgentResult,
    EventItem,
    EvidenceItem,
    NewsExtractedMetric,
    NewsSignalAnalysis,
    NewsSignalDataQuality,
    NewsSignalEvent,
    ResearchBrief,
    SentimentName,
)
from app.tools.website import DefaultWebsiteDiscoveryAdapter, RequestsWebsiteCrawler
from app.utils.http import build_headers, request_json
from app.utils.logging import get_logger
from app.utils.text import dedupe_items, normalize_name, normalize_whitespace, truncate_text
from app.utils.time import days_ago_iso

logger = get_logger(__name__)

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

AGENT_NAME = "message_intel"
SIMHASH_DISTANCE_THRESHOLD = 3

EVENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "earnings": ["业绩", "预增", "预减", "年报", "季报", "营收", "净利润", "盈利", "亏损", "earnings", "profit", "revenue"],
    "contract_order": ["合同", "订单", "中标", "采购", "供应", "客户", "contract", "order", "tender", "supply"],
    "shareholder_change": ["减持", "增持", "持股", "股东", "stake", "shareholder"],
    "financing_buyback": ["融资", "定增", "配股", "回购", "债券", "募资", "buyback", "repurchase", "financing"],
    "regulatory_penalty": ["监管", "处罚", "问询", "立案", "调查", "罚款", "regulator", "penalty", "probe"],
    "lawsuit_arbitration": ["诉讼", "仲裁", "起诉", "纠纷", "lawsuit", "litigation", "arbitration"],
    "accident_recall": ["事故", "召回", "火灾", "停产", "安全", "recall", "accident"],
    "product_release": ["发布", "新品", "产品", "平台", "量产", "launch", "release", "product"],
    "partnership_ma": ["合作", "签约", "并购", "收购", "投资", "partnership", "acquisition", "merger"],
    "management_change": ["董事长", "总经理", "高管", "辞职", "任命", "ceo", "cfo", "resign", "appoint"],
    "capacity_expansion": ["产能", "扩产", "投产", "工厂", "项目", "capacity", "factory"],
    "policy_impact": ["政策", "补贴", "关税", "行业标准", "policy", "tariff", "subsidy"],
    "rating_research": ["评级", "研报", "目标价", "上调", "下调", "rating", "target price", "upgrade", "downgrade"],
    "dividend": ["分红", "派息", "股息", "dividend"],
}

LEGACY_CATEGORY_MAP = {
    "earnings": "earnings",
    "contract_order": "partnership",
    "shareholder_change": "financing",
    "financing_buyback": "financing",
    "regulatory_penalty": "regulation",
    "lawsuit_arbitration": "lawsuit",
    "accident_recall": "accident",
    "product_release": "product_release",
    "partnership_ma": "partnership",
    "management_change": "regulation",
    "capacity_expansion": "product_release",
    "policy_impact": "regulation",
    "rating_research": "earnings",
    "dividend": "financing",
    "other": "earnings",
}

CATEGORY_WEIGHTS = {
    "earnings": 0.18,
    "contract_order": 0.18,
    "shareholder_change": 0.17,
    "financing_buyback": 0.16,
    "regulatory_penalty": 0.24,
    "lawsuit_arbitration": 0.24,
    "accident_recall": 0.26,
    "product_release": 0.15,
    "partnership_ma": 0.17,
    "management_change": 0.14,
    "capacity_expansion": 0.15,
    "policy_impact": 0.2,
    "rating_research": 0.12,
    "dividend": 0.13,
    "other": 0.08,
}

POSITIVE_WORDS = ["增长", "预增", "上升", "中标", "签订", "合作", "回购", "分红", "盈利", "突破", "投产", "利好", "超预期", "upgrade", "beat"]
NEGATIVE_WORDS = ["下降", "下滑", "亏损", "减持", "处罚", "调查", "诉讼", "召回", "事故", "停产", "风险", "利空", "downgrade", "miss"]
METRIC_NAME_KEYWORDS = {
    "净利润": ["净利润", "归母净利润", "net income", "net profit"],
    "营收": ["营收", "营业收入", "收入", "revenue"],
    "订单金额": ["订单", "合同", "中标", "order", "contract"],
    "减持比例": ["减持", "持股比例"],
    "回购金额": ["回购"],
    "供应期限": ["期限", "年"],
    "销量": ["销量", "交付", "辆"],
}
METRIC_RE = re.compile(
    r"(?P<raw>(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>亿元人民币|亿元|万元|亿美元|美元|元|%|％|年|个月|万辆|辆|万股|亿股|股|GWh|MWh))",
    re.IGNORECASE,
)


def message_intel_agent_definition() -> AgentDefinition:
    discovery = DefaultWebsiteDiscoveryAdapter()
    crawler = RequestsWebsiteCrawler()
    return AgentDefinition(
        agent_name=AGENT_NAME,
        description="消息面 Agent：官网/IR 采集 + 可审计新闻信号抽取流水线。",
        enabled_capabilities=[
            "collect_website_intel",
            "collect_news_signals",
            "build_message_output",
        ],
        tool_registry={
            "collect_website_intel": ToolDefinition(
                name="collect_website_intel",
                description="Discover and crawl official website/IR pages, then extract business and positioning signals.",
                handler=lambda brief, shared, scratchpad: _collect_website_intel(discovery, crawler, brief),
            ),
            "collect_news_signals": ToolDefinition(
                name="collect_news_signals",
                description="Fetch company news, entity-link, SimHash dedupe, classify events, extract metrics, and score sentiment.",
                handler=_collect_news_signals,
            ),
            "build_message_output": ToolDefinition(
                name="build_message_output",
                description="Format structured message-side output for the main critic/output agent.",
                handler=_build_message_output,
            ),
        },
        output_model=AgentResult,
        finalize_handler=_finalize_message_intel_agent,
        timeout_seconds=get_settings().agent_timeout_seconds,
        max_steps=get_settings().agent_max_steps,
    )


def _collect_website_intel(
    discovery: DefaultWebsiteDiscoveryAdapter,
    crawler: RequestsWebsiteCrawler,
    brief: ResearchBrief,
) -> dict[str, Any]:
    local_scratchpad: dict[str, Any] = {"payload": {}, "evidence": [], "errors": []}
    summaries: list[str] = []

    for handler in (
        lambda: _discover_official_site(discovery, brief),
        lambda: _crawl_pages(crawler, brief, local_scratchpad),
        lambda: _extract_product_business(brief, {}, local_scratchpad),
        lambda: _extract_competitive_language(brief, {}, local_scratchpad),
    ):
        try:
            observation = handler()
        except Exception as exc:
            local_scratchpad["errors"].append(str(exc))
            continue
        _merge_observation(local_scratchpad, observation)
        if observation.get("summary"):
            summaries.append(str(observation["summary"]))

    payload = dict(local_scratchpad["payload"])
    payload["website_errors"] = local_scratchpad["errors"]
    return {
        "summary": " ".join(summaries) or "Website intelligence collection produced no usable observations.",
        "payload": payload,
        "evidence": _normalize_evidence(local_scratchpad["evidence"]),
    }


def _collect_news_signals(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    aliases = _build_entity_aliases(brief)
    warnings: list[str] = []
    raw_articles = _fetch_news_articles(brief, warnings)
    linked_articles = _filter_company_articles(raw_articles, aliases)
    clusters = _cluster_articles(linked_articles)
    events = [_build_news_signal_event(brief.company_name, aliases, cluster, warnings) for cluster in clusters]
    events = sorted(events, key=lambda item: (item.sentiment_score, item.duplicate_count, item.time or ""), reverse=True)
    analysis = _build_news_signal_analysis(brief.company_name, aliases, raw_articles, linked_articles, events, warnings)
    legacy_events = [_to_legacy_event(item) for item in analysis.events[:10]]
    return {
        "summary": f"Collected {len(raw_articles)} raw articles and extracted {len(analysis.events)} deduped news signal events.",
        "payload": {
            "news_signal_analysis": analysis.model_dump(),
            "scored_events": [item.model_dump() for item in analysis.events],
            "news_errors": warnings,
        },
        "events": [item.model_dump() for item in legacy_events],
        "evidence": _build_news_evidence(analysis.events),
    }


def _build_message_output(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    payload = scratchpad.get("payload", {}) or {}
    product_points = list(payload.get("product_points") or [])
    ir_highlights = list(payload.get("ir_highlights") or [])
    positioning = list(payload.get("positioning") or [])
    analysis_payload = payload.get("news_signal_analysis")
    analysis = NewsSignalAnalysis.model_validate(analysis_payload) if analysis_payload else _empty_news_signal_analysis(brief.company_name)
    signal_bias = _signal_bias_from_news(analysis, product_points, ir_highlights, positioning)
    takeaways = [
        *(event.one_line_summary for event in analysis.events[:4]),
        *product_points[:1],
        *ir_highlights[:1],
        *positioning[:1],
    ]
    return {
        "summary": "Built structured message-side output from news signals and website/IR signals.",
        "payload": {
            "message_insights": {
                "dominant_narrative": analysis.dominant_narrative,
                "signal_bias": signal_bias,
                "takeaways": list(dict.fromkeys([item for item in takeaways if item]))[:6],
            },
            "dominant_narrative": analysis.dominant_narrative,
            "signal_bias": signal_bias,
        },
    }


def _finalize_message_intel_agent(
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
    observations: list[Any],
) -> AgentResult:
    payload = dict(scratchpad.get("payload") or {})
    pages = payload.get("pages") or []
    official_website = payload.get("official_website")
    product_points = list(payload.get("product_points") or [])
    ir_highlights = list(payload.get("ir_highlights") or [])
    positioning = list(payload.get("positioning") or [])
    analysis_payload = payload.get("news_signal_analysis")
    analysis = NewsSignalAnalysis.model_validate(analysis_payload) if analysis_payload else _empty_news_signal_analysis(brief.company_name)
    events = [EventItem.model_validate(item) for item in scratchpad.get("events", [])]

    insights = payload.get("message_insights") or {}
    signal_bias = insights.get("signal_bias") or payload.get("signal_bias") or _signal_bias_from_news(
        analysis,
        product_points,
        ir_highlights,
        positioning,
    )
    dominant_narrative = insights.get("dominant_narrative") or payload.get("dominant_narrative") or analysis.dominant_narrative
    website_ok = bool(official_website and pages)
    news_ok = bool(analysis.events)
    status = "success" if website_ok and news_ok else "partial"

    warnings = []
    if not website_ok:
        warnings.append("Official website/IR discovery was weak or pages were inaccessible.")
    if not news_ok:
        warnings.append("No company-linked news signal events were extracted.")
    if scratchpad.get("errors"):
        warnings.extend(str(item) for item in scratchpad["errors"][:2])
    warnings.extend(str(item) for item in payload.get("website_errors") or [])
    warnings.extend(str(item) for item in payload.get("news_errors") or [])
    warnings.extend(analysis.warnings)

    key_points = list(insights.get("takeaways") or [])
    if not key_points:
        key_points = [
            *(event.one_line_summary for event in analysis.events[:4]),
            *product_points[:1],
            *ir_highlights[:1],
            *positioning[:1],
        ][:6]

    payload.update(
        {
            "official_website": official_website,
            "product_points": product_points,
            "ir_highlights": ir_highlights,
            "positioning": positioning,
            "dominant_narrative": dominant_narrative,
            "signal_bias": signal_bias,
            "events": [item.model_dump() for item in events],
            "news_signal_analysis": analysis.model_dump(),
        }
    )
    return AgentResult(
        agent_name=AGENT_NAME,
        applicable=True,
        status=status,
        summary=(
            f"消息面 Agent 已完成官网/IR 与新闻信号抽取："
            f"识别到 {len(product_points)} 条产品/业务线索、{len(ir_highlights)} 条 IR 线索、"
            f"{len(analysis.events)} 个新闻信号事件。{dominant_narrative}"
        ),
        key_points=list(dict.fromkeys([item for item in key_points if item]))[:6],
        payload=payload,
        events=events,
        evidence=[EvidenceItem.model_validate(item).model_copy(update={"agent_name": AGENT_NAME}) for item in scratchpad.get("evidence", [])],
        warning=" ".join(dict.fromkeys(warnings)) if warnings else None,
        observations=observations,
    )


def _build_entity_aliases(brief: ResearchBrief) -> list[str]:
    candidates = [
        brief.company_name,
        brief.instrument.display_name,
        brief.instrument.symbol,
        str(brief.instrument.symbol or "").replace("sh", "").replace("sz", ""),
    ]
    aliases: list[str] = []
    for item in candidates:
        raw = normalize_whitespace(str(item or ""))
        if not raw:
            continue
        aliases.append(raw)
        stripped = re.sub(r"（.*?）|\(.*?\)", "", raw).strip()
        if stripped and stripped != raw:
            aliases.append(stripped)
    return dedupe_items([item for item in aliases if len(item) >= 2], lambda item: normalize_name(item))


def _fetch_news_articles(brief: ResearchBrief, warnings: list[str]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    settings = get_settings()
    if brief.market == "A_SHARE" and brief.instrument.symbol and ak is not None:
        try:
            frame = ak.stock_news_em(symbol=brief.instrument.symbol)
            for _, row in frame.head(settings.max_news_articles).iterrows():
                articles.append(
                    {
                        "title": normalize_whitespace(str(row.get("新闻标题") or "")),
                        "summary": normalize_whitespace(str(row.get("新闻内容") or "")),
                        "content": normalize_whitespace(str(row.get("新闻内容") or "")),
                        "date": str(row.get("发布时间") or "")[:19],
                        "source": str(row.get("文章来源") or ""),
                        "url": str(row.get("新闻链接") or ""),
                    }
                )
        except Exception as exc:
            warnings.append(f"A-share news fetch failed: {exc}")
            logger.exception("A-share news fetch failed for %s.", brief.company_name)

    if not articles and settings.newsapi_key:
        payload = request_json(
            "https://newsapi.org/v2/everything",
            params={
                "q": brief.company_name,
                "from": days_ago_iso(settings.news_days),
                "sortBy": "publishedAt",
                "pageSize": settings.max_news_articles,
            },
            headers={"X-Api-Key": settings.newsapi_key, **build_headers()},
        )
        for item in payload.get("articles", []):
            articles.append(
                {
                    "title": normalize_whitespace(str(item.get("title") or "")),
                    "summary": normalize_whitespace(str(item.get("description") or "")),
                    "content": normalize_whitespace(str(item.get("content") or item.get("description") or "")),
                    "date": str(item.get("publishedAt") or ""),
                    "source": str((item.get("source") or {}).get("name") or ""),
                    "url": str(item.get("url") or ""),
                }
            )
    return dedupe_items([item for item in articles if item.get("title")], lambda item: f"{item.get('title')}|{item.get('url')}")


def _filter_company_articles(articles: list[dict[str, Any]], aliases: list[str]) -> list[dict[str, Any]]:
    return [item for item in articles if _article_matches_company(item, aliases)]


def _article_matches_company(article: dict[str, Any], aliases: list[str]) -> bool:
    text = normalize_name(_article_text(article))
    return any(normalize_name(alias) in text for alias in aliases if alias)


def _article_text(article: dict[str, Any]) -> str:
    return " ".join(
        [
            str(article.get("title") or ""),
            str(article.get("summary") or ""),
            str(article.get("content") or ""),
        ]
    )


def _cluster_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for article in articles:
        signature = _simhash(f"{article.get('title') or ''} {str(article.get('content') or article.get('summary') or '')[:200]}")
        normalized_title = normalize_name(str(article.get("title") or ""))
        matched = None
        for cluster in clusters:
            same_title = normalized_title and normalized_title == cluster.get("normalized_title")
            if same_title or _hamming_distance(signature, cluster["signature"]) <= SIMHASH_DISTANCE_THRESHOLD:
                matched = cluster
                break
        if matched is None:
            clusters.append({"signature": signature, "normalized_title": normalized_title, "items": [article]})
        else:
            matched["items"].append(article)
    for cluster in clusters:
        items = cluster["items"]
        representative = max(items, key=lambda item: len(_article_text(item)))
        cluster["representative"] = representative
        cluster["sources"] = dedupe_items([str(item.get("source") or "") for item in items if item.get("source")], lambda item: item)
        cluster["source_urls"] = dedupe_items([str(item.get("url") or "") for item in items if item.get("url")], lambda item: item)
    clusters.sort(key=lambda item: (len(item["items"]), str(item["representative"].get("date") or "")), reverse=True)
    return clusters


def _simhash(text: str, bits: int = 64) -> int:
    vector = [0] * bits
    for token in _simhash_tokens(text):
        digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for index in range(bits):
            vector[index] += 1 if digest & (1 << index) else -1
    result = 0
    for index, value in enumerate(vector):
        if value >= 0:
            result |= 1 << index
    return result


def _simhash_tokens(text: str) -> list[str]:
    normalized = normalize_name(text)
    if not normalized:
        return ["empty"]
    if " " in normalized:
        return [token for token in normalized.split() if token]
    return [normalized[index : index + 2] for index in range(max(len(normalized) - 1, 1))]


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _build_news_signal_event(
    company: str,
    aliases: list[str],
    cluster: dict[str, Any],
    warnings: list[str],
) -> NewsSignalEvent:
    article = cluster["representative"]
    text = _article_text(article)
    category, matched_keywords = _classify_news_category(text)
    metrics = _extract_news_metrics(text)
    sentiment_text = _company_context_text(article, aliases)
    sentiment, score, probs, method, warning = _analyze_sentiment(sentiment_text)
    if warning:
        warnings.append(warning)
    event_id = _event_id(article)
    metric_keywords = [item.raw_text for item in metrics[:3]]
    keywords = list(dict.fromkeys([*matched_keywords[:5], *metric_keywords]))
    return NewsSignalEvent(
        event_id=event_id,
        time=article.get("date"),
        category=category,
        title=str(article.get("title") or ""),
        summary=truncate_text(str(article.get("summary") or article.get("content") or article.get("title") or ""), 280),
        keywords=keywords[:8],
        extracted_metrics=metrics,
        sentiment=sentiment,
        sentiment_score=score,
        sentiment_probs=probs,
        sentiment_method=method,
        source_title=str(article.get("title") or ""),
        source_url=article.get("url"),
        sources=cluster.get("sources") or [],
        source_urls=cluster.get("source_urls") or [],
        duplicate_count=len(cluster.get("items") or []),
        one_line_summary=_one_line_summary(company, category, keywords, sentiment),
        audit_trail={
            "simhash": cluster.get("signature"),
            "matched_keywords": matched_keywords,
            "representative_url": article.get("url"),
            "cluster_size": len(cluster.get("items") or []),
            "sentiment_input": truncate_text(sentiment_text, 260),
        },
    )


def _classify_news_category(text: str) -> tuple[str, list[str]]:
    lowered = normalize_name(text)
    for category, keywords in EVENT_TYPE_KEYWORDS.items():
        matched = [keyword for keyword in keywords if normalize_name(keyword) in lowered]
        if matched:
            return category, matched
    return "other", []


def _extract_news_metrics(text: str) -> list[NewsExtractedMetric]:
    metrics: list[NewsExtractedMetric] = []
    for match in METRIC_RE.finditer(text):
        raw = match.group("raw")
        start = max(0, match.start() - 24)
        context = text[start : min(len(text), match.end() + 12)]
        unit = match.group("unit")
        name = _infer_metric_name(context, unit)
        try:
            value = float(match.group("value"))
        except Exception:
            value = None
        metrics.append(
            NewsExtractedMetric(
                name=name,
                value=value,
                unit=unit,
                raw_text=raw,
            )
        )
    return metrics[:10]


def _infer_metric_name(context: str, unit: str | None = None) -> str:
    normalized = normalize_name(context)
    if unit in {"年", "个月"} and any(token in normalized for token in ["期限", "供应", "合同"]):
        return "供应期限"
    if unit in {"辆", "万辆"} and any(token in normalized for token in ["销量", "交付"]):
        return "销量"
    for name, keywords in METRIC_NAME_KEYWORDS.items():
        if any(normalize_name(keyword) in normalized for keyword in keywords):
            return name
    return "numeric_value"


def _company_context_text(article: dict[str, Any], aliases: list[str]) -> str:
    text = _article_text(article)
    sentences = re.split(r"[。！？!?；;\n]", text)
    matched = [
        normalize_whitespace(sentence)
        for sentence in sentences
        if sentence and any(normalize_name(alias) in normalize_name(sentence) for alias in aliases)
    ]
    return "。".join(matched[:4]) or truncate_text(text, get_settings().finbert_max_chars)


def _analyze_sentiment(text: str) -> tuple[SentimentName, float, dict[str, float], str, str | None]:
    settings = get_settings()
    if settings.enable_finbert_sentiment:
        try:
            result = _run_finbert(text[: settings.finbert_max_chars])
            if result:
                return (*result, "finbert_chinese", None)
        except Exception as exc:
            return (*_rule_sentiment(text), "rule_fallback", f"FinBERT sentiment unavailable, used rule fallback: {exc}")
    sentiment, score, probs = _rule_sentiment(text)
    return sentiment, score, probs, "rule_fallback", None


@lru_cache(maxsize=1)
def _finbert_pipeline():
    from transformers import pipeline

    return pipeline("text-classification", model=get_settings().finbert_chinese_model, top_k=None)


def _run_finbert(text: str) -> tuple[SentimentName, float, dict[str, float]] | None:
    raw = _finbert_pipeline()(text)
    items = raw[0] if raw and isinstance(raw[0], list) else raw
    probs = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    for item in items or []:
        label = _normalize_sentiment_label(str(item.get("label") or ""))
        if label in probs:
            probs[label] = float(item.get("score") or 0.0)
    if not any(probs.values()):
        return None
    sentiment = max(probs, key=lambda key: probs[key])
    return sentiment, round(probs[sentiment], 4), {key: round(value, 4) for key, value in probs.items()}


def _normalize_sentiment_label(label: str) -> SentimentName | str:
    lowered = label.lower()
    if any(token in lowered for token in ["positive", "pos", "正", "积极", "利好"]):
        return "positive"
    if any(token in lowered for token in ["negative", "neg", "负", "消极", "利空"]):
        return "negative"
    if any(token in lowered for token in ["neutral", "neu", "中"]):
        return "neutral"
    return lowered


def _rule_sentiment(text: str) -> tuple[SentimentName, float, dict[str, float]]:
    lowered = normalize_name(text)
    positive_hits = sum(1 for keyword in POSITIVE_WORDS if normalize_name(keyword) in lowered)
    negative_hits = sum(1 for keyword in NEGATIVE_WORDS if normalize_name(keyword) in lowered)
    if positive_hits > negative_hits:
        score = min(0.9, 0.55 + positive_hits * 0.08)
        return "positive", round(score, 4), {"positive": round(score, 4), "neutral": round(1 - score, 4), "negative": 0.0}
    if negative_hits > positive_hits:
        score = min(0.9, 0.55 + negative_hits * 0.08)
        return "negative", round(score, 4), {"positive": 0.0, "neutral": round(1 - score, 4), "negative": round(score, 4)}
    return "neutral", 0.6, {"positive": 0.2, "neutral": 0.6, "negative": 0.2}


def _build_news_signal_analysis(
    company: str,
    aliases: list[str],
    raw_articles: list[dict[str, Any]],
    linked_articles: list[dict[str, Any]],
    events: list[NewsSignalEvent],
    warnings: list[str],
) -> NewsSignalAnalysis:
    narrative = _dominant_narrative(events)
    confidence = 0.0 if not raw_articles else min(0.95, 0.3 + len(events) * 0.08 + len(linked_articles) / max(len(raw_articles), 1) * 0.35)
    status = "success" if events else "partial"
    data_quality = NewsSignalDataQuality(status=status, confidence=round(confidence, 2), warnings=list(dict.fromkeys(warnings)))
    return NewsSignalAnalysis(
        company=company,
        entity_aliases=aliases,
        raw_article_count=len(raw_articles),
        deduped_event_count=len(events),
        events=events,
        dominant_narrative=narrative,
        data_quality=data_quality,
        warnings=list(dict.fromkeys(warnings)),
    )


def _dominant_narrative(events: list[NewsSignalEvent]) -> str:
    if not events:
        return "近期没有抽取到可审计的公司相关新闻信号。"
    positive = len([event for event in events if event.sentiment == "positive"])
    negative = len([event for event in events if event.sentiment == "negative"])
    if positive > negative:
        return "近期新闻信号更偏向正面催化。"
    if negative > positive:
        return "近期新闻信号更偏向风险事件。"
    return "近期新闻信号整体偏中性。"


def _signal_bias_from_news(
    analysis: NewsSignalAnalysis,
    product_points: list[str],
    ir_highlights: list[str],
    positioning: list[str],
) -> str:
    positive = len([event for event in analysis.events if event.sentiment == "positive"])
    negative = len([event for event in analysis.events if event.sentiment == "negative"])
    high_risk = any(event.category in {"regulatory_penalty", "lawsuit_arbitration", "accident_recall"} and event.sentiment == "negative" for event in analysis.events)
    if high_risk or negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    if product_points or ir_highlights or positioning:
        return "positive"
    return "neutral"


def _to_legacy_event(event: NewsSignalEvent) -> EventItem:
    impact = _impact_score(event)
    return EventItem(
        title=event.title,
        category=LEGACY_CATEGORY_MAP.get(event.category, "earnings"),  # type: ignore[arg-type]
        horizon=_classify_horizon(event.category, event.sentiment, impact),  # type: ignore[arg-type]
        sentiment=event.sentiment,
        impact_score=impact,
        confidence_score=_confidence_score(event),
        date=event.time,
        summary=event.one_line_summary,
        source_ids=event.source_urls[:5] or ([event.source_url] if event.source_url else []),
    )


def _impact_score(event: NewsSignalEvent) -> float:
    score = 0.35 + CATEGORY_WEIGHTS.get(event.category, 0.08)
    score += min(0.18, event.duplicate_count * 0.04)
    score += 0.08 if event.extracted_metrics else 0.0
    score += 0.08 if event.sentiment in {"positive", "negative"} and event.sentiment_score >= 0.75 else 0.0
    return round(min(1.0, score), 2)


def _confidence_score(event: NewsSignalEvent) -> float:
    score = 0.45 + min(0.2, event.duplicate_count * 0.04) + (event.sentiment_score * 0.25)
    if event.extracted_metrics:
        score += 0.06
    return round(min(1.0, score), 2)


def _classify_horizon(category: str, sentiment: SentimentName, impact: float) -> str:
    if category in {"contract_order", "product_release", "partnership_ma", "capacity_expansion", "policy_impact"}:
        return "mid_term_catalyst"
    if category in {"regulatory_penalty", "lawsuit_arbitration", "accident_recall"}:
        return "mid_term_catalyst"
    if impact >= 0.72 or sentiment in {"positive", "negative"}:
        return "mid_term_catalyst"
    return "short_term_noise"


def _build_news_evidence(events: list[NewsSignalEvent]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for event in events[:10]:
        evidence.append(
            EvidenceItem(
                agent_name=AGENT_NAME,
                source_type="news_article",
                category="news_signal_event",
                title=event.title,
                date=event.time,
                url=event.source_url,
                snippet=truncate_text(event.one_line_summary, 320),
                metadata={"event_id": event.event_id, "category": event.category, "duplicate_count": event.duplicate_count},
            ).model_dump()
        )
        evidence.append(
            EvidenceItem(
                agent_name=AGENT_NAME,
                source_type="news_article",
                category="news_sentiment_signal",
                title=f"{event.title} sentiment",
                date=event.time,
                url=event.source_url,
                snippet=truncate_text(f"{event.sentiment} score={event.sentiment_score}; method={event.sentiment_method}", 260),
                metadata={"event_id": event.event_id, "sentiment_probs": event.sentiment_probs},
            ).model_dump()
        )
        if event.extracted_metrics:
            evidence.append(
                EvidenceItem(
                    agent_name=AGENT_NAME,
                    source_type="news_article",
                    category="news_metric_extract",
                    title=f"{event.title} metrics",
                    date=event.time,
                    url=event.source_url,
                    snippet=truncate_text("; ".join(item.raw_text for item in event.extracted_metrics), 260),
                    metadata={"event_id": event.event_id, "metrics": [item.model_dump() for item in event.extracted_metrics[:5]]},
                ).model_dump()
            )
    return evidence


def _one_line_summary(company: str, category: str, keywords: list[str], sentiment: SentimentName) -> str:
    category_text = _category_display(category)
    sentiment_text = {"positive": "正面", "neutral": "中性", "negative": "负面"}[sentiment]
    details = "、".join(keywords[:3]) if keywords else "未抽取到关键数字"
    return f"{company}发生{category_text}：涉及{details}，情感判断为{sentiment_text}。"


def _category_display(category: str) -> str:
    mapping = {
        "earnings": "业绩事件",
        "contract_order": "合同订单事件",
        "shareholder_change": "股东持股变化",
        "financing_buyback": "融资回购事件",
        "regulatory_penalty": "监管处罚事件",
        "lawsuit_arbitration": "诉讼仲裁事件",
        "accident_recall": "事故召回事件",
        "product_release": "产品发布事件",
        "partnership_ma": "合作并购事件",
        "management_change": "高管变动事件",
        "capacity_expansion": "产能扩张事件",
        "policy_impact": "政策影响事件",
        "rating_research": "评级研报事件",
        "dividend": "分红事件",
        "other": "其他消息事件",
    }
    return mapping.get(category, "消息事件")


def _event_id(article: dict[str, Any]) -> str:
    raw = "|".join([str(article.get("title") or ""), str(article.get("date") or ""), str(article.get("url") or "")])
    return f"evt_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def _empty_news_signal_analysis(company: str) -> NewsSignalAnalysis:
    return NewsSignalAnalysis(
        company=company,
        data_quality=NewsSignalDataQuality(status="partial", confidence=0.0, warnings=["news_signal_analysis_missing"]),
        dominant_narrative="近期没有抽取到可审计的公司相关新闻信号。",
        warnings=["news_signal_analysis_missing"],
    )


def _merge_observation(scratchpad: dict[str, Any], observation: dict[str, Any]) -> None:
    if isinstance(observation.get("payload"), dict):
        scratchpad["payload"].update(observation["payload"])
    if isinstance(observation.get("evidence"), list):
        scratchpad["evidence"].extend(observation["evidence"])
    if isinstance(observation.get("events"), list):
        scratchpad["events"].extend(observation["events"])


def _normalize_evidence(items: list[Any]) -> list[dict[str, Any]]:
    return [
        EvidenceItem.model_validate(item).model_copy(update={"agent_name": AGENT_NAME}).model_dump()
        for item in items
    ]
