from app.agents import critic_output
from app.research.context import build_unified_research_context
from app.schemas import AgentResult, EventItem, InstrumentInfo, MarketSnapshot, ResearchBrief


def _agent_results():
    return {
        "market": AgentResult(
            agent_name="market",
            applicable=True,
            status="success",
            summary="市场画像显示近一月走势偏强。",
            key_points=["近一月收益 12.5%", "估值快照 PE 18.2 / PB 4.1"],
            payload={
                "signal_bias": "positive",
                "market_snapshot": MarketSnapshot(last_price=1520.0, as_of="2026-04-16", provider="market-data-mcp").model_dump(),
            },
        ),
        "filing": AgentResult(
            agent_name="filing",
            applicable=True,
            status="partial",
            summary="财报子 Agent 对财务健康度的评分为 3/5。",
            key_points=["经营现金流质量一般。"],
            payload={
                "signal_bias": "neutral",
                "financial_statement_analysis": {
                    "company": "贵州茅台",
                    "period": "2025FY",
                    "overall_financial_assessment": {
                        "rating": "neutral",
                        "summary": "财务数据可用性有限，结论应保守。",
                        "confidence": 0.55,
                    },
                    "financial_score": {"growth": 3, "profitability": 3, "cash_flow_quality": 3, "balance_sheet": 3, "overall": 3},
                    "financial_snapshot": {"revenue": 1688.38, "net_income": 823.2},
                    "key_metrics": {"net_margin": 0.48},
                    "risks": [
                        {
                            "type": "data_quality",
                            "summary": "部分财务字段缺失。",
                            "severity": "medium",
                            "evidence": {"missing_fields": ["free_cash_flow"]},
                            "confidence": 0.8,
                        }
                    ],
                },
            },
            warning="Financial statement extraction is partial.",
        ),
        "message_intel": AgentResult(
            agent_name="message_intel",
            applicable=True,
            status="success",
            summary="近期新闻信号更偏向正面催化。",
            key_points=["公司公布高比例现金分红方案。"],
            payload={
                "signal_bias": "positive",
                "news_signal_analysis": {
                    "company": "贵州茅台",
                    "raw_article_count": 3,
                    "deduped_event_count": 1,
                    "dominant_narrative": "近期新闻信号更偏向正面催化。",
                    "events": [
                        {
                            "event_id": "evt_001",
                            "category": "dividend",
                            "title": "公司公告年度分红方案",
                            "summary": "新闻集中报道公司公布高比例现金分红方案。",
                            "keywords": ["分红"],
                            "extracted_metrics": [],
                            "sentiment": "positive",
                            "sentiment_score": 0.82,
                            "sentiment_probs": {"positive": 0.82, "neutral": 0.18, "negative": 0.0},
                            "sentiment_method": "rule_fallback",
                            "source_title": "公司公告年度分红方案",
                            "source_url": "https://news.example.com/dividend",
                            "sources": ["Example News"],
                            "source_urls": ["https://news.example.com/dividend"],
                            "duplicate_count": 1,
                            "one_line_summary": "贵州茅台发生分红事件：涉及分红，情感判断为正面。",
                            "audit_trail": {},
                        }
                    ],
                },
            },
        ),
    }


def test_unified_research_context_builds_agent_interface_and_llm_document():
    brief = ResearchBrief(
        company_name="贵州茅台",
        market="A_SHARE",
        query="贵州茅台",
        instrument=InstrumentInfo(symbol="600519", display_name="贵州茅台", market="A_SHARE"),
        briefing_notes=["Instrument identity aligned with the input query."],
    )
    event = EventItem(
        title="公司公告年度分红方案",
        category="earnings",
        horizon="mid_term_catalyst",
        sentiment="positive",
        impact_score=0.82,
        confidence_score=0.9,
        date="2026-04-11",
        summary="新闻集中报道公司公布高比例现金分红方案。",
        source_ids=["https://news.example.com/dividend"],
    )

    context = build_unified_research_context(
        brief,
        _agent_results(),
        [event],
        {"valid_agent_count": 3, "evidence_count": 5, "event_count": 1, "warnings": []},
    )

    assert set(context.agents) == {"market", "filing", "message_intel"}
    assert context.cross_agent["overall_signal_bias"] == "positive"
    assert context.agents["market"].metrics["last_price"] == 1520.0
    assert context.agents["filing"].findings[0].category == "financial_assessment"
    assert context.agents["message_intel"].findings[0].source_refs == ["https://news.example.com/dividend"]
    assert "## market Agent" in context.llm_context_document
    assert "## filing Agent" in context.llm_context_document
    assert "## message_intel Agent" in context.llm_context_document


def test_critic_output_persists_unified_context_for_dialogue(monkeypatch):
    monkeypatch.setattr(critic_output, "is_llm_available", lambda: False)
    brief = ResearchBrief(
        company_name="贵州茅台",
        market="A_SHARE",
        query="贵州茅台",
        instrument=InstrumentInfo(symbol="600519", display_name="贵州茅台", market="A_SHARE"),
    )

    memo = critic_output.run_critic_output_agent(
        brief=brief,
        agent_results=_agent_results(),
        events=[],
        coverage={"valid_agent_count": 3, "evidence_count": 5, "event_count": 1, "warnings": []},
        chunks=[],
    )

    assert memo.research_context is not None
    assert memo.llm_context_document.startswith("# Unified Company Research Context")
    assert "unified_research" in memo.agent_outputs["market"]
    assert memo.agent_outputs["message_intel"]["unified_research"]["findings"]


def test_critic_output_heuristic_uses_five_level_stance():
    brief = ResearchBrief(
        company_name="贵州茅台",
        market="A_SHARE",
        query="贵州茅台",
        instrument=InstrumentInfo(symbol="600519", display_name="贵州茅台", market="A_SHARE"),
    )

    draft = critic_output._heuristic_draft(
        brief=brief,
        agent_results=_agent_results(),
        events=[],
        coverage={"valid_agent_count": 3, "warnings": []},
    )

    assert draft.stance == "strong_bullish"
    assert draft.stance_confidence > 0.55


def test_critic_output_heuristic_keeps_mild_direction_for_single_agent_signal():
    brief = ResearchBrief(company_name="测试公司", market="A_SHARE", query="测试公司")
    agent_results = {
        "market": AgentResult(
            agent_name="market",
            applicable=True,
            status="success",
            summary="市场走势偏弱。",
            key_points=["近一月收益 -12%"],
            payload={"signal_bias": "negative"},
        )
    }

    draft = critic_output._heuristic_draft(
        brief=brief,
        agent_results=agent_results,
        events=[],
        coverage={"valid_agent_count": 1, "warnings": []},
    )

    assert draft.stance == "bearish"
