from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.filing.extract import extract_structured_facts
from app.filing.models import PERIODIC_FORMS, ParsedFiling
from app.filing.parser import parse_filing_html
from app.schemas import EvidenceCard, FilingInsights, ModuleResult, StructuredFilingFacts
from app.tools.base import FilingDocumentRecord


@dataclass
class FilingAnalysisBundle:
    facts: StructuredFilingFacts
    insights: FilingInsights
    evidence_cards: list[EvidenceCard]
    key_points: list[str]
    supporting_filing_count: int
    sparse: bool = False


def analyze_filings(
    company_name: str,
    ticker: str | None,
    filings: list[FilingDocumentRecord],
) -> FilingAnalysisBundle:
    parsed_filings = [parse_filing_html(filing) for filing in filings]
    primary_filing, supporting_filings = _select_primary_and_supporting_filings(parsed_filings)
    facts = extract_structured_facts(company_name, ticker, primary_filing, supporting_filings)
    insights = _build_filing_insights(company_name, facts)
    evidence_cards = _build_evidence_cards(facts)
    key_points = _build_key_points(facts)
    sparse = not any(
        [
            facts.revenue,
            facts.operating_income,
            facts.net_income,
            facts.eps,
            facts.operating_cash_flow,
            facts.guidance,
            facts.key_risks,
        ]
    )
    return FilingAnalysisBundle(
        facts=facts,
        insights=insights,
        evidence_cards=evidence_cards,
        key_points=key_points,
        supporting_filing_count=len(supporting_filings),
        sparse=sparse,
    )


def build_filing_module_result(bundle: FilingAnalysisBundle) -> ModuleResult:
    rag_answers = {
        "operating_performance": bundle.insights.operating_performance,
        "risk_factors": bundle.insights.risk_factors,
        "management_commentary": bundle.insights.management_commentary,
        "guidance_changes": bundle.insights.guidance_changes,
    }
    status = "partial" if bundle.sparse else "success"
    warning = "Structured filing extraction found only limited signal." if bundle.sparse else None
    return ModuleResult(
        module="filing",
        applicable=True,
        status=status,
        summary=bundle.insights.summary,
        metrics={
            "filing_type": bundle.facts.filing_type,
            "filed_at": bundle.facts.filed_at,
            "fiscal_period": bundle.facts.fiscal_period,
            "structured_facts": bundle.facts.model_dump(),
            "supporting_filing_count": bundle.supporting_filing_count,
        },
        rag_answers=rag_answers,
        key_points=bundle.key_points,
        evidence=bundle.evidence_cards,
        warning=warning,
    )


def _select_primary_and_supporting_filings(parsed_filings: list[ParsedFiling]) -> tuple[ParsedFiling, list[ParsedFiling]]:
    if not parsed_filings:
        raise ValueError("No parsed filings were available.")

    primary = max(
        parsed_filings,
        key=lambda filing: (1 if filing.filing_type in PERIODIC_FORMS else 0, filing.filed_at),
    )

    supporting: list[ParsedFiling] = []
    for filing in sorted(parsed_filings, key=lambda item: item.filed_at, reverse=True):
        if filing is primary:
            continue
        if filing.filing_type in PERIODIC_FORMS and primary.filing_type in PERIODIC_FORMS:
            continue
        supporting.append(filing)

    max_documents = max(get_settings().filing_max_documents - 1, 0)
    return primary, supporting[:max_documents]


def _build_filing_insights(company_name: str, facts: StructuredFilingFacts) -> FilingInsights:
    operating_bits = []
    if facts.revenue:
        operating_bits.append(f"revenue {facts.revenue}")
    if facts.revenue_yoy:
        operating_bits.append(f"revenue YoY {facts.revenue_yoy}")
    if facts.gross_margin:
        operating_bits.append(f"gross margin {facts.gross_margin}")
    if facts.operating_income:
        operating_bits.append(f"operating income {facts.operating_income}")
    if facts.net_income:
        operating_bits.append(f"net income {facts.net_income}")
    if facts.eps:
        operating_bits.append(f"EPS {facts.eps}")

    operating_performance = "; ".join(operating_bits[:5]) or "Recent filing evidence is thin for operating performance."
    management_commentary = facts.management_explanation[0] if facts.management_explanation else "Management explanation was sparse in the extracted filing sections."
    guidance_changes = facts.guidance[0] if facts.guidance else "No clear guidance or outlook statement was extracted from the analyzed filings."
    summary = _build_summary(company_name, facts)

    return FilingInsights(
        summary=summary,
        operating_performance=operating_performance,
        risk_factors=facts.key_risks[:4],
        management_commentary=management_commentary,
        guidance_changes=guidance_changes,
    )


def _build_summary(company_name: str, facts: StructuredFilingFacts) -> str:
    opening = f"Structured filing review for {company_name} focused on the latest {facts.filing_type} filed on {facts.filed_at}."
    period_text = f" Fiscal period: {facts.fiscal_period}." if facts.fiscal_period else ""
    facts_bits = []
    if facts.revenue:
        facts_bits.append(f"Revenue was {facts.revenue}")
    if facts.revenue_yoy:
        facts_bits.append(f"revenue change was {facts.revenue_yoy} year over year")
    if facts.net_income:
        facts_bits.append(f"net income was {facts.net_income}")
    if facts.eps:
        facts_bits.append(f"EPS was {facts.eps}")
    if facts.operating_cash_flow:
        facts_bits.append(f"operating cash flow was {facts.operating_cash_flow}")
    if facts.guidance:
        facts_bits.append(f"guidance/outlook highlight: {facts.guidance[0]}")
    if facts.key_risks:
        facts_bits.append(f"key risk: {facts.key_risks[0]}")
    body = " ".join(facts_bits[:4]) if facts_bits else "The extracted filing signal was limited, so conclusions should stay conservative."
    return f"{opening}{period_text} {body}".strip()


def _build_key_points(facts: StructuredFilingFacts) -> list[str]:
    key_points: list[str] = []
    if facts.revenue:
        point = f"{facts.filing_type} revenue: {facts.revenue}"
        if facts.revenue_yoy:
            point += f" ({facts.revenue_yoy} YoY)"
        key_points.append(point)
    if facts.gross_margin:
        key_points.append(f"Gross margin: {facts.gross_margin}")
    if facts.operating_income:
        key_points.append(f"Operating income: {facts.operating_income}")
    if facts.net_income:
        key_points.append(f"Net income: {facts.net_income}")
    if facts.eps:
        key_points.append(f"EPS: {facts.eps}")
    if facts.operating_cash_flow:
        key_points.append(f"Operating cash flow: {facts.operating_cash_flow}")
    if facts.free_cash_flow:
        key_points.append(f"Free cash flow: {facts.free_cash_flow}")
    if facts.guidance:
        key_points.append(f"Guidance/outlook: {facts.guidance[0]}")
    if facts.unusual_items:
        key_points.append(f"Unusual item: {facts.unusual_items[0]}")
    return key_points[:8]


def _build_evidence_cards(facts: StructuredFilingFacts) -> list[EvidenceCard]:
    cards: list[EvidenceCard] = []
    for ref in facts.evidence_references[: get_settings().filing_evidence_limit]:
        title_prefix = f"{ref.filing_type} {ref.heading}".strip()
        cards.append(
            EvidenceCard(
                module="filing",
                source_type="sec_filing",
                title=title_prefix or f"SEC filing evidence: {ref.topic}",
                date=ref.filed_at,
                snippet=ref.snippet,
                url=ref.url,
            )
        )
    return cards
