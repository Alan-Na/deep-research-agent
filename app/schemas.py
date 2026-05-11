from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

MarketName = Literal["A_SHARE", "US", "UNKNOWN"]
SentimentName = Literal["positive", "neutral", "negative"]
AgentStatus = Literal["success", "partial", "skipped", "failed"]
JobStatus = Literal["queued", "running", "partial", "succeeded", "failed"]
StanceName = Literal["bullish", "neutral", "bearish"]
EventCategory = Literal[
    "earnings",
    "product_release",
    "regulation",
    "lawsuit",
    "partnership",
    "layoff",
    "financing",
    "accident",
]
EventHorizon = Literal["short_term_noise", "mid_term_catalyst"]


class InstrumentInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str | None = None
    display_name: str | None = None
    exchange: str | None = None
    market: MarketName = "UNKNOWN"
    website_url: str | None = None
    industry: str | None = None
    listed_at: str | None = None
    notes: List[str] = Field(default_factory=list)


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str
    market: MarketName = "UNKNOWN"
    query: str
    instrument: InstrumentInfo = Field(default_factory=InstrumentInfo)
    priority_agents: List[str] = Field(default_factory=list)
    briefing_notes: List[str] = Field(default_factory=list)


class FilingEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    filing_type: str
    filed_at: str
    fiscal_period: str | None = None
    section_type: str = "unknown"
    heading: str = ""
    snippet: str = ""
    url: str | None = None
    title: str | None = None


class StructuredFilingFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    ticker: str | None = None
    filing_type: str = ""
    fiscal_period: str | None = None
    filed_at: str = ""
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
    operating_performance: str = ""
    risk_factors: List[str] = Field(default_factory=list)
    management_commentary: str = ""
    guidance_changes: str = ""


class FinancialDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "partial"] = "partial"
    missing_fields: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class FinancialSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None
    cash_and_equivalents: float | None = None
    accounts_receivable: float | None = None
    inventory: float | None = None
    total_assets: float | None = None
    total_debt: float | None = None
    total_liabilities: float | None = None
    shareholders_equity: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None
    free_cash_flow: float | None = None


class FinancialKeyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revenue_yoy_growth: float | None = None
    operating_income_yoy_growth: float | None = None
    net_income_yoy_growth: float | None = None
    operating_cash_flow_yoy_growth: float | None = None
    accounts_receivable_yoy_growth: float | None = None
    inventory_yoy_growth: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    operating_margin_change: float | None = None
    ocf_to_net_income: float | None = None
    fcf_margin: float | None = None
    debt_to_equity: float | None = None
    cash_to_debt: float | None = None


class FinancialMetricWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    value: float | None = None
    warning: str


class FinancialSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    summary: str
    severity: Literal["low", "medium", "high"] = "medium"
    evidence: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class FinancialAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["positive", "moderately_positive", "neutral", "moderately_negative", "negative"] = "neutral"
    summary: str
    main_positive: str = ""
    main_negative: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class FinancialScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    growth: int = Field(default=3, ge=1, le=5)
    profitability: int = Field(default=3, ge=1, le=5)
    cash_flow_quality: int = Field(default=3, ge=1, le=5)
    balance_sheet: int = Field(default=3, ge=1, le=5)
    overall: int = Field(default=3, ge=1, le=5)
    score_interpretation: str = "This score reflects financial health only, not valuation attractiveness."


class FinancialStatementAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subagent: str = "financial_statement_agent"
    company: str
    period: str | None = None
    currency: str | None = None
    unit: str | None = None
    data_quality: FinancialDataQuality = Field(default_factory=FinancialDataQuality)
    financial_snapshot: FinancialSnapshot = Field(default_factory=FinancialSnapshot)
    key_metrics: FinancialKeyMetrics = Field(default_factory=FinancialKeyMetrics)
    metric_warnings: List[FinancialMetricWarning] = Field(default_factory=list)
    strengths: List[FinancialSignal] = Field(default_factory=list)
    risks: List[FinancialSignal] = Field(default_factory=list)
    overall_financial_assessment: FinancialAssessment
    questions_for_main_agent: List[str] = Field(default_factory=list)
    financial_score: FinancialScore = Field(default_factory=FinancialScore)


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
    dominant_narrative: str = ""
    event_timeline: List[EventItem] = Field(default_factory=list)


class NewsExtractedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None = None
    unit: str
    raw_text: str


class NewsSignalDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "partial"] = "partial"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: List[str] = Field(default_factory=list)


class NewsSignalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    time: str | None = None
    category: str
    title: str
    summary: str
    keywords: List[str] = Field(default_factory=list)
    extracted_metrics: List[NewsExtractedMetric] = Field(default_factory=list)
    sentiment: SentimentName
    sentiment_score: float = Field(default=0.0, ge=0.0, le=1.0)
    sentiment_probs: Dict[str, float] = Field(default_factory=dict)
    sentiment_method: str
    source_title: str
    source_url: str | None = None
    sources: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    duplicate_count: int = 1
    one_line_summary: str
    audit_trail: Dict[str, Any] = Field(default_factory=dict)


class NewsSignalAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    entity_aliases: List[str] = Field(default_factory=list)
    raw_article_count: int = 0
    deduped_event_count: int = 0
    events: List[NewsSignalEvent] = Field(default_factory=list)
    dominant_narrative: str = ""
    data_quality: NewsSignalDataQuality = Field(default_factory=NewsSignalDataQuality)
    warnings: List[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    source_type: str
    category: str
    title: str
    snippet: str
    date: str | None = None
    url: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    category: EventCategory
    horizon: EventHorizon
    sentiment: SentimentName
    impact_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    date: str | None = None
    summary: str
    source_ids: List[str] = Field(default_factory=list)


class MarketReturns(BaseModel):
    model_config = ConfigDict(extra="forbid")

    one_day_pct: float | None = None
    one_week_pct: float | None = None
    one_month_pct: float | None = None
    three_month_pct: float | None = None


class VolumeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest: float | None = None
    average_20d: float | None = None
    turnover_rate: float | None = None


class VolatilitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realized_20d_pct: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None


class ValuationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_cap: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    eps_ttm: float | None = None
    book_value_per_share: float | None = None


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_price: float | None = None
    returns: MarketReturns = Field(default_factory=MarketReturns)
    volume: VolumeSnapshot = Field(default_factory=VolumeSnapshot)
    volatility: VolatilitySnapshot = Field(default_factory=VolatilitySnapshot)
    turnover: Dict[str, Any] = Field(default_factory=dict)
    valuation: ValuationSnapshot = Field(default_factory=ValuationSnapshot)
    as_of: str | None = None
    provider: str | None = None


class OhlcvBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None


class OhlcvSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    market: MarketName
    exchange: str | None = None
    display_name: str | None = None
    adjustment: str = "raw"
    provider: str = "market-data-mcp"
    cache_status: Literal["hit", "refresh", "miss"] = "miss"
    cached_until: str | None = None
    bars: List[OhlcvBar] = Field(default_factory=list)


class AgentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    summary: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    applicable: bool
    status: AgentStatus = "success"
    summary: str
    key_points: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    events: List[EventItem] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    observations: List[AgentObservation] = Field(default_factory=list)
    capabilities_used: List[str] = Field(default_factory=list)
    current_step: str | None = None
    tool_calls_count: int = 0
    warning: str | None = None
    reason: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    citations_count: int = 0


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    agent_name: str
    source_type: str
    category: str
    title: str
    snippet: str
    url: str | None = None
    date: str | None = None
    score: float = Field(default=0.0, ge=0.0)
    chunk_id: str | None = None
    document_id: str | None = None


class CriticSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_coverage_score: float = Field(ge=0.0, le=1.0)
    freshness_score: float = Field(ge=0.0, le=1.0)
    consistency_score: float = Field(ge=0.0, le=1.0)
    duplicate_event_bias_score: float = Field(ge=0.0, le=1.0)
    stance_supported: bool
    warnings: List[str] = Field(default_factory=list)


class InvestmentMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str
    market: MarketName
    instrument: InstrumentInfo = Field(default_factory=InstrumentInfo)
    stance: StanceName
    stance_confidence: float = Field(ge=0.0, le=1.0)
    thesis: str
    bull_case: List[str] = Field(default_factory=list)
    bear_case: List[str] = Field(default_factory=list)
    key_catalysts: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    valuation_view: str
    market_snapshot: MarketSnapshot | None = None
    watch_items: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    agent_outputs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    events: List[EventItem] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    critic_summary: CriticSummary | None = None


class InvestmentJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1)


class InvestmentJobCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    created_at: str


class AgentRunStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    status: JobStatus | AgentStatus
    current_step: str | None = None
    tool_calls_count: int = 0
    summary: str | None = None
    warning: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class InvestmentJobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    company_name: str
    market: MarketName = "UNKNOWN"
    status: JobStatus
    research_brief: ResearchBrief | None = None
    agent_runs: List[AgentRunStatus] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    memo_id: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class InvestmentJobListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    company_name: str
    market: MarketName = "UNKNOWN"
    status: JobStatus
    created_at: str
    memo_id: str | None = None


class InvestmentMemoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memo_id: str
    job_id: str
    memo: InvestmentMemo


class EvidenceResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agent_name: str
    source_type: str
    category: str
    title: str
    url: str | None = None
    published_at: str | None = None
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    items: List[EvidenceResponseItem] = Field(default_factory=list)


class MarketOhlcvResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    company_name: str
    market: MarketName
    instrument: InstrumentInfo = Field(default_factory=InstrumentInfo)
    series: OhlcvSeries


class InvestmentState(TypedDict, total=False):
    company_name: str
    research_brief: ResearchBrief
    agent_results: Dict[str, AgentResult]
    evidence_items: List[EvidenceItem]
    event_items: List[EventItem]
    warnings: List[str]
    errors: List[str]
    coverage: Dict[str, Any]
    retrieval_chunks: List[Any]
    memo: InvestmentMemo
    progress_callback: Callable[[dict[str, Any]], None]


# Compatibility aliases for the deprecated v1 API shape.
ModuleName = str
ModuleStatus = AgentStatus
AnalyzeRequest = InvestmentJobRequest
EvidenceCard = EvidenceItem
TimelineEvent = EventItem
PlannerOutput = ResearchBrief
CompanyIdentifiers = InstrumentInfo
ModuleResult = AgentResult
CoverageCheck = Dict[str, Any]
EvaluationSummary = CriticSummary
FinalReport = InvestmentMemo
ResearchJobCreateResponse = InvestmentJobCreateResponse
ModuleRunStatus = AgentRunStatus
ResearchJobStatusResponse = InvestmentJobStatusResponse
ResearchJobListItem = InvestmentJobListItem
ReportResponse = InvestmentMemoResponse
ResearchState = InvestmentState
