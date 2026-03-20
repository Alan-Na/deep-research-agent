from __future__ import annotations

import json
from collections import defaultdict

from langchain_core.prompts import ChatPromptTemplate

from app.config import get_settings
from app.llm import get_chat_model, is_llm_available
from app.prompts import NEWS_ANALYSIS_SYSTEM_PROMPT, NEWS_ANALYSIS_USER_PROMPT
from app.routers import build_skipped_result, route_news
from app.schemas import CompanyIdentifiers, ModuleResult, NewsInsights, PlannerOutput, EvidenceCard, TimelineEvent
from app.tools.base import NewsArticleRecord, NewsDataAdapter
from app.utils.http import build_headers, request_json
from app.utils.logging import get_logger
from app.utils.text import dedupe_items, extract_domain, normalize_name, truncate_text
from app.utils.time import days_ago_iso

logger = get_logger(__name__)

LOW_QUALITY_DOMAINS = {
    "youtube.com",
    "tiktok.com",
    "facebook.com",
    "instagram.com",
}


class NewsApiAdapter(NewsDataAdapter):
    # 使用 NewsAPI Everything 接口获取近期文章元数据。
    def fetch(self, company_name: str, *, from_date: str, page_size: int = 20) -> list[NewsArticleRecord]:
        settings = get_settings()
        if not settings.newsapi_key:
            raise RuntimeError("NEWSAPI_KEY is not configured.")

        payload = request_json(
            "https://newsapi.org/v2/everything",
            params={
                "q": company_name,
                "from": from_date,
                "sortBy": "publishedAt",
                "pageSize": min(page_size, 100),
            },
            headers={"X-Api-Key": settings.newsapi_key, **build_headers()},
        )

        records: list[NewsArticleRecord] = []
        for article in payload.get("articles", []):
            source = article.get("source", {}) or {}
            records.append(
                NewsArticleRecord(
                    title=article.get("title") or "",
                    source=source.get("name") or "",
                    published_at=article.get("publishedAt") or "",
                    url=article.get("url") or "",
                    description=article.get("description") or "",
                    content=article.get("content") or "",
                )
            )
        return records


def _article_quality_ok(article: NewsArticleRecord) -> bool:
    if not article.title or not article.url or not article.source:
        return False
    if len(article.title.strip()) < 12:
        return False
    if "[removed]" in article.title.lower():
        return False
    domain = extract_domain(article.url) or ""
    if any(domain.endswith(bad) for bad in LOW_QUALITY_DOMAINS):
        return False
    return True


def _dedupe_and_sort_articles(articles: list[NewsArticleRecord]) -> list[NewsArticleRecord]:
    cleaned = [article for article in articles if _article_quality_ok(article)]
    deduped = dedupe_items(
        cleaned,
        lambda item: f"{normalize_name(item.title)}|{item.url}",
    )
    deduped.sort(key=lambda item: item.published_at, reverse=True)
    return deduped


def _topic_key(title: str, company_name: str) -> str:
    company_tokens = set(normalize_name(company_name).split())
    tokens = [
        token
        for token in normalize_name(title).split()
        if token and token not in company_tokens
    ]
    return " ".join(tokens[:6]) or normalize_name(title)


def _build_topic_clusters(articles: list[NewsArticleRecord], company_name: str) -> dict[str, list[dict[str, str]]]:
    clusters: dict[str, list[dict[str, str]]] = defaultdict(list)
    for article in articles:
        key = _topic_key(article.title, company_name)
        clusters[key].append(
            {
                "title": article.title,
                "date": article.published_at,
                "source": article.source,
                "url": article.url,
                "description": article.description,
            }
        )
    return dict(clusters)


def _keyword_sentiment(title: str) -> str:
    lowered = title.lower()
    positive_words = ["beat", "surge", "growth", "record", "win", "launch", "partnership", "upgrade", "profit"]
    negative_words = ["miss", "fall", "drop", "lawsuit", "probe", "layoff", "recall", "downgrade", "loss"]
    if any(word in lowered for word in negative_words):
        return "negative"
    if any(word in lowered for word in positive_words):
        return "positive"
    return "neutral"


def _heuristic_news_analysis(company_name: str, articles: list[NewsArticleRecord], clusters: dict[str, list[dict[str, str]]]) -> NewsInsights:
    positive_events: list[str] = []
    neutral_events: list[str] = []
    negative_events: list[str] = []
    timeline: list[TimelineEvent] = []

    for article in articles[:8]:
        bucket = _keyword_sentiment(article.title)
        if bucket == "positive":
            positive_events.append(article.title)
        elif bucket == "negative":
            negative_events.append(article.title)
        else:
            neutral_events.append(article.title)

        timeline.append(
            TimelineEvent(
                date=article.published_at,
                title=article.title,
                sentiment=bucket,
                summary=truncate_text(article.description or article.content or article.title, 180),
                url=article.url,
            )
        )

    summary = f"Recent news review for {company_name} was generated with heuristic fallback from processed articles."
    dominant_narrative = "Coverage is mixed and based on article metadata only."
    if negative_events and len(negative_events) > len(positive_events):
        dominant_narrative = "Recent coverage leans cautious or negative."
    elif positive_events and len(positive_events) > len(negative_events):
        dominant_narrative = "Recent coverage leans constructive or positive."

    return NewsInsights(
        summary=summary,
        positive_events=positive_events[:5],
        neutral_events=neutral_events[:5],
        negative_events=negative_events[:5],
        dominant_narrative=dominant_narrative,
        event_timeline=timeline[:8],
    )


def _analyze_news_with_llm(company_name: str, articles: list[NewsArticleRecord], clusters: dict[str, list[dict[str, str]]]) -> NewsInsights:
    if not is_llm_available():
        return _heuristic_news_analysis(company_name, articles, clusters)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", NEWS_ANALYSIS_SYSTEM_PROMPT),
            ("human", NEWS_ANALYSIS_USER_PROMPT),
        ]
    )

    article_payload = [
        {
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at,
            "url": article.url,
            "description": truncate_text(article.description or article.content or article.title, 280),
        }
        for article in articles[:12]
    ]

    try:
        llm = get_chat_model(temperature=0.1)
        structured_llm = llm.with_structured_output(NewsInsights, method="json_schema")
        result = (prompt | structured_llm).invoke(
            {
                "company_name": company_name,
                "articles_payload": json.dumps(article_payload, ensure_ascii=False, indent=2),
                "clusters_payload": json.dumps(clusters, ensure_ascii=False, indent=2),
            }
        )
        return NewsInsights.model_validate(result)
    except Exception:
        logger.exception("News LLM analysis failed. Falling back to heuristic summary.")
        return _heuristic_news_analysis(company_name, articles, clusters)


def run_news_module(
    company_name: str,
    planner_output: PlannerOutput,
    identifiers: CompanyIdentifiers,
    *,
    adapter: NewsDataAdapter | None = None,
) -> tuple[ModuleResult, CompanyIdentifiers]:
    decision = route_news(planner_output)
    if not decision.should_run:
        return build_skipped_result("news", decision.reason), identifiers

    settings = get_settings()
    adapter = adapter or NewsApiAdapter()

    try:
        raw_articles = adapter.fetch(
            company_name,
            from_date=days_ago_iso(14),  # <--- 修改在这里：固定为过去 14 天
            page_size=settings.max_news_articles,
        )
        articles = _dedupe_and_sort_articles(raw_articles)

        if not articles:
            result = ModuleResult(
                module="news",
                applicable=True,
                status="partial",
                summary="News module ran but returned no useful recent articles.",
                reason="No recent news found.",
                warning="Recent news coverage was empty after filtering and deduplication.",
            )
            return result, identifiers

        clusters = _build_topic_clusters(articles, company_name)
        insights = _analyze_news_with_llm(company_name, articles, clusters)

        evidence = [
            EvidenceCard(
                module="news",
                source_type="news_article",
                title=article.title,
                date=article.published_at,
                snippet=truncate_text(article.description or article.content or article.title, 320),
                url=article.url,
            )
            for article in articles[:10]
        ]

        key_points = insights.positive_events[:2] + insights.neutral_events[:2] + insights.negative_events[:2]

        result = ModuleResult(
            module="news",
            applicable=True,
            status="success",
            summary=insights.summary,
            key_points=key_points,
            event_timeline=insights.event_timeline,
            evidence=evidence,
            metrics={
                "article_count": len(articles),
                "cluster_count": len(clusters),
                "dominant_narrative": insights.dominant_narrative,
            },
        )
        return result, identifiers
    except Exception as exc:
        logger.exception("News module failed.")
        result = ModuleResult(
            module="news",
            applicable=True,
            status="failed",
            summary="News module failed during execution.",
            error=str(exc),
            reason="Unexpected news module exception.",
        )
        return result, identifiers