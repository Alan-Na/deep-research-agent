from __future__ import annotations

from typing import Any, Dict, List, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

ModuleName = Literal["price", "filing", "website", "news"]
MarketName = Literal["A_SHARE", "US", "NONE", "UNKNOWN"]
SentimentName = Literal["positive", "neutral", "negative"]
ModuleStatus = Literal["success", "partial", "skipped", "failed"]


class EvidenceCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: ModuleName
    source_type: str
    title: str
    date: str | None = None
    snippet: str
    url: str | None = None


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str | None = None
    title: str
    sentiment: SentimentName
    summary: str
    url: str | None = None


class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str
    is_public: bool | Literal["unknown"]
    market: MarketName
    selected_modules: List[ModuleName]
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class FilingEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    filing_type: str
    filed_at: str
    fiscal_period: str | None = None
    section_type: str
    heading: str
    snippet: str
    url: str | None = None
    title: str | None = None


class StructuredFilingFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    ticker: str | None = None
    filing_type: str
    fiscal_period: str | None = None
    filed_at: str
    revenue: str | None = None
    revenue_yoy: str | None = None
    revenue_qoq: str | None = None
    gross_margin: str | None = None
    operating_income: str | None = None
    net_income: str | None = None
    eps: str | None = None
    operating_cash_flow: str | None = None
    free_cash_flow: str | None = None
    capex: str | None = None
    guidance: List[str] = Field(default_factory=list)
    segment_performance: List[str] = Field(default_factory=list)
    management_explanation: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    unusual_items: List[str] = Field(default_factory=list)
    evidence_references: List[FilingEvidenceReference] = Field(default_factory=list)
    supporting_filings: List[Dict[str, str | None]] = Field(default_factory=list)


class FilingInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    operating_performance: str
    risk_factors: List[str] = Field(default_factory=list)
    management_commentary: str
    guidance_changes: str


class WebsiteInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    key_points: List[str] = Field(default_factory=list)


class NewsInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    positive_events: List[str] = Field(default_factory=list)
    neutral_events: List[str] = Field(default_factory=list)
    negative_events: List[str] = Field(default_factory=list)
    dominant_narrative: str
    event_timeline: List[TimelineEvent] = Field(default_factory=list)


class CompanyIdentifiers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str | None = None
    cik: str | None = None
    website_url: str | None = None
    exchange: str | None = None
    notes: List[str] = Field(default_factory=list)


class ModuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: ModuleName
    applicable: bool
    summary: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    rag_answers: Dict[str, Any] = Field(default_factory=dict)
    key_points: List[str] = Field(default_factory=list)
    event_timeline: List[TimelineEvent] = Field(default_factory=list)
    evidence: List[EvidenceCard] = Field(default_factory=list)
    status: ModuleStatus = "success"
    reason: str | None = None
    warning: str | None = None
    error: str | None = None


class CoverageCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_module_count: int
    evidence_count: int
    has_recent_evidence: bool
    enough_evidence: bool
    failed_or_skipped_modules: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class FinalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str
    overall_sentiment: SentimentName
    summary: str
    key_findings: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    module_results: Dict[str, ModuleResult] = Field(default_factory=dict)
    evidence: List[EvidenceCard] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1)


class ResearchState(TypedDict, total=False):
    company_name: str
    planner_output: PlannerOutput
    identifiers: CompanyIdentifiers
    module_results: Dict[str, ModuleResult]
    evidence_cards: List[EvidenceCard]
    coverage_check: CoverageCheck
    warnings: List[str]
    errors: List[str]
    final_report: FinalReport
