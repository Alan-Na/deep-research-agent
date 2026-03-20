from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# 中文注释：加载本地环境变量，便于开发调试。
load_dotenv(override=False)


@dataclass(frozen=True)
class Settings:
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "deep-research-agent/0.1 research@example.com",
    )
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
    price_lookback_days: int = int(os.getenv("PRICE_LOOKBACK_DAYS", "90"))
    news_days: int = int(os.getenv("NEWS_DAYS", "90"))
    max_news_articles: int = int(os.getenv("MAX_NEWS_ARTICLES", "20"))
    max_website_pages: int = int(os.getenv("MAX_WEBSITE_PAGES", "4"))
    website_page_char_limit: int = int(os.getenv("WEBSITE_PAGE_CHAR_LIMIT", "6000"))
    rag_chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "1200"))
    rag_chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
    recent_days_threshold: int = int(os.getenv("RECENT_DAYS_THRESHOLD", "120"))
    minimum_evidence_cards: int = int(os.getenv("MINIMUM_EVIDENCE_CARDS", "4"))
    final_evidence_limit: int = int(os.getenv("FINAL_EVIDENCE_LIMIT", "12"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 中文注释：通过缓存保证全局只初始化一次配置。
    return Settings()
