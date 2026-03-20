from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

from app.config import get_settings
from app.llm import get_chat_model, is_llm_available
from app.prompts import WEBSITE_ANALYSIS_SYSTEM_PROMPT, WEBSITE_ANALYSIS_USER_PROMPT
from app.routers import build_skipped_result, route_website
from app.schemas import CompanyIdentifiers, ModuleResult, PlannerOutput, WebsiteInsights, EvidenceCard
from app.tools.base import WebsiteCrawlerAdapter, WebsiteDiscoveryAdapter, WebsitePageRecord
from app.utils.http import build_headers, request_text
from app.utils.logging import get_logger
from app.utils.text import dedupe_items, extract_domain, normalize_name, normalize_whitespace, truncate_text
from langchain_core.prompts import ChatPromptTemplate

logger = get_logger(__name__)

BAD_DOMAINS = {
    "wikipedia.org",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "bloomberg.com",
    "reuters.com",
    "finance.yahoo.com",
}

KEYWORDS = ["about", "company", "investor", "news", "press", "products", "about-us", "ir", "关于", "投资者", "新闻", "产品"]


class DefaultWebsiteDiscoveryAdapter(WebsiteDiscoveryAdapter):
    # 中文注释：优先复用已解析的网站，再尝试证券数据源，最后做公开搜索。
    def discover(self, company_name: str, hints: dict[str, object]) -> str | None:
        existing = hints.get("website_url")
        if isinstance(existing, str) and existing:
            return existing

        ticker = hints.get("ticker")
        market = hints.get("market")
        if ticker and market == "US" and yf is not None:
            try:
                info = yf.Ticker(str(ticker)).get_info()
                website = info.get("website")
                if website:
                    return str(website)
            except Exception:
                logger.debug("Failed to obtain website from yfinance for %s.", ticker)

        query = f"{company_name} official website"
        if any(ord(ch) > 127 for ch in company_name):
            query = f"{company_name} 官网 official website"

        try:
            html = request_text(
                "https://duckduckgo.com/html/",
                params={"q": query},
                headers=build_headers(),
            )
            soup = BeautifulSoup(html, "html.parser")
            anchors = soup.find_all("a", href=True)

            for anchor in anchors:
                href = anchor.get("href", "")
                if not href:
                    continue

                if "duckduckgo.com/l/" in href and "uddg=" in href:
                    parsed = urlparse(href)
                    target = parse_qs(parsed.query).get("uddg", [None])[0]
                    href = target or href

                domain = extract_domain(href)
                if not domain:
                    continue

                if any(domain.endswith(bad) for bad in BAD_DOMAINS):
                    continue

                if href.startswith("http"):
                    return href
        except Exception:
            logger.exception("Website discovery search failed for %s.", company_name)

        return None


class RequestsWebsiteCrawler(WebsiteCrawlerAdapter):
    # 中文注释：只抓首页及少量高价值内链，避免网页噪声无限扩散。
    def crawl(self, base_url: str, *, max_pages: int = 4) -> list[WebsitePageRecord]:
        settings = get_settings()
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc.lower()
        queue: list[str] = [base_url]
        visited: set[str] = set()
        pages: list[WebsitePageRecord] = []

        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                html = request_text(url, headers=build_headers())
            except Exception:
                logger.exception("Website crawl failed for %s.", url)
                continue

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else url
            text = normalize_whitespace(soup.get_text("\n", strip=True))
            if text:
                pages.append(
                    WebsitePageRecord(
                        title=title,
                        url=url,
                        text=text[: settings.website_page_char_limit],
                    )
                )

            for anchor in soup.find_all("a", href=True):
                href = anchor.get("href", "")
                link_text = normalize_whitespace(anchor.get_text(" ", strip=True)).lower()
                if not href:
                    continue

                absolute_url = urljoin(url, href)
                parsed = urlparse(absolute_url)
                if parsed.netloc.lower() != base_domain:
                    continue

                path_or_text = f"{parsed.path.lower()} {link_text}"
                if any(keyword in path_or_text for keyword in KEYWORDS) and absolute_url not in visited:
                    queue.append(absolute_url)

        return dedupe_items(pages, lambda page: page.url)


def _heuristic_website_analysis(company_name: str, pages: list[WebsitePageRecord]) -> WebsiteInsights:
    titles = [page.title for page in pages[:4]]
    snippets = [truncate_text(page.text, 180) for page in pages[:3]]
    key_points = [f"Observed page: {title}" for title in titles]
    if snippets:
        key_points.append(f"Representative website text: {snippets[0]}")
    return WebsiteInsights(
        summary=f"Website summary for {company_name} was generated with heuristic fallback from crawled pages.",
        key_points=key_points[:5],
    )


def _analyze_pages_with_llm(company_name: str, pages: list[WebsitePageRecord]) -> WebsiteInsights:
    if not is_llm_available():
        return _heuristic_website_analysis(company_name, pages)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", WEBSITE_ANALYSIS_SYSTEM_PROMPT),
            ("human", WEBSITE_ANALYSIS_USER_PROMPT),
        ]
    )

    payload_lines: list[str] = []
    for page in pages:
        payload_lines.append(
            f"TITLE: {page.title}\nURL: {page.url}\nTEXT:\n{truncate_text(page.text, 1800)}"
        )

    try:
        llm = get_chat_model(temperature=0.1)
        structured_llm = llm.with_structured_output(WebsiteInsights, method="json_schema")
        result = (prompt | structured_llm).invoke(
            {
                "company_name": company_name,
                "pages_payload": "\n\n---\n\n".join(payload_lines),
            }
        )
        return WebsiteInsights.model_validate(result)
    except Exception:
        logger.exception("Website LLM analysis failed. Falling back to heuristic summary.")
        return _heuristic_website_analysis(company_name, pages)


def run_website_module(
    company_name: str,
    planner_output: PlannerOutput,
    identifiers: CompanyIdentifiers,
    *,
    discovery_adapter: WebsiteDiscoveryAdapter | None = None,
    crawler_adapter: WebsiteCrawlerAdapter | None = None,
) -> tuple[ModuleResult, CompanyIdentifiers]:
    decision = route_website(planner_output)
    if not decision.should_run:
        return build_skipped_result("website", decision.reason), identifiers

    discovery_adapter = discovery_adapter or DefaultWebsiteDiscoveryAdapter()
    crawler_adapter = crawler_adapter or RequestsWebsiteCrawler()
    settings = get_settings()

    try:
        website_url = discovery_adapter.discover(
            company_name,
            {
                "website_url": identifiers.website_url,
                "ticker": identifiers.ticker,
                "market": planner_output.market,
            },
        )

        if not website_url:
            result = ModuleResult(
                module="website",
                applicable=True,
                status="partial",
                summary="Website module could not determine an official website.",
                reason="Official website not found.",
                warning="Official website discovery failed.",
            )
            return result, identifiers

        pages = crawler_adapter.crawl(website_url, max_pages=settings.max_website_pages)
        if not pages:
            result = ModuleResult(
                module="website",
                applicable=True,
                status="partial",
                summary="Website module found a candidate website but could not crawl useful pages.",
                reason="Website crawl returned no usable pages.",
                warning="Website pages were empty or inaccessible.",
            )
            updated_identifiers = identifiers.model_copy(update={"website_url": website_url})
            return result, updated_identifiers

        insights = _analyze_pages_with_llm(company_name, pages)
        evidence = [
            EvidenceCard(
                module="website",
                source_type="official_website",
                title=page.title,
                date=None,
                snippet=truncate_text(page.text, max_chars=320),
                url=page.url,
            )
            for page in pages[: settings.max_website_pages]
        ]

        updated_identifiers = identifiers.model_copy(update={"website_url": website_url})

        result = ModuleResult(
            module="website",
            applicable=True,
            status="success",
            summary=insights.summary,
            key_points=insights.key_points,
            evidence=evidence,
            metrics={"pages_crawled": len(pages)},
        )
        return result, updated_identifiers
    except Exception as exc:
        logger.exception("Website module failed.")
        result = ModuleResult(
            module="website",
            applicable=True,
            status="failed",
            summary="Website module failed during execution.",
            error=str(exc),
            reason="Unexpected website module exception.",
        )
        return result, identifiers
