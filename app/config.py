from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv(override=False)


@dataclass(frozen=True)
class Settings:
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "deep-research-agent/0.2 research@example.com",
    )

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/deep_research_agent",
    )
    reset_database_on_startup: bool = os.getenv("RESET_DATABASE_ON_STARTUP", "false").lower() in {"1", "true", "yes"}
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_queue_name: str = os.getenv("REDIS_QUEUE_NAME", "investment_jobs")
    event_channel_prefix: str = os.getenv("EVENT_CHANNEL_PREFIX", "investment_job_events")

    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
    agent_max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "4"))
    agent_timeout_seconds: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "45"))
    price_lookback_days: int = int(os.getenv("PRICE_LOOKBACK_DAYS", "90"))
    news_days: int = int(os.getenv("NEWS_DAYS", "14"))
    max_news_articles: int = int(os.getenv("MAX_NEWS_ARTICLES", "20"))
    max_website_pages: int = int(os.getenv("MAX_WEBSITE_PAGES", "4"))
    website_page_char_limit: int = int(os.getenv("WEBSITE_PAGE_CHAR_LIMIT", "6000"))
    rag_chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "1200"))
    rag_chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
    filing_max_documents: int = int(os.getenv("FILING_MAX_DOCUMENTS", "4"))
    filing_evidence_limit: int = int(os.getenv("FILING_EVIDENCE_LIMIT", "8"))
    recent_days_threshold: int = int(os.getenv("RECENT_DAYS_THRESHOLD", "120"))
    minimum_evidence_cards: int = int(os.getenv("MINIMUM_EVIDENCE_CARDS", "4"))
    final_evidence_limit: int = int(os.getenv("FINAL_EVIDENCE_LIMIT", "12"))
    retrieval_top_k: int = int(os.getenv("RETRIEVAL_TOP_K", "8"))
    blocking_analyze_timeout_seconds: int = int(os.getenv("BLOCKING_ANALYZE_TIMEOUT_SECONDS", "90"))
    worker_poll_timeout_seconds: int = int(os.getenv("WORKER_POLL_TIMEOUT_SECONDS", "5"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
