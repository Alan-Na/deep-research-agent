from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from app.llm import get_chat_model, is_llm_available
from app.research.context import build_unified_research_context
from app.research.retrieval import bind_citations_to_memo
from app.schemas import EventItem, InstrumentInfo, InvestmentMemo, MarketSnapshot, ResearchBrief, StanceName, UnifiedResearchContext
from app.utils.text import truncate_text

CRITIC_OUTPUT_SYSTEM_PROMPT = """
你是投资研究系统中的 Critic & Output Agent。

规则：
- 只能使用提供的 research brief、agent outputs、events、coverage。
- 优先使用 unified research context document；它是三个研究 agent 输出的规范化版本。
- 不要使用外部知识。
- 必须输出明确 stance，且只能是 strong_bullish / bullish / neutral / bearish / strong_bearish。
- strong_bullish：至少两个独立研究 agent 给出强正面证据，且没有高严重度反向风险。
- bullish：正面证据明显多于风险，但强度或覆盖度不足以判为 strong_bullish。
- neutral：多空信号均衡、证据不足、或核心数据缺失导致无法形成方向性判断。
- bearish：负面证据明显多于正面证据，但尚未形成多源高严重度风险。
- strong_bearish：至少两个独立来源显示高严重度负面信号，或财务/消息/市场同时转弱。
- 不要因为存在少量不确定性就默认 neutral；如果证据有清晰方向，使用 bullish 或 bearish，并在 confidence 中体现不确定性。
- bull_case / bear_case / key_catalysts / key_risks 要简洁、证据导向。
- valuation_view 只能基于 market agent 提供的 market snapshot。
"""

CRITIC_OUTPUT_USER_PROMPT = """
Research brief:
{brief_payload}

Unified research context document:
{research_context_document}

Coverage:
{coverage_payload}

Events:
{events_payload}
"""


class InvestmentMemoDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stance: StanceName
    stance_confidence: float = Field(ge=0.0, le=1.0)
    thesis: str
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    key_catalysts: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    valuation_view: str
    watch_items: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def run_critic_output_agent(
    brief: ResearchBrief,
    agent_results: dict[str, Any],
    events: list[EventItem],
    coverage: dict[str, Any],
    chunks: list[Any],
) -> InvestmentMemo:
    research_context = build_unified_research_context(brief, agent_results, events, coverage)
    draft = _draft_memo_with_llm(brief, research_context, events, coverage) if is_llm_available() else None
    if draft is None:
        draft = _heuristic_draft(brief, agent_results, events, coverage)

    market_snapshot = _market_snapshot_from_agent(agent_results.get("market"))
    memo = InvestmentMemo(
        company_name=brief.company_name,
        market=brief.market,
        instrument=brief.instrument if isinstance(brief.instrument, InstrumentInfo) else InstrumentInfo.model_validate(brief.instrument),
        stance=draft.stance,
        stance_confidence=draft.stance_confidence,
        thesis=draft.thesis,
        bull_case=draft.bull_case,
        bear_case=draft.bear_case,
        key_catalysts=draft.key_catalysts,
        key_risks=draft.key_risks,
        valuation_view=draft.valuation_view,
        market_snapshot=market_snapshot,
        watch_items=draft.watch_items,
        limitations=list(dict.fromkeys([*(draft.limitations or []), *(coverage.get("warnings") or [])]))[:10],
        agent_outputs={
            name: {
                **result.payload,
                "unified_research": research_context.agents[name].model_dump() if name in research_context.agents else {},
            }
            for name, result in agent_results.items()
        },
        research_context=research_context,
        llm_context_document=research_context.llm_context_document,
        events=events,
    )
    return bind_citations_to_memo(memo, chunks, coverage)


def _draft_memo_with_llm(
    brief: ResearchBrief,
    research_context: UnifiedResearchContext,
    events: list[EventItem],
    coverage: dict[str, Any],
) -> InvestmentMemoDraft | None:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CRITIC_OUTPUT_SYSTEM_PROMPT),
            ("human", CRITIC_OUTPUT_USER_PROMPT),
        ]
    )
    try:
        llm = get_chat_model(temperature=0.1)
        structured = llm.with_structured_output(InvestmentMemoDraft, method="json_schema")
        payload = {
            "brief_payload": brief.model_dump_json(indent=2),
            "research_context_document": research_context.llm_context_document,
            "coverage_payload": json.dumps(coverage, ensure_ascii=False, indent=2),
            "events_payload": json.dumps([item.model_dump() for item in events[:10]], ensure_ascii=False, indent=2),
        }
        result = (prompt | structured).invoke(payload)
        return InvestmentMemoDraft.model_validate(result)
    except Exception:
        return None


def _heuristic_draft(
    brief: ResearchBrief,
    agent_results: dict[str, Any],
    events: list[EventItem],
    coverage: dict[str, Any],
) -> InvestmentMemoDraft:
    stance_score = _stance_score(agent_results, events, coverage)
    stance = _stance_from_score(stance_score)
    directional = stance != "neutral"
    confidence = min(
        0.92,
        0.34
        + (coverage.get("valid_agent_count", 0) * 0.08)
        + min(abs(stance_score), 2.8) * 0.12
        + (0.05 if directional else 0.0),
    )
    market_summary = agent_results.get("market").summary if agent_results.get("market") else "市场信息有限"
    filing_summary = _filing_financial_summary(agent_results.get("filing"))
    message_result = agent_results.get("message_intel") or agent_results.get("news_risk") or agent_results.get("web_intel")
    message_summary = message_result.summary if message_result else "消息面信息有限"
    thesis = f"{market_summary} {filing_summary} {message_summary}"

    bull_case = []
    bear_case = []
    catalysts = []
    risks = []
    watch_items = []

    for name, result in agent_results.items():
        for point in result.key_points[:3]:
            if result.payload.get("signal_bias") == "positive":
                bull_case.append(point)
            elif result.payload.get("signal_bias") == "negative":
                bear_case.append(point)
            else:
                watch_items.append(point)

    for event in events[:8]:
        line = f"{event.title} | {event.category} | impact {event.impact_score}"
        if event.horizon == "mid_term_catalyst" and event.sentiment == "positive":
            catalysts.append(line)
        if event.sentiment == "negative":
            risks.append(line)
        elif event.horizon == "short_term_noise":
            watch_items.append(line)

    valuation_view = "估值数据暂不完整。"
    market_snapshot = _market_snapshot_from_agent(agent_results.get("market"))
    if market_snapshot:
        pe = market_snapshot.valuation.pe_ttm
        pb = market_snapshot.valuation.pb
        valuation_view = (
            f"Market Agent 显示最新价 {market_snapshot.last_price}，"
            f"PE {pe if pe is not None else 'n/a'}，PB {pb if pb is not None else 'n/a'}。"
        )

    limitations = list(coverage.get("warnings") or [])
    if not bull_case and not bear_case:
        bull_case = ["正向证据仍然有限，更多来自市场与消息面定性信号。"]
        bear_case = ["负向证据仍然有限，更多来自消息面和披露风险提示。"]
    return InvestmentMemoDraft(
        stance=stance,
        stance_confidence=round(confidence, 2),
        thesis=truncate_text(thesis, 520),
        bull_case=list(dict.fromkeys(bull_case))[:5],
        bear_case=list(dict.fromkeys(bear_case))[:5],
        key_catalysts=list(dict.fromkeys(catalysts))[:5] or ["暂无高置信度中期催化，需继续跟踪公告与新闻。"],
        key_risks=list(dict.fromkeys(risks))[:5] or ["暂无高置信度单一风险源，需结合后续披露继续跟踪。"],
        valuation_view=valuation_view,
        watch_items=list(dict.fromkeys(watch_items))[:6],
        limitations=limitations[:8],
    )


def _stance_score(agent_results: dict[str, Any], events: list[EventItem], coverage: dict[str, Any]) -> float:
    signal_biases = coverage.get("signal_biases") or {}
    if not signal_biases:
        signal_biases = {
            name: result.payload.get("signal_bias")
            for name, result in agent_results.items()
            if getattr(result, "payload", None)
        }

    weights = {"market": 0.9, "filing": 1.2, "message_intel": 1.0, "news_risk": 0.8, "web_intel": 0.5}
    score = 0.0
    for name, bias in signal_biases.items():
        weight = weights.get(name, 0.7)
        if bias == "positive":
            score += weight
        elif bias == "negative":
            score -= weight

    filing = agent_results.get("filing")
    filing_analysis = filing.payload.get("financial_statement_analysis") if filing and filing.payload else None
    if isinstance(filing_analysis, dict):
        financial_score = filing_analysis.get("financial_score") or {}
        overall = financial_score.get("overall")
        if isinstance(overall, (int, float)):
            score += {5: 0.75, 4: 0.35, 2: -0.35, 1: -0.75}.get(int(overall), 0.0)
        risks = filing_analysis.get("risks") or []
        high_risk_count = len([item for item in risks if isinstance(item, dict) and item.get("severity") == "high"])
        score -= min(0.9, high_risk_count * 0.45)
        strengths = filing_analysis.get("strengths") or []
        score += min(0.45, len(strengths) * 0.2)

    message = agent_results.get("message_intel") or agent_results.get("news_risk") or agent_results.get("web_intel")
    news_analysis = message.payload.get("news_signal_analysis") if message and message.payload else None
    if isinstance(news_analysis, dict):
        for item in (news_analysis.get("events") or [])[:8]:
            if not isinstance(item, dict):
                continue
            sentiment = item.get("sentiment")
            sentiment_score = float(item.get("sentiment_score") or 0.0)
            duplicate_count = int(item.get("duplicate_count") or 1)
            event_weight = 0.12 + min(0.16, duplicate_count * 0.03) + min(0.12, sentiment_score * 0.12)
            if sentiment == "positive":
                score += event_weight
            elif sentiment == "negative":
                score -= event_weight

    for event in events[:8]:
        event_weight = 0.12 + min(0.28, float(event.impact_score or 0.0) * 0.28)
        if event.sentiment == "positive":
            score += event_weight
        elif event.sentiment == "negative":
            score -= event_weight

    return round(score, 4)


def _stance_from_score(score: float) -> StanceName:
    if score >= 2.0:
        return "strong_bullish"
    if score >= 0.65:
        return "bullish"
    if score <= -2.0:
        return "strong_bearish"
    if score <= -0.65:
        return "bearish"
    return "neutral"


def _market_snapshot_from_agent(agent_result: Any) -> MarketSnapshot | None:
    if not agent_result:
        return None
    snapshot = agent_result.payload.get("market_snapshot")
    if not snapshot:
        return None
    return MarketSnapshot.model_validate(snapshot)


def _filing_financial_summary(agent_result: Any) -> str:
    if not agent_result:
        return "披露信息有限"
    analysis = agent_result.payload.get("financial_statement_analysis") if agent_result.payload else None
    if isinstance(analysis, dict):
        assessment = analysis.get("overall_financial_assessment") or {}
        summary = assessment.get("summary")
        if summary:
            return str(summary)
    return agent_result.summary or "披露信息有限"
