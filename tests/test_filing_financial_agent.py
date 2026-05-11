from app.agents.filing import (
    AShareDisclosureProvider,
    FilingDocument,
    _calculate_key_metrics,
    _detect_risks,
    _parse_document_financials,
    filing_agent_definition,
)
from app.agents.runtime import execute_react_agent
from app.schemas import FinancialKeyMetrics, FinancialSnapshot, InstrumentInfo, ResearchBrief


def test_financial_parser_aliases_units_and_negative_capex():
    document = {
        "provider": "sec",
        "filing_type": "10-K",
        "title": "Example Corp 2024 annual report",
        "filed_at": "2025-03-01",
        "url": "https://example.com/10k",
        "text": """
        USD in millions
        Revenue 12,500
        Gross profit 5,500
        Operating income 2,600
        Net income 1,900
        EPS 3.20
        Cash and cash equivalents 8,200
        Accounts receivable 1,400
        Inventory 900
        Total assets 25,000
        Total debt 6,000
        Total liabilities 10,000
        Shareholders' equity 15,000
        Net cash provided by operating activities 2,100
        Capital expenditures (600)
        """,
    }
    brief = ResearchBrief(company_name="Example Corp", market="US", query="Example Corp")

    parsed = _parse_document_financials(brief, document)

    assert parsed["currency"] == "USD"
    assert parsed["unit"] == "millions"
    assert parsed["income_statement"]["revenue"] == 12500
    assert parsed["income_statement"]["gross_profit"] == 5500
    assert parsed["balance_sheet"]["cash_and_equivalents"] == 8200
    assert parsed["cash_flow_statement"]["capital_expenditure"] == -600


def test_financial_calculator_handles_zero_negative_and_missing_values():
    current = {
        "company": "Example Corp",
        "period": "2024FY",
        "currency": "USD",
        "unit": "millions",
        "document": {"title": "current", "filed_at": "2025-03-01"},
        "income_statement": {"revenue": 100, "gross_profit": 40, "operating_income": 20, "net_income": -10},
        "balance_sheet": {"cash_and_equivalents": 0, "accounts_receivable": 20, "inventory": 30, "total_debt": 0, "shareholders_equity": 50},
        "cash_flow_statement": {"operating_cash_flow": 5, "capital_expenditure": -20},
        "field_sources": {},
    }
    same_last_year = {
        "income_statement": {"revenue": 0, "operating_income": -10, "net_income": -5},
        "balance_sheet": {"accounts_receivable": 10, "inventory": 20},
        "cash_flow_statement": {"operating_cash_flow": 10},
    }

    result = _calculate_key_metrics(
        ResearchBrief(company_name="Example Corp", market="US", query="Example Corp"),
        {},
        {"payload": {"current_period": current, "same_period_last_year": same_last_year}},
    )

    snapshot = FinancialSnapshot.model_validate(result["payload"]["financial_snapshot"])
    metrics = FinancialKeyMetrics.model_validate(result["payload"]["key_metrics"])
    warnings = {item["metric"]: item["warning"] for item in result["payload"]["metric_warnings"]}

    assert snapshot.capital_expenditure == 20
    assert snapshot.free_cash_flow == -15
    assert metrics.gross_margin == 0.4
    assert metrics.net_income_yoy_growth == -1
    assert warnings["revenue_yoy_growth"] == "previous_period_value_is_zero"
    assert warnings["operating_income_yoy_growth"] == "prior_period_value_is_negative_growth_rate_less_reliable"
    assert warnings["cash_to_debt"] == "no_reported_debt_or_debt_missing"


def test_financial_risk_flags():
    snapshot = FinancialSnapshot(
        operating_cash_flow=800,
        capital_expenditure=1200,
        free_cash_flow=-400,
        cash_and_equivalents=500,
        total_debt=2300,
    )
    metrics = FinancialKeyMetrics(
        revenue_yoy_growth=0.18,
        operating_margin_change=-0.035,
        net_income_yoy_growth=0.25,
        operating_cash_flow_yoy_growth=-0.12,
        accounts_receivable_yoy_growth=0.35,
        inventory_yoy_growth=0.40,
        cash_to_debt=0.22,
    )

    risks = _detect_risks(snapshot, metrics)
    risk_types = {item.type for item in risks}

    assert risk_types == {
        "revenue_growth_with_margin_pressure",
        "profit_growth_not_supported_by_cash_flow",
        "receivables_growing_faster_than_revenue",
        "inventory_growing_faster_than_revenue",
        "negative_free_cash_flow",
        "weak_cash_debt_coverage",
    }
    assert next(item for item in risks if item.type == "profit_growth_not_supported_by_cash_flow").severity == "high"


def test_filing_agent_runs_full_financial_statement_workflow(monkeypatch):
    def fake_fetch(self, brief, limit=3):
        return [
            FilingDocument(
                provider="cninfo",
                filing_type="年报",
                title="Example Corp 2024 年报",
                filed_at="2025-03-01",
                url="https://example.com/current",
                text="""
                单位：百万元
                营业收入 12500 毛利 5500 营业利润 2600 归母净利润 1900 基本每股收益 3.20
                货币资金 8200 应收账款 1400 存货 900 资产总计 25000 总债务 6000 负债合计 10000 所有者权益合计 15000
                经营活动产生的现金流量净额 2100 购建固定资产、无形资产和其他长期资产支付的现金 600
                """,
            ),
            FilingDocument(
                provider="cninfo",
                filing_type="年报",
                title="Example Corp 2023 年报",
                filed_at="2024-03-01",
                url="https://example.com/prior",
                text="""
                单位：百万元
                营业收入 10000 毛利 4300 营业利润 2200 归母净利润 1700
                货币资金 7000 应收账款 1200 存货 820 总债务 6500 所有者权益合计 14000
                经营活动产生的现金流量净额 1800
                """,
            ),
        ]

    monkeypatch.setattr(AShareDisclosureProvider, "fetch_recent_documents", fake_fetch)
    brief = ResearchBrief(
        company_name="Example Corp",
        market="A_SHARE",
        query="Example Corp",
        instrument=InstrumentInfo(symbol="000001", market="A_SHARE", display_name="Example Corp"),
    )

    result = execute_react_agent(filing_agent_definition(), brief, {"research_brief": brief.model_dump()})

    analysis = result.payload["financial_statement_analysis"]
    assert result.agent_name == "filing"
    assert result.tool_calls_count == 5
    assert analysis["financial_snapshot"]["revenue"] == 12500
    assert analysis["key_metrics"]["revenue_yoy_growth"] == 0.25
    assert analysis["financial_score"]["score_interpretation"].startswith("This score reflects financial health")
    assert result.status in {"success", "partial"}
    assert result.key_points
