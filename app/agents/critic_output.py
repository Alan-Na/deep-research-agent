from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from app.llm import get_chat_model, is_llm_available
from app.research.retrieval import bind_citations_to_memo
from app.schemas import EventItem, InstrumentInfo, InvestmentMemo, MarketSnapshot, ResearchBrief, StanceName
from app.utils.text import truncate_text

CRITIC_OUTPUT_SYSTEM_PROMPT = """
你是投资研究系统中的 Critic & Output Agent。

规则：
- 只能使用提供的 research brief、agent outputs、events、coverage。
- 不要使用外部知识。
- 必须输出明确 stance: bullish / neutral / bearish。
- 如果证据偏弱、agent 互相冲突、或关键信号不足，优先输出 neutral。
- bull_case / bear_case / key_catalysts / key_risks 要简洁、证据导向。
- valuation_view 只能基于 market agent 提供的 market snapshot。
"""

CRITIC_OUTPUT_USER_PROMPT = """
Research brief:
{brief_payload}

Agent outputs:
{agent_payload}

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
    draft = _draft_memo_with_llm(brief, agent_results, events, coverage) if is_llm_available() else None
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
        agent_outputs={name: result.payload for name, result in agent_results.items()},
        events=events,
    )
    return bind_citations_to_memo(memo, chunks, coverage)


def _draft_memo_with_llm(
    brief: ResearchBrief,
    agent_results: dict[str, Any],
    events: list[EventItem],
    coverage: dict[str, Any],
) -> InvestmentMemoDraft | None:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CRITIC_OUTPUT_SYSTEM_PROMPT),
            ("human", CRITIC_OUTPUT_USER_PROMPT),
        ]
    )
    simplified_agent_outputs = {
        name: {
            "summary": result.summary,
            "status": result.status,
            "key_points": result.key_points[:5],
            "payload": result.payload,
            "warning": result.warning,
        }
        for name, result in agent_results.items()
    }
    try:
        llm = get_chat_model(temperature=0.1)
        structured = llm.with_structured_output(InvestmentMemoDraft, method="json_schema")
        payload = {
            "brief_payload": brief.model_dump_json(indent=2),
            "agent_payload": json.dumps(simplified_agent_outputs, ensure_ascii=False, indent=2),
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
    signal_biases = coverage.get("signal_biases") or {}
    positive = len([value for value in signal_biases.values() if value == "positive"])
    negative = len([value for value in signal_biases.values() if value == "negative"])
    if positive > negative:
        stance = "bullish"
    elif negative > positive:
        stance = "bearish"
    else:
        stance = "neutral"

    confidence = min(0.85, 0.35 + (coverage.get("valid_agent_count", 0) * 0.1) + (0.08 if positive != negative else 0.0))
    market_summary = agent_results.get("market").summary if agent_results.get("market") else "市场信息有限"
    filing_summary = agent_results.get("filing").summary if agent_results.get("filing") else "披露信息有限"
    news_summary = agent_results.get("news_risk").summary if agent_results.get("news_risk") else "新闻信息有限"
    thesis = f"{market_summary} {filing_summary} {news_summary}"

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
        bull_case = ["正向证据仍然有限，更多来自市场与官网定性信号。"]
        bear_case = ["负向证据仍然有限，更多来自新闻和披露风险提示。"]
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


def _market_snapshot_from_agent(agent_result: Any) -> MarketSnapshot | None:
    if not agent_result:
        return None
    snapshot = agent_result.payload.get("market_snapshot")
    if not snapshot:
        return None
    return MarketSnapshot.model_validate(snapshot)
