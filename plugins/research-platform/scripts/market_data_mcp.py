from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.agents.market import LocalMarketDataMcpTransport
from app.schemas import MarketSnapshot

transport = LocalMarketDataMcpTransport()
mcp = FastMCP("Market Data MCP", json_response=True)


@mcp.tool()
def resolve_instrument(company_name: str, market: str = "A_SHARE") -> dict[str, Any]:
    """Resolve a tradable instrument and return its normalized identity schema."""
    return transport.resolve_instrument(company_name, market).model_dump()


@mcp.tool()
def get_market_snapshot(symbol: str, market: str = "A_SHARE", lookback_days: int = 90) -> dict[str, Any]:
    """Return a unified market snapshot with returns, liquidity, volatility, and valuation context."""
    instrument = transport.resolve_instrument(symbol, market)
    history = transport.get_history(instrument.symbol or symbol, market, lookback_days)
    profile = transport.get_company_profile(instrument.symbol or symbol, market)
    financials = transport.get_financial_snapshot(instrument.symbol or symbol, market)
    snapshot = MarketSnapshot(
        last_price=float(history.iloc[-1].get("收盘") or history.iloc[-1].get("Close")) if not history.empty else None,
        as_of=str(history.iloc[-1].get("日期") or history.index[-1])[:10] if not history.empty else None,
        provider="market-data-mcp",
    )
    return {
        "instrument": instrument.model_dump(),
        "snapshot": snapshot.model_dump(),
        "profile": profile,
        "financial_snapshot": financials,
    }


if __name__ == "__main__":
    mcp.run(transport=os.getenv("MARKET_DATA_MCP_TRANSPORT", "stdio"))
