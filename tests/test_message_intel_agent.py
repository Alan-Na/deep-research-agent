from types import SimpleNamespace

from app.agents import message_intel as mi
from app.agents.runtime import execute_react_agent
from app.schemas import InstrumentInfo, NewsSignalAnalysis, ResearchBrief
from app.tools.base import WebsitePageRecord


def _brief() -> ResearchBrief:
    return ResearchBrief(
        company_name="宁德时代",
        market="A_SHARE",
        query="宁德时代",
        instrument=InstrumentInfo(symbol="300750", market="A_SHARE", display_name="宁德时代新能源科技股份有限公司"),
    )


def test_entity_aliases_filter_company_articles():
    aliases = mi._build_entity_aliases(_brief())
    articles = [
        {"title": "宁德时代签订储能合同", "summary": "", "content": "宁德时代订单增长", "url": "1"},
        {"title": "300750公告回购进展", "summary": "", "content": "公司回购金额达5亿元", "url": "2"},
        {"title": "锂电行业景气度回升", "summary": "", "content": "行业整体需求改善", "url": "3"},
    ]

    linked = mi._filter_company_articles(articles, aliases)

    assert "宁德时代" in aliases
    assert "300750" in aliases
    assert [item["url"] for item in linked] == ["1", "2"]


def test_simhash_clusters_reposts_and_keeps_longest_representative():
    articles = [
        {
            "title": "宁德时代签订200亿元合同",
            "summary": "宁德时代签订200亿元合同",
            "content": "宁德时代签订200亿元合同。",
            "source": "A",
            "url": "a",
            "date": "2026-05-10",
        },
        {
            "title": "宁德时代签订200亿元合同",
            "summary": "宁德时代签订200亿元合同",
            "content": "宁德时代签订200亿元合同，期限3年，供应磷酸铁锂电池。",
            "source": "B",
            "url": "b",
            "date": "2026-05-10",
        },
        {
            "title": "宁德时代收到监管处罚",
            "summary": "宁德时代收到监管处罚",
            "content": "宁德时代因信息披露问题收到监管处罚。",
            "source": "C",
            "url": "c",
            "date": "2026-05-11",
        },
    ]

    clusters = mi._cluster_articles(articles)
    duplicate_cluster = next(item for item in clusters if len(item["items"]) == 2)

    assert len(clusters) == 2
    assert duplicate_cluster["representative"]["url"] == "b"
    assert duplicate_cluster["sources"] == ["A", "B"]


def test_event_classification_keyword_tree():
    cases = {
        "宁德时代净利润增长，营收创新高": "earnings",
        "宁德时代签订200亿元订单合同": "contract_order",
        "宁德时代股东计划减持股份": "shareholder_change",
        "宁德时代收到监管处罚": "regulatory_penalty",
        "宁德时代发布新产品平台": "product_release",
        "宁德时代参加行业论坛": "other",
    }

    for text, expected in cases.items():
        category, _ = mi._classify_news_category(text)
        assert category == expected


def test_metric_extraction_keeps_raw_numbers_and_infers_names():
    text = "宁德时代签订200亿元合同，供应期限3年；净利润下降20%，交付3000辆。"

    metrics = mi._extract_news_metrics(text)
    by_raw = {item.raw_text: item for item in metrics}

    assert by_raw["200亿元"].name == "订单金额"
    assert by_raw["3年"].name == "供应期限"
    assert by_raw["20%"].name == "净利润"
    assert by_raw["3000辆"].name == "销量"


def test_sentiment_uses_rule_fallback_without_finbert():
    sentiment, score, probs, method, warning = mi._analyze_sentiment("宁德时代中标重大订单，增长超预期，利好。")

    assert sentiment == "positive"
    assert score > 0.6
    assert probs["positive"] == score
    assert method == "rule_fallback"
    assert warning is None


def test_sentiment_uses_mock_finbert_when_enabled(monkeypatch):
    monkeypatch.setattr(mi, "get_settings", lambda: SimpleNamespace(enable_finbert_sentiment=True, finbert_max_chars=512))
    monkeypatch.setattr(mi, "_run_finbert", lambda text: ("negative", 0.88, {"positive": 0.01, "neutral": 0.11, "negative": 0.88}))

    sentiment, score, probs, method, warning = mi._analyze_sentiment("宁德时代收到处罚。")

    assert sentiment == "negative"
    assert score == 0.88
    assert probs["negative"] == 0.88
    assert method == "finbert_chinese"
    assert warning is None


def test_message_intel_agent_runs_structured_news_and_website_pipeline(monkeypatch):
    monkeypatch.setattr(
        mi.DefaultWebsiteDiscoveryAdapter,
        "discover",
        lambda self, company_name, hints: "https://example.com",
    )
    monkeypatch.setattr(
        mi.RequestsWebsiteCrawler,
        "crawl",
        lambda self, base_url, max_pages=4: [
            WebsitePageRecord(
                title="宁德时代官网",
                url="https://example.com",
                text="宁德时代 产品 电池 储能 投资者关系 公司定位全球新能源创新。",
            )
        ],
    )
    monkeypatch.setattr(
        mi,
        "_fetch_news_articles",
        lambda brief, warnings: [
            {
                "title": "宁德时代签订200亿元合同",
                "summary": "宁德时代签订200亿元合同，期限3年。",
                "content": "宁德时代签订200亿元合同，期限3年，增长超预期。",
                "date": "2026-05-10T10:30:00Z",
                "source": "SourceA",
                "url": "https://news.example/a",
            },
            {
                "title": "宁德时代签订200亿元合同",
                "summary": "宁德时代签订200亿元合同，期限3年。",
                "content": "宁德时代签订200亿元合同，期限3年，增长超预期，供应储能电池。",
                "date": "2026-05-10T10:35:00Z",
                "source": "SourceB",
                "url": "https://news.example/b",
            },
            {
                "title": "锂电行业景气回升",
                "summary": "行业需求改善。",
                "content": "行业需求改善。",
                "date": "2026-05-10T12:00:00Z",
                "source": "SourceC",
                "url": "https://news.example/c",
            },
        ],
    )
    brief = _brief()

    result = execute_react_agent(mi.message_intel_agent_definition(), brief, {"research_brief": brief.model_dump()})
    analysis = NewsSignalAnalysis.model_validate(result.payload["news_signal_analysis"])

    assert result.agent_name == "message_intel"
    assert result.tool_calls_count == 3
    assert result.status in {"success", "partial"}
    assert analysis.raw_article_count == 3
    assert analysis.deduped_event_count == 1
    assert analysis.events[0].category == "contract_order"
    assert analysis.events[0].duplicate_count == 2
    assert result.payload["events"]
    assert result.payload["signal_bias"] == "positive"
    assert {item.category for item in result.evidence} >= {"news_signal_event", "news_sentiment_signal", "news_metric_extract"}
