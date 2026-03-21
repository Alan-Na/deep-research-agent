from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ResolvedInstrument:
    symbol: str
    display_name: str
    market: str
    website_url: str | None = None
    exchange: str | None = None


@dataclass
class FilingDocumentRecord:
    form: str
    filed_at: str
    title: str
    url: str
    text: str
    raw_html: str | None = None


@dataclass
class WebsitePageRecord:
    title: str
    url: str
    text: str


@dataclass
class NewsArticleRecord:
    title: str
    source: str
    published_at: str
    url: str
    description: str = ""
    content: str = ""


class PriceDataAdapter(ABC):
    @abstractmethod
    def resolve(self, company_name: str) -> ResolvedInstrument | None:
        raise NotImplementedError

    @abstractmethod
    def fetch_recent_history(self, instrument: ResolvedInstrument, lookback_days: int) -> Any:
        raise NotImplementedError


class FilingDataAdapter(ABC):
    @abstractmethod
    def fetch_recent_filings(
        self,
        company_name: str,
        *,
        ticker: str | None = None,
        limit: int = 3,
    ) -> list[FilingDocumentRecord]:
        raise NotImplementedError


class WebsiteDiscoveryAdapter(ABC):
    @abstractmethod
    def discover(self, company_name: str, hints: dict[str, Any]) -> str | None:
        raise NotImplementedError


class WebsiteCrawlerAdapter(ABC):
    @abstractmethod
    def crawl(self, base_url: str, *, max_pages: int = 4) -> list[WebsitePageRecord]:
        raise NotImplementedError


class NewsDataAdapter(ABC):
    @abstractmethod
    def fetch(self, company_name: str, *, from_date: str, page_size: int = 20) -> list[NewsArticleRecord]:
        raise NotImplementedError
