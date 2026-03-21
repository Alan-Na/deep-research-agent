from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from app.config import get_settings
from app.filing.context_builder import analyze_filings, build_filing_module_result
from app.filing.models import PERIODIC_FORMS, SUPPLEMENTAL_FORMS, SUPPORTED_FORMS
from app.routers import build_skipped_result, route_filing
from app.schemas import CompanyIdentifiers, ModuleResult, PlannerOutput
from app.tools.base import FilingDataAdapter, FilingDocumentRecord
from app.utils.http import build_headers, request_json, request_text
from app.utils.logging import get_logger
from app.utils.text import normalize_name, normalize_whitespace

logger = get_logger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


class SecEdgarAdapter(FilingDataAdapter):
    # 中文注释：先从 SEC 的公司索引解析实体，再拉取最近申报。
    def resolve_entity(self, company_name: str, ticker: str | None = None) -> dict[str, Any] | None:
        payload = request_json(SEC_TICKERS_URL, headers=build_headers())
        values = payload.values() if isinstance(payload, dict) else payload
        target_name = normalize_name(company_name)
        target_ticker = normalize_name(ticker or "")

        exact_candidates: list[dict[str, Any]] = []
        partial_candidates: list[dict[str, Any]] = []

        for item in values:
            title = str(item.get("title", ""))
            item_ticker = str(item.get("ticker", ""))
            normalized_title = normalize_name(title)
            normalized_ticker = normalize_name(item_ticker)

            if target_ticker and normalized_ticker == target_ticker:
                exact_candidates.append(item)
                continue

            if normalized_title == target_name:
                exact_candidates.append(item)
                continue

            if target_name and target_name in normalized_title:
                partial_candidates.append(item)

        selected = exact_candidates[0] if exact_candidates else (partial_candidates[0] if partial_candidates else None)
        if not selected:
            return None

        cik = str(selected.get("cik_str", "")).zfill(10)
        return {
            "cik": cik,
            "ticker": selected.get("ticker"),
            "title": selected.get("title"),
        }

    def _resolve_entity(self, company_name: str, ticker: str | None = None) -> dict[str, Any] | None:
        # 向后兼容旧调用路径。
        return self.resolve_entity(company_name, ticker=ticker)

    def _build_filing_url(self, cik: str, accession_number: str, primary_document: str) -> str:
        accession_without_dashes = accession_number.replace("-", "")
        cik_no_padding = str(int(cik))
        return f"{SEC_ARCHIVES_BASE}/{cik_no_padding}/{accession_without_dashes}/{primary_document}"

    def _html_to_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        lines = [normalize_whitespace(line) for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def fetch_recent_filings(
        self,
        company_name: str,
        *,
        ticker: str | None = None,
        limit: int = 3,
    ) -> list[FilingDocumentRecord]:
        entity = self.resolve_entity(company_name, ticker=ticker)
        if entity is None:
            return []

        submissions = request_json(
            SEC_SUBMISSIONS_URL.format(cik=entity["cik"]),
            headers=build_headers(),
        )

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        candidates: list[dict[str, str]] = []
        for form, filed_at, accession_number, primary_document in zip(
            forms,
            filing_dates,
            accession_numbers,
            primary_documents,
        ):
            if form not in SUPPORTED_FORMS:
                continue
            candidates.append(
                {
                    "form": form,
                    "filed_at": filed_at,
                    "accession_number": accession_number,
                    "primary_document": primary_document,
                }
            )

        def candidate_priority(item: dict[str, str]) -> tuple[int, str]:
            form = item["form"]
            if form in PERIODIC_FORMS:
                return (2, item["filed_at"])
            if form in SUPPLEMENTAL_FORMS:
                return (1, item["filed_at"])
            return (0, item["filed_at"])

        periodic_candidates = sorted(
            [item for item in candidates if item["form"] in PERIODIC_FORMS],
            key=lambda item: item["filed_at"],
            reverse=True,
        )
        supplemental_candidates = sorted(
            [item for item in candidates if item["form"] in SUPPLEMENTAL_FORMS],
            key=lambda item: item["filed_at"],
            reverse=True,
        )
        periodic_limit = min(max(limit - 1, 1), len(periodic_candidates)) if periodic_candidates else 0
        supplemental_limit = min(limit - periodic_limit, len(supplemental_candidates)) if supplemental_candidates else 0
        selected_candidates = periodic_candidates[:periodic_limit] + supplemental_candidates[:supplemental_limit]
        if len(selected_candidates) < limit:
            selected_keys = {(item["form"], item["filed_at"], item["accession_number"]) for item in selected_candidates}
            leftovers = [
                item
                for item in sorted(candidates, key=candidate_priority, reverse=True)
                if (item["form"], item["filed_at"], item["accession_number"]) not in selected_keys
            ]
            selected_candidates.extend(leftovers[: limit - len(selected_candidates)])

        documents: list[FilingDocumentRecord] = []
        for item in selected_candidates:
            filing_url = self._build_filing_url(entity["cik"], item["accession_number"], item["primary_document"])
            try:
                filing_html = request_text(filing_url, headers=build_headers())
                filing_text = self._html_to_text(filing_html)
            except Exception:
                logger.exception("Failed to download filing %s.", filing_url)
                continue

            if len(normalize_whitespace(filing_text)) < 500:
                continue

            documents.append(
                FilingDocumentRecord(
                    form=item["form"],
                    filed_at=item["filed_at"],
                    title=f"{entity['title']} {item['form']} filed on {item['filed_at']}",
                    url=filing_url,
                    text=filing_text,
                    raw_html=filing_html,
                )
            )

            if len(documents) >= limit:
                break

        return documents


def run_filing_module(
    company_name: str,
    planner_output: PlannerOutput,
    identifiers: CompanyIdentifiers,
    *,
    adapter: FilingDataAdapter | None = None,
) -> tuple[ModuleResult, CompanyIdentifiers]:
    decision = route_filing(planner_output)
    if not decision.should_run:
        return build_skipped_result("filing", decision.reason), identifiers

    adapter = adapter or SecEdgarAdapter()
    settings = get_settings()

    try:
        filings = adapter.fetch_recent_filings(
            company_name,
            ticker=identifiers.ticker,
            limit=settings.filing_max_documents,
        )

        if not filings:
            result = ModuleResult(
                module="filing",
                applicable=True,
                status="partial",
                summary="Filing module ran but no recent SEC filings were available.",
                reason="No recent SEC filings found.",
                warning="SEC filings were not found or could not be downloaded.",
            )
            return result, identifiers

        bundle = analyze_filings(company_name, identifiers.ticker, filings)
        result = build_filing_module_result(bundle)

        resolved_entity = None
        if hasattr(adapter, "resolve_entity"):
            try:
                resolved_entity = getattr(adapter, "resolve_entity")(company_name, ticker=identifiers.ticker)
            except Exception:
                logger.debug("Failed to refresh SEC entity metadata after filing retrieval.")
        elif hasattr(adapter, "_resolve_entity"):
            try:
                resolved_entity = getattr(adapter, "_resolve_entity")(company_name, ticker=identifiers.ticker)
            except Exception:
                logger.debug("Failed to refresh SEC entity metadata after filing retrieval.")

        updated_identifiers = identifiers.model_copy(
            update={
                "cik": identifiers.cik or (resolved_entity or {}).get("cik"),
                "ticker": identifiers.ticker or (resolved_entity or {}).get("ticker"),
            }
        )
        structured_facts = result.metrics.get("structured_facts") if result.metrics else None
        if isinstance(structured_facts, dict) and not structured_facts.get("ticker"):
            structured_facts["ticker"] = updated_identifiers.ticker
        return result, updated_identifiers
    except Exception as exc:
        logger.exception("Filing module failed.")
        result = ModuleResult(
            module="filing",
            applicable=True,
            status="failed",
            summary="Filing module failed during execution.",
            error=str(exc),
            reason="Unexpected filing module exception.",
        )
        return result, identifiers
