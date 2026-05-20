from datetime import date, timedelta

import pandas as pd

from app.agents import market
from app.agents.runtime import execute_react_agent
from app.schemas import InstrumentInfo, OhlcvSeries, ResearchBrief
from app.services.market_ohlcv import MarketOhlcvLoadResult


def test_market_agent_soft_fails_optional_profile_provider(monkeypatch):
    def fake_resolve(self, company_name, market_name):
        return InstrumentInfo(symbol="600519", display_name="贵州茅台", exchange="SH", market="A_SHARE")

    def fake_profile(self, symbol, market_name):
        raise RuntimeError("HTTPSConnectionPool ProxyError Remote end closed connection without response")

    def fake_financial_snapshot(self, symbol, market_name):
        return {}

    def fake_ohlcv(**kwargs):
        start = date(2026, 4, 1)
        rows = []
        for index in range(30):
            close = 100 + index
            rows.append(
                {
                    "date": (start + timedelta(days=index)).isoformat(),
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "volume": 100000 + index,
                    "amount": 1000000 + index,
                }
            )
        return MarketOhlcvLoadResult(
            series=OhlcvSeries(
                symbol=kwargs["symbol"],
                market=kwargs["market"],
                exchange=kwargs.get("exchange"),
                display_name=kwargs.get("display_name"),
                adjustment="qfq",
                cache_status="hit",
                cached_until=rows[-1]["date"],
                bars=[],
            ),
            frame=pd.DataFrame(rows),
            fetched_rows=0,
        )

    monkeypatch.setattr(market.LocalMarketDataMcpTransport, "resolve_instrument", fake_resolve)
    monkeypatch.setattr(market.LocalMarketDataMcpTransport, "get_company_profile", fake_profile)
    monkeypatch.setattr(market.LocalMarketDataMcpTransport, "get_financial_snapshot", fake_financial_snapshot)
    monkeypatch.setattr(market, "load_or_refresh_ohlcv", fake_ohlcv)

    result = execute_react_agent(
        market.market_agent_definition(),
        ResearchBrief(company_name="贵州茅台", market="A_SHARE", query="贵州茅台"),
        {},
    )

    assert result.status == "success"
    assert result.payload["market_snapshot"]["last_price"] == 129
    assert result.payload["provider_warnings"]
    assert "Company profile provider unavailable" in (result.warning or "")
    assert "Capability fallback triggered" not in (result.warning or "")
    assert "HTTPSConnectionPool" not in (result.warning or "")


def test_market_agent_converts_nan_volume_to_null(monkeypatch):
    def fake_resolve(self, company_name, market_name):
        return InstrumentInfo(symbol="600900", display_name="长江电力", exchange="SH", market="A_SHARE")

    def fake_profile(self, symbol, market_name):
        return {}

    def fake_financial_snapshot(self, symbol, market_name):
        return {}

    rows = []
    start = date(2026, 2, 1)
    for index in range(90):
        close = 25 + index * 0.01
        rows.append(
            {
                "date": (start + timedelta(days=index)).isoformat(),
                "open": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": float("nan"),
                "amount": None,
            }
        )

    def fake_ohlcv(**kwargs):
        return MarketOhlcvLoadResult(
            series=OhlcvSeries(
                symbol=kwargs["symbol"],
                market=kwargs["market"],
                exchange=kwargs.get("exchange"),
                display_name=kwargs.get("display_name"),
                adjustment="qfq",
                cache_status="hit",
                cached_until=rows[-1]["date"],
                bars=[],
            ),
            frame=pd.DataFrame(rows),
            fetched_rows=0,
        )

    monkeypatch.setattr(market.LocalMarketDataMcpTransport, "resolve_instrument", fake_resolve)
    monkeypatch.setattr(market.LocalMarketDataMcpTransport, "get_company_profile", fake_profile)
    monkeypatch.setattr(market.LocalMarketDataMcpTransport, "get_financial_snapshot", fake_financial_snapshot)
    monkeypatch.setattr(market, "load_or_refresh_ohlcv", fake_ohlcv)

    result = execute_react_agent(
        market.market_agent_definition(),
        ResearchBrief(company_name="长江电力", market="A_SHARE", query="长江电力"),
        {},
    )

    snapshot = result.payload["market_snapshot"]
    assert result.status == "success"
    assert snapshot["volume"]["latest"] is None
    assert snapshot["volume"]["average_20d"] is None
