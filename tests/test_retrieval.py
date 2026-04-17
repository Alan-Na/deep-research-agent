from app.research.retrieval import bind_citations_to_memo, build_documents_and_chunks, build_evidence_index
from app.schemas import AgentResult, EvidenceItem, EventItem, InstrumentInfo, InvestmentMemo, MarketSnapshot


def test_build_evidence_index_and_chunks():
    agent_results = {
        "web_intel": AgentResult(
            agent_name="web_intel",
            applicable=True,
            status="success",
            summary="官网强调高端白酒品牌、渠道与投资者关系页面。",
            key_points=["IR 页面提供了公告和投资者沟通入口。"],
            payload={"signal_bias": "positive"},
            evidence=[
                EvidenceItem(
                    agent_name="web_intel",
                    source_type="official_website",
                    category="website_page",
                    title="官网首页",
                    date="2026-04-10",
                    snippet="官网强调高端品牌、渠道管理与投资者关系页面。",
                    url="https://example.com",
                )
            ],
        ),
        "news_risk": AgentResult(
            agent_name="news_risk",
            applicable=True,
            status="success",
            summary="近期新闻聚焦分红与年报表现。",
            key_points=["高分红是近期最强的中期催化之一。"],
            payload={"signal_bias": "positive"},
            events=[
                EventItem(
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
            ],
            evidence=[
                EvidenceItem(
                    agent_name="news_risk",
                    source_type="news_article",
                    category="news_article",
                    title="年度分红方案",
                    date="2026-04-11",
                    snippet="新闻报道公司公布高比例现金分红方案。",
                    url="https://news.example.com/dividend",
                )
            ],
        ),
    }

    evidence_items, events, coverage = build_evidence_index(agent_results)
    documents, chunks = build_documents_and_chunks(agent_results)

    assert evidence_items
    assert events
    assert coverage["valid_agent_count"] == 2
    assert documents
    assert chunks
    assert {chunk.source_type for chunk in chunks} >= {"official_website", "news_article", "agent_summary"}


def test_bind_citations_and_critic_summary():
    agent_results = {
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
            evidence=[
                EvidenceItem(
                    agent_name="market",
                    source_type="market_data",
                    category="price_snapshot",
                    title="市场快照",
                    date="2026-04-16",
                    snippet="最新价 1520.0，近一月收益 12.5%，20 日波动率 18%。",
                )
            ],
        ),
        "filing": AgentResult(
            agent_name="filing",
            applicable=True,
            status="success",
            summary="披露文件显示营收和净利润仍具韧性。",
            key_points=["披露文件中提到营业收入 1688.38 亿元", "披露文件中提到归母净利润 823.2 亿元"],
            payload={"signal_bias": "positive"},
            evidence=[
                EvidenceItem(
                    agent_name="filing",
                    source_type="disclosure_document",
                    category="filing_excerpt",
                    title="2025 年年报",
                    date="2026-04-16",
                    snippet="年报显示营业收入 1688.38 亿元，归母净利润 823.2 亿元。",
                    url="https://example.com/annual-report",
                )
            ],
        ),
    }
    _, _, coverage = build_evidence_index(agent_results)
    _, chunks = build_documents_and_chunks(agent_results)
    memo = InvestmentMemo(
        company_name="贵州茅台",
        market="A_SHARE",
        instrument=InstrumentInfo(symbol="600519", display_name="贵州茅台", market="A_SHARE"),
        stance="bullish",
        stance_confidence=0.78,
        thesis="市场与披露都支持公司基本面仍具韧性。",
        bull_case=["近一月走势偏强。", "年报披露显示营收和利润具备韧性。"],
        bear_case=["估值已经不便宜。"],
        key_catalysts=["高比例分红可能继续支撑情绪。"],
        key_risks=["估值消化需要后续业绩继续兑现。"],
        valuation_view="PE 与 PB 仍处于较高水平，需要业绩继续消化估值。",
        market_snapshot=MarketSnapshot(last_price=1520.0, as_of="2026-04-16", provider="market-data-mcp"),
        watch_items=["跟踪下一次月度经营数据。"],
        limitations=[],
        agent_outputs={name: result.payload for name, result in agent_results.items()},
        events=[],
    )

    enriched = bind_citations_to_memo(memo, chunks, coverage)

    assert enriched.citations
    assert enriched.critic_summary is not None
    assert enriched.critic_summary.citation_coverage_score > 0
