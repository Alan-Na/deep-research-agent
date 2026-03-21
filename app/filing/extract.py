from __future__ import annotations

import re

from app.filing.models import PERIODIC_FORMS, ParsedFiling
from app.filing.retrieval import retrieve_section_matches
from app.schemas import FilingEvidenceReference, StructuredFilingFacts
from app.utils.text import normalize_name, truncate_text

MONEY_RE = re.compile(r"(?:US\$|\$)\s?-?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|bn|b|m)?", re.IGNORECASE)
PERCENT_RE = re.compile(r"-?\d+(?:\.\d+)?\s*%")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
EPS_VALUE_RE = re.compile(
    r"(?:earnings per share|eps|diluted earnings per share|basic earnings per share)[^\d$-]{0,20}(?:was|were|of)?\s*(\$?-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
EPS_TRAILING_RE = re.compile(r"(\$?-?\d+(?:\.\d+)?)\s*(?:per share)", re.IGNORECASE)

PERIODIC_SECTION_TYPES = {"mdna", "results_of_operations", "liquidity", "financial_statements", "segment_performance", "overview"}
SUPPLEMENTAL_SECTION_TYPES = {"earnings_release", "guidance", "overview"}

UNUSUAL_ITEM_KEYWORDS = [
    "restructuring",
    "impairment",
    "one time",
    "one-time",
    "non recurring",
    "non-recurring",
    "acquisition related",
    "charge",
    "write down",
    "write-off",
    "litigation",
    "settlement",
]

MANAGEMENT_EXPLANATION_KEYWORDS = [
    "due to",
    "driven by",
    "reflecting",
    "primarily",
    "mainly",
    "resulting from",
    "because of",
    "as a result",
]

GUIDANCE_KEYWORDS = [
    "guidance",
    "outlook",
    "expect",
    "expects",
    "forecast",
    "reaffirm",
    "raised",
    "lowered",
    "anticipate",
]

RISK_KEYWORDS = [
    "risk",
    "uncertainty",
    "headwind",
    "competition",
    "regulatory",
    "macro",
    "supply chain",
    "litigation",
]


def extract_structured_facts(
    company_name: str,
    ticker: str | None,
    primary_filing: ParsedFiling,
    supporting_filings: list[ParsedFiling] | None = None,
) -> StructuredFilingFacts:
    supporting_filings = supporting_filings or []
    primary_sections = list(primary_filing.sections)
    supporting_sections = [section for filing in supporting_filings for section in filing.sections]
    all_sections = primary_sections + supporting_sections
    primary_metric_section_types = (
        PERIODIC_SECTION_TYPES if primary_filing.filing_type in PERIODIC_FORMS else PERIODIC_SECTION_TYPES | SUPPLEMENTAL_SECTION_TYPES
    )

    evidence_references: list[FilingEvidenceReference] = []

    revenue, refs = _extract_money_field(
        topic="revenue",
        sections=primary_sections,
        section_types=primary_metric_section_types,
        keywords=["revenue", "net sales", "sales"],
    )
    evidence_references.extend(refs)

    revenue_yoy, refs = _extract_percent_field(
        topic="revenue_yoy",
        sections=primary_sections,
        section_types=primary_metric_section_types,
        keywords=["revenue", "year over year", "from the prior year", "from a year ago", "compared with the same period"],
        required_terms=["year over year", "from the prior year", "from a year ago", "same period"],
    )
    evidence_references.extend(refs)

    revenue_qoq, refs = _extract_percent_field(
        topic="revenue_qoq",
        sections=primary_sections,
        section_types=primary_metric_section_types,
        keywords=["revenue", "sequential", "quarter over quarter", "qoq", "compared with the prior quarter"],
        required_terms=["sequential", "quarter over quarter", "qoq", "prior quarter"],
    )
    evidence_references.extend(refs)

    gross_margin, refs = _extract_percent_field(
        topic="gross_margin",
        sections=primary_sections,
        section_types=primary_metric_section_types,
        keywords=["gross margin", "gross profit margin"],
    )
    evidence_references.extend(refs)

    operating_income, refs = _extract_money_field(
        topic="operating_income",
        sections=primary_sections,
        section_types=primary_metric_section_types,
        keywords=["operating income", "income from operations"],
    )
    evidence_references.extend(refs)

    net_income, refs = _extract_money_field(
        topic="net_income",
        sections=primary_sections,
        section_types=primary_metric_section_types,
        keywords=["net income", "net earnings", "net loss"],
    )
    evidence_references.extend(refs)

    eps, refs = _extract_eps_field(
        topic="eps",
        sections=primary_sections + supporting_sections,
        section_types=PERIODIC_SECTION_TYPES | SUPPLEMENTAL_SECTION_TYPES,
        keywords=["earnings per share", "eps", "diluted earnings per share", "diluted eps", "basic earnings per share"],
    )
    evidence_references.extend(refs)

    operating_cash_flow, refs = _extract_money_field(
        topic="operating_cash_flow",
        sections=primary_sections,
        section_types={"liquidity", "financial_statements", "mdna", "earnings_release", "overview"},
        keywords=["operating cash flow", "cash provided by operating activities", "net cash provided by operating activities"],
    )
    evidence_references.extend(refs)

    free_cash_flow, refs = _extract_money_field(
        topic="free_cash_flow",
        sections=all_sections,
        section_types={"liquidity", "mdna", "earnings_release", "guidance", "overview"},
        keywords=["free cash flow"],
    )
    evidence_references.extend(refs)

    capex, refs = _extract_money_field(
        topic="capex",
        sections=all_sections,
        section_types={"liquidity", "mdna", "guidance", "earnings_release", "overview"},
        keywords=["capital expenditures", "capital expenditure", "capex"],
    )
    evidence_references.extend(refs)

    guidance, refs = _collect_topic_sentences(
        topic="guidance",
        sections=all_sections,
        section_types={"guidance", "earnings_release", "mdna", "overview"},
        keywords=GUIDANCE_KEYWORDS,
        limit=3,
        required_terms=GUIDANCE_KEYWORDS,
    )
    evidence_references.extend(refs)

    segment_performance, refs = _collect_topic_sentences(
        topic="segment_performance",
        sections=all_sections,
        section_types={"segment_performance", "results_of_operations", "mdna", "earnings_release"},
        keywords=["segment", "segments", "business unit"],
        limit=4,
        require_number=True,
        required_terms=["segment", "segments", "business unit"],
    )
    evidence_references.extend(refs)

    management_explanation, refs = _collect_topic_sentences(
        topic="management_explanation",
        sections=primary_sections,
        section_types={"mdna", "results_of_operations", "liquidity", "overview"},
        keywords=MANAGEMENT_EXPLANATION_KEYWORDS,
        limit=4,
        required_terms=MANAGEMENT_EXPLANATION_KEYWORDS,
    )
    evidence_references.extend(refs)

    key_risks, refs = _collect_topic_sentences(
        topic="key_risks",
        sections=primary_sections,
        section_types={"risk_factors"},
        keywords=RISK_KEYWORDS,
        limit=5,
        required_terms=RISK_KEYWORDS,
    )
    evidence_references.extend(refs)

    unusual_items, refs = _collect_topic_sentences(
        topic="unusual_items",
        sections=all_sections,
        section_types={"mdna", "results_of_operations", "earnings_release", "financial_statements", "segment_performance", "guidance", "overview"},
        keywords=UNUSUAL_ITEM_KEYWORDS,
        limit=4,
        required_terms=UNUSUAL_ITEM_KEYWORDS,
    )
    evidence_references.extend(refs)

    return StructuredFilingFacts(
        company=company_name,
        ticker=ticker,
        filing_type=primary_filing.filing_type,
        fiscal_period=primary_filing.fiscal_period,
        filed_at=primary_filing.filed_at,
        revenue=revenue,
        revenue_yoy=revenue_yoy,
        revenue_qoq=revenue_qoq,
        gross_margin=gross_margin,
        operating_income=operating_income,
        net_income=net_income,
        eps=eps,
        operating_cash_flow=operating_cash_flow,
        free_cash_flow=free_cash_flow,
        capex=capex,
        guidance=guidance,
        segment_performance=segment_performance,
        management_explanation=management_explanation,
        key_risks=key_risks,
        unusual_items=unusual_items,
        evidence_references=_dedupe_evidence_references(evidence_references),
        supporting_filings=[
            {
                "filing_type": filing.filing_type,
                "filed_at": filing.filed_at,
                "fiscal_period": filing.fiscal_period,
                "title": filing.title,
                "url": filing.url,
            }
            for filing in supporting_filings
        ],
    )


def _extract_money_field(
    *,
    topic: str,
    sections,
    section_types: set[str],
    keywords: list[str],
) -> tuple[str | None, list[FilingEvidenceReference]]:
    matches = retrieve_section_matches(
        list(sections),
        keywords=keywords,
        section_types=section_types,
        limit=3,
    )
    for match in matches:
        value = _extract_money(match.snippet)
        if value:
            return value, [_build_reference(topic, match)]
    if matches:
        return truncate_text(matches[0].snippet, max_chars=180), [_build_reference(topic, matches[0])]
    return None, []


def _extract_percent_field(
    *,
    topic: str,
    sections,
    section_types: set[str],
    keywords: list[str],
    required_terms: list[str] | None = None,
) -> tuple[str | None, list[FilingEvidenceReference]]:
    matches = retrieve_section_matches(
        list(sections),
        keywords=keywords,
        section_types=section_types,
        limit=3,
    )
    for match in matches:
        if required_terms and not _contains_any_term(match.snippet, required_terms):
            continue
        value = _extract_percent(match.snippet)
        if value:
            return value, [_build_reference(topic, match)]
    return None, []


def _extract_eps_field(
    *,
    topic: str,
    sections,
    section_types: set[str],
    keywords: list[str],
) -> tuple[str | None, list[FilingEvidenceReference]]:
    matches = retrieve_section_matches(
        list(sections),
        keywords=keywords,
        section_types=section_types,
        limit=3,
    )
    for match in matches:
        value = _extract_eps(match.snippet)
        if value:
            return value, [_build_reference(topic, match)]
    return None, []


def _collect_topic_sentences(
    *,
    topic: str,
    sections,
    section_types: set[str],
    keywords: list[str],
    limit: int,
    require_number: bool = False,
    required_terms: list[str] | None = None,
) -> tuple[list[str], list[FilingEvidenceReference]]:
    matches = retrieve_section_matches(
        list(sections),
        keywords=keywords,
        section_types=section_types,
        limit=max(limit * 2, 4),
    )
    items: list[str] = []
    refs: list[FilingEvidenceReference] = []
    seen: set[str] = set()
    for match in matches:
        snippet = truncate_text(match.snippet, max_chars=260)
        key = normalize_name(snippet)
        if key in seen:
            continue
        if require_number and not (_extract_money(snippet) or _extract_percent(snippet)):
            continue
        if required_terms and not _contains_any_term(snippet, required_terms):
            continue
        seen.add(key)
        items.append(snippet)
        refs.append(_build_reference(topic, match))
        if len(items) >= limit:
            break
    return items, refs


def _extract_money(text: str) -> str | None:
    match = MONEY_RE.search(text or "")
    if not match:
        return None
    return normalize_whitespace_keep_case(match.group(0))


def _extract_percent(text: str) -> str | None:
    match = PERCENT_RE.search(text or "")
    if not match:
        return None
    return normalize_whitespace_keep_case(match.group(0))


def _extract_eps(text: str) -> str | None:
    match = EPS_VALUE_RE.search(text or "")
    if match:
        return normalize_whitespace_keep_case(match.group(1))
    trailing_match = EPS_TRAILING_RE.search(text or "")
    if trailing_match:
        return normalize_whitespace_keep_case(trailing_match.group(1))
    numbers = NUMBER_RE.findall(text or "")
    if not numbers:
        return None
    return numbers[0]


def _build_reference(topic: str, match) -> FilingEvidenceReference:
    return FilingEvidenceReference(
        topic=topic,
        filing_type=match.section.filing_type,
        filed_at=match.section.filed_at,
        fiscal_period=match.section.fiscal_period,
        section_type=match.section.section_type,
        heading=match.section.heading,
        snippet=truncate_text(match.snippet, max_chars=320),
        url=match.section.url,
        title=match.section.title,
    )


def _dedupe_evidence_references(refs: list[FilingEvidenceReference]) -> list[FilingEvidenceReference]:
    output: list[FilingEvidenceReference] = []
    seen: set[str] = set()
    for ref in refs:
        key = f"{ref.topic}|{ref.url}|{normalize_name(ref.snippet)}"
        if key in seen:
            continue
        seen.add(key)
        output.append(ref)
    return output


def _contains_any_term(text: str, terms: list[str]) -> bool:
    normalized_text = normalize_name(text)
    return any(normalize_name(term) in normalized_text for term in terms)


def normalize_whitespace_keep_case(text: str) -> str:
    return " ".join((text or "").split()).strip()
