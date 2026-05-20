from app.research.context import build_unified_research_context
from app.schemas import (
    AgentResult,
    CompanyChatRequest,
    CompanyChatToolCall,
    InstrumentInfo,
    MarketSnapshot,
    ResearchBrief,
    ResearchContextResponse,
)
from app.services import company_chat
from app.services.company_chat import answer_company_question


def _context_response() -> ResearchContextResponse:
    brief = ResearchBrief(
        company_name="宁德时代",
        market="A_SHARE",
        query="宁德时代",
        instrument=InstrumentInfo(symbol="300750", display_name="宁德时代", market="A_SHARE"),
    )
    agent_results = {
        "market": AgentResult(
            agent_name="market",
            applicable=True,
            status="success",
            summary="宁德时代 的市场画像已生成，最新价 447.66，近1个月收益 18.53%。",
            key_points=["最新价 447.66", "近1个月收益 18.53%"],
            payload={
                "signal_bias": "positive",
                "market_snapshot": MarketSnapshot(last_price=447.66, as_of="2026-05-11", provider="market-data-mcp").model_dump(),
            },
        ),
        "filing": AgentResult(
            agent_name="filing",
            applicable=True,
            status="partial",
            summary="财报子 Agent 对财务健康度的评分为 3/5。",
            key_points=["财报字段抽取较弱。"],
            payload={
                "signal_bias": "neutral",
                "financial_statement_analysis": {
                    "company": "宁德时代",
                    "overall_financial_assessment": {
                        "rating": "neutral",
                        "summary": "由于部分核心字段缺失，该判断应保守使用。",
                        "confidence": 0.55,
                    },
                    "financial_score": {"growth": 3, "profitability": 3, "cash_flow_quality": 3, "balance_sheet": 3, "overall": 3},
                    "financial_snapshot": {"revenue": 1291.31},
                    "key_metrics": {"net_margin": 0.16},
                    "filing_coverage": {
                        "parsed_period_count": 4,
                        "documents": [
                            {
                                "title": "宁德时代 2025 一季报",
                                "filing_type": "一季报",
                                "period": "2025Q1",
                                "filed_at": "2025-04-25",
                                "url": "https://example.com/q1",
                            }
                        ],
                    },
                    "period_analyses": [
                        {
                            "period": "2025Q1",
                            "filing_type": "一季报",
                            "financial_snapshot": {"revenue": 1291.31, "net_income": 139.63, "operating_cash_flow": 110.0},
                        }
                    ],
                    "trend_analysis": {
                        "periods_covered": ["2025Q1", "2024FY", "2023FY"],
                        "margin_trends": [{"metric": "gross_margin", "direction": "improving", "change": 0.02}],
                        "narrative": "gross_margin is improving",
                    },
                },
            },
        ),
        "message_intel": AgentResult(
            agent_name="message_intel",
            applicable=True,
            status="success",
            summary="消息面识别到 10 个新闻信号事件。",
            key_points=["近期新闻信号更偏向正面催化。"],
            payload={"signal_bias": "positive", "news_signal_analysis": {"company": "宁德时代", "events": []}},
        ),
    }
    context = build_unified_research_context(brief, agent_results, [], {"valid_agent_count": 3, "evidence_count": 3, "event_count": 0})
    return ResearchContextResponse(
        memo_id="memo_1",
        job_id="job_1",
        research_context=context,
        llm_context_document=context.llm_context_document,
    )


def test_company_chat_uses_heuristic_tools_without_llm(monkeypatch):
    monkeypatch.setattr(company_chat, "is_llm_available", lambda: False)

    response = answer_company_question(
        _context_response(),
        CompanyChatRequest(question="这家公司当前股价和估值怎么看？"),
    )

    assert not response.rejected
    assert [item.name for item in response.tool_calls] == ["get_market_data"]
    assert "447.66" in response.answer
    assert response.sources


def test_company_chat_can_reject_out_of_scope_question(monkeypatch):
    monkeypatch.setattr(
        company_chat,
        "_select_chat_tools",
        lambda context, question, history: [CompanyChatToolCall(name="reject_question", arguments={"reason": "只能回答当前公司的问题。"})],
    )

    response = answer_company_question(
        _context_response(),
        CompanyChatRequest(question="帮我分析苹果公司。"),
    )

    assert response.rejected
    assert response.answer == "只能回答当前公司的问题。"
    assert response.tool_calls[0].name == "reject_question"


def test_company_chat_strips_markdown_bold_from_llm_answer(monkeypatch):
    monkeypatch.setattr(company_chat, "is_llm_available", lambda: True)
    monkeypatch.setattr(
        company_chat,
        "_select_chat_tools",
        lambda context, question, history: [CompanyChatToolCall(name="get_market_data", arguments={"focus": question})],
    )

    class FakeMessage:
        content = "根据 Market Agent，**最新价 447.66 元**，**近1个月收益 18.53%**。"

    class FakeLlm:
        def invoke(self, messages):
            return FakeMessage()

    monkeypatch.setattr(company_chat, "get_chat_model", lambda temperature=0.0: FakeLlm())

    response = answer_company_question(
        _context_response(),
        CompanyChatRequest(question="今天股价怎么样？"),
    )

    assert "**" not in response.answer
    assert "最新价 447.66 元" in response.answer


def test_company_chat_financial_trend_tool(monkeypatch):
    monkeypatch.setattr(company_chat, "is_llm_available", lambda: False)

    response = answer_company_question(
        _context_response(),
        CompanyChatRequest(question="财报里毛利率趋势和商誉变化怎么看？"),
    )

    tool_names = [item.name for item in response.tool_calls]
    assert "get_financial_trends" in tool_names
    assert "gross_margin is improving" in response.answer
    assert response.sources
