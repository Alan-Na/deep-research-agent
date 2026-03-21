from __future__ import annotations

from app.filing.context_builder import analyze_filings
from app.schemas import EvidenceCard, FilingInsights
from app.tools.base import FilingDocumentRecord
from app.utils.logging import get_logger

logger = get_logger(__name__)


def extract_filing_insights(
    company_name: str,
    filings: list[FilingDocumentRecord],
) -> tuple[FilingInsights, list[EvidenceCard]]:
    """Compatibility shim for the old filing RAG entrypoint.

    The filing pipeline is now structure-first: parser -> section tagging ->
    structured extraction -> evidence binding. This function keeps the old
    public contract so existing imports do not break.
    """
    try:
        bundle = analyze_filings(company_name, None, filings)
        return bundle.insights, bundle.evidence_cards
    except Exception:
        logger.exception("Structured filing analysis failed inside compatibility shim.")
        fallback = FilingInsights(
            summary=f"Structured filing analysis for {company_name} failed and returned a conservative fallback.",
            operating_performance="Structured filing extraction failed before operating performance could be derived.",
            risk_factors=["Structured filing extraction failed before risk evidence could be derived."],
            management_commentary="Structured filing extraction failed before management commentary could be derived.",
            guidance_changes="Structured filing extraction failed before guidance/outlook could be derived.",
        )
        return fallback, []
