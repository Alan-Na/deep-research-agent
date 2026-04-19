from __future__ import annotations

from typing import Any

import pandas as pd

from app.agents.base import AgentDefinition, ToolDefinition
from app.config import get_settings
from app.schemas import (
    AgentResult,
    EvidenceItem,
    InstrumentInfo,
    MarketName,
    MarketReturns,
    MarketSnapshot,
    ResearchBrief,
    ValuationSnapshot,
    VolatilitySnapshot,
    VolumeSnapshot,
)
from app.services.market_ohlcv import load_or_refresh_ohlcv
from app.tools.price import AksharePriceAdapter, YFinancePriceAdapter
from app.utils.logging import get_logger
from app.utils.text import truncate_text

logger = get_logger(__name__)

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None


class LocalMarketDataMcpTransport:
    """Local MCP-style transport boundary for market data tools."""

    def __init__(self) -> None:
        self._a_share = AksharePriceAdapter()
        self._us = YFinancePriceAdapter()

    def resolve_instrument(self, company_name: str, market: MarketName) -> InstrumentInfo:
        adapter = self._a_share if market == "A_SHARE" else self._us
        try:
            instrument = adapter.resolve(company_name)
        except Exception:
            logger.exception("Instrument resolution failed for %s in market=%s.", company_name, market)
            instrument = None
        if instrument is None:
            return InstrumentInfo(display_name=company_name, market=market, notes=["Instrument resolution failed."])
        return InstrumentInfo(
            symbol=instrument.symbol.replace("sh", "").replace("sz", "") if market == "A_SHARE" else instrument.symbol,
            display_name=instrument.display_name,
            exchange=instrument.exchange,
            market=market,
            website_url=instrument.website_url,
        )

    def get_history(self, symbol: str, market: MarketName, lookback_days: int) -> pd.DataFrame:
        if market == "A_SHARE":
            if ak is None:
                raise RuntimeError("akshare is not installed.")
            return ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date="19900101",
                end_date="20500101",
                adjust="qfq",
            ).tail(lookback_days)
        instrument = self._us.resolve(symbol) if market == "US" else None
        if instrument is None:
            raise RuntimeError(f"Unable to resolve history instrument for {symbol}.")
        return self._us.fetch_recent_history(instrument, lookback_days)

    def get_company_profile(self, symbol: str, market: MarketName) -> dict[str, Any]:
        if market != "A_SHARE" or ak is None:
            return {}
        frame = ak.stock_individual_info_em(symbol=symbol)
        if frame is None or frame.empty:
            return {}
        profile = {str(row["item"]): row["value"] for _, row in frame.iterrows()}
        return {
            "latest": _to_float(profile.get("最新")),
            "market_cap": _to_float(profile.get("总市值")),
            "industry": str(profile.get("行业") or "") or None,
            "listed_at": _to_date(profile.get("上市时间")),
            "exchange": "SH" if str(symbol).startswith("6") else "SZ",
        }

    def get_financial_snapshot(self, symbol: str, market: MarketName) -> dict[str, Any]:
        if market != "A_SHARE" or ak is None:
            return {}
        frame = ak.stock_financial_abstract(symbol=symbol)
        if frame is None or frame.empty or "指标" not in frame.columns:
            return {}

        period_columns = [column for column in frame.columns if str(column).isdigit()]
        if not period_columns:
            return {}
        latest_period = sorted(period_columns)[-1]
        metric_map = {str(row["指标"]): row[latest_period] for _, row in frame.iterrows()}
        return {
            "period": latest_period,
            "revenue": _to_float(metric_map.get("营业总收入")),
            "net_income": _to_float(metric_map.get("归母净利润")),
            "operating_cash_flow": _to_float(metric_map.get("经营现金流量净额")),
            "eps_ttm": _to_float(metric_map.get("基本每股收益")),
            "book_value_per_share": _to_float(metric_map.get("每股净资产")),
        }


def market_agent_definition() -> AgentDefinition:
    transport = LocalMarketDataMcpTransport()
    return AgentDefinition(
        agent_name="market",
        description="Analyse instrument identity, price action, liquidity, volatility, and valuation snapshot.",
        enabled_capabilities=[
            "resolve_instrument",
            "load_price_history",
            "load_company_profile",
            "load_financial_snapshot",
        ],
        tool_registry={
            "resolve_instrument": ToolDefinition(
                name="resolve_instrument",
                description="Resolve the listed instrument identity for the research target.",
                handler=lambda brief, shared, scratchpad: _resolve_instrument(transport, brief, shared),
            ),
            "load_price_history": ToolDefinition(
                name="load_price_history",
                description="Fetch recent OHLCV history and compute return/liquidity/volatility features.",
                handler=lambda brief, shared, scratchpad: _load_price_history(transport, brief, scratchpad),
            ),
            "load_company_profile": ToolDefinition(
                name="load_company_profile",
                description="Fetch latest company profile and market-cap style metadata.",
                handler=lambda brief, shared, scratchpad: _load_company_profile(transport, brief, scratchpad),
            ),
            "load_financial_snapshot": ToolDefinition(
                name="load_financial_snapshot",
                description="Fetch headline financial metrics for valuation snapshot derivation.",
                handler=lambda brief, shared, scratchpad: _load_financial_snapshot(transport, brief, scratchpad),
            ),
        },
        output_model=MarketSnapshot,
        finalize_handler=_finalize_market_agent,
        timeout_seconds=get_settings().agent_timeout_seconds,
        max_steps=get_settings().agent_max_steps,
    )


def _resolve_instrument(
    transport: LocalMarketDataMcpTransport,
    brief: ResearchBrief,
    shared_context: dict[str, Any],
) -> dict[str, Any]:
    market = brief.market if brief.market != "UNKNOWN" else "A_SHARE"
    instrument = transport.resolve_instrument(brief.company_name, market)
    shared_context["instrument"] = instrument.model_dump()
    summary = f"Resolved instrument as {instrument.display_name or brief.company_name} ({instrument.symbol or 'unknown'})."
    return {
        "summary": summary,
        "payload": {"instrument": instrument.model_dump()},
        "metrics": {"market": instrument.market},
    }


def _load_price_history(
    transport: LocalMarketDataMcpTransport,
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    instrument = InstrumentInfo.model_validate(scratchpad.get("payload", {}).get("instrument") or brief.instrument.model_dump())
    if not instrument.symbol:
        return {"summary": "Skipped price history because instrument symbol is unavailable."}

    ohlcv_result = load_or_refresh_ohlcv(
        symbol=instrument.symbol,
        market=instrument.market,
        display_name=instrument.display_name or brief.company_name,
        exchange=instrument.exchange,
        lookback_days=get_settings().price_lookback_days,
    )
    history = ohlcv_result.frame
    if history is None or history.empty:
        return {"summary": "Price history returned no rows."}

    close_col = _pick_column(history, ["close", "收盘", "Close"])
    volume_col = _pick_column(history, ["volume", "成交量", "Volume"])
    high_col = _pick_column(history, ["high", "最高", "High"])
    low_col = _pick_column(history, ["low", "最低", "Low"])

    closes = history[close_col].astype(float)
    returns = closes.pct_change().dropna()
    latest_close = round(float(closes.iloc[-1]), 4)
    snapshot = MarketSnapshot(
        last_price=latest_close,
        returns=MarketReturns(
            one_day_pct=_pct_change(closes, 2),
            one_week_pct=_pct_change(closes, 6),
            one_month_pct=_pct_change(closes, 22),
            three_month_pct=_pct_change(closes, 66),
        ),
        volume=VolumeSnapshot(
            latest=float(history[volume_col].iloc[-1]) if volume_col else None,
            average_20d=float(history[volume_col].tail(min(20, len(history))).mean()) if volume_col else None,
        ),
        volatility=VolatilitySnapshot(
            realized_20d_pct=round(float(returns.tail(min(20, len(returns))).std() * (252 ** 0.5) * 100), 2)
            if not returns.empty
            else None,
            high_52w=round(float(history[high_col].tail(min(252, len(history))).max()), 4) if high_col else None,
            low_52w=round(float(history[low_col].tail(min(252, len(history))).min()), 4) if low_col else None,
        ),
        as_of=str(history.iloc[-1].get("date") or history.index[-1])[:10],
        provider="market-data-mcp",
    )
    evidence = EvidenceItem(
        agent_name="market",
        source_type="market_data",
        category="price_snapshot",
        title=f"{instrument.display_name or brief.company_name} 市场快照",
        date=snapshot.as_of,
        snippet=truncate_text(
            f"最新价 {snapshot.last_price}; 1周收益 {snapshot.returns.one_week_pct}; "
            f"20日波动率 {snapshot.volatility.realized_20d_pct}; 20日均量 {snapshot.volume.average_20d}.",
            300,
        ),
        metadata={"symbol": instrument.symbol, "provider": snapshot.provider, "cache_status": ohlcv_result.series.cache_status},
    )
    return {
        "summary": f"Loaded price history for {instrument.symbol} with {len(history)} rows.",
        "payload": {
            "market_snapshot": snapshot.model_dump(),
            "ohlcv_series": ohlcv_result.series.model_dump(),
        },
        "metrics": {
            "trading_days": len(history),
            "cache_status": ohlcv_result.series.cache_status,
            "fetched_rows": ohlcv_result.fetched_rows,
        },
        "evidence": [evidence.model_dump()],
    }


def _load_company_profile(
    transport: LocalMarketDataMcpTransport,
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    instrument = InstrumentInfo.model_validate(scratchpad.get("payload", {}).get("instrument") or brief.instrument.model_dump())
    if not instrument.symbol:
        return {"summary": "Skipped company profile because instrument symbol is unavailable."}
    profile = transport.get_company_profile(instrument.symbol, instrument.market)
    if not profile:
        return {"summary": "Company profile lookup returned no extra metadata."}
    notes = []
    if profile.get("industry"):
        notes.append(f"所属行业：{profile['industry']}")
    if profile.get("listed_at"):
        notes.append(f"上市日期：{profile['listed_at']}")
    return {
        "summary": f"Loaded market profile metadata for {instrument.symbol}.",
        "payload": {"profile": profile},
        "metrics": {"market_cap": profile.get("market_cap")},
        "evidence": [
            EvidenceItem(
                agent_name="market",
                source_type="market_profile",
                category="company_profile",
                title=f"{instrument.display_name or brief.company_name} 个股资料",
                date=None,
                snippet=truncate_text("；".join(notes) or f"总市值 {profile.get('market_cap')}", 260),
                metadata={"symbol": instrument.symbol},
            ).model_dump()
        ],
    }


def _load_financial_snapshot(
    transport: LocalMarketDataMcpTransport,
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    instrument = InstrumentInfo.model_validate(scratchpad.get("payload", {}).get("instrument") or brief.instrument.model_dump())
    if not instrument.symbol:
        return {"summary": "Skipped financial snapshot because instrument symbol is unavailable."}
    financials = transport.get_financial_snapshot(instrument.symbol, instrument.market)
    if not financials:
        return {"summary": "Financial snapshot returned no data."}
    market_snapshot = MarketSnapshot.model_validate(
        scratchpad.get("payload", {}).get("market_snapshot") or MarketSnapshot().model_dump()
    )
    profile = scratchpad.get("payload", {}).get("profile") or {}
    market_cap = _to_float(profile.get("market_cap"))
    eps = _to_float(financials.get("eps_ttm"))
    book_value = _to_float(financials.get("book_value_per_share"))
    pe = round(market_snapshot.last_price / eps, 2) if market_snapshot.last_price and eps else None
    pb = round(market_snapshot.last_price / book_value, 2) if market_snapshot.last_price and book_value else None
    valuation = ValuationSnapshot(
        market_cap=market_cap,
        pe_ttm=pe,
        pb=pb,
        eps_ttm=eps,
        book_value_per_share=book_value,
    )
    return {
        "summary": f"Loaded valuation inputs for {instrument.symbol} from latest financial abstract.",
        "payload": {"financial_snapshot": financials, "valuation": valuation.model_dump()},
        "metrics": {"valuation_period": financials.get("period")},
        "evidence": [
            EvidenceItem(
                agent_name="market",
                source_type="financial_abstract",
                category="valuation_snapshot",
                title=f"{instrument.display_name or brief.company_name} 估值快照",
                date=financials.get("period"),
                snippet=truncate_text(
                    f"营收 {financials.get('revenue')}; 归母净利润 {financials.get('net_income')}; "
                    f"EPS {valuation.eps_ttm}; PB {valuation.pb}; PE {valuation.pe_ttm}.",
                    280,
                ),
                metadata={"symbol": instrument.symbol},
            ).model_dump()
        ],
    }


def _finalize_market_agent(
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
    observations: list[Any],
) -> AgentResult:
    payload = dict(scratchpad.get("payload") or {})
    instrument = InstrumentInfo.model_validate(payload.get("instrument") or brief.instrument.model_dump())
    market_snapshot = MarketSnapshot.model_validate(payload.get("market_snapshot") or MarketSnapshot().model_dump())
    if payload.get("valuation"):
        market_snapshot = MarketSnapshot.model_validate(
            {**market_snapshot.model_dump(), "valuation": payload["valuation"]}
        )
    profile = payload.get("profile") or {}
    financials = payload.get("financial_snapshot") or {}

    if profile.get("industry") or profile.get("listed_at"):
        instrument = instrument.model_copy(
            update={
                "industry": profile.get("industry") or instrument.industry,
                "listed_at": profile.get("listed_at") or instrument.listed_at,
                "exchange": profile.get("exchange") or instrument.exchange,
            }
        )

    key_points = []
    if market_snapshot.last_price is not None:
        key_points.append(f"最新价 {market_snapshot.last_price}")
    if market_snapshot.returns.one_month_pct is not None:
        key_points.append(f"近1个月收益 {market_snapshot.returns.one_month_pct}%")
    if market_snapshot.volatility.realized_20d_pct is not None:
        key_points.append(f"20日实现波动率 {market_snapshot.volatility.realized_20d_pct}%")
    if market_snapshot.valuation.pe_ttm is not None or market_snapshot.valuation.pb is not None:
        key_points.append(
            f"估值快照 PE {market_snapshot.valuation.pe_ttm or 'n/a'} / PB {market_snapshot.valuation.pb or 'n/a'}"
        )

    signal = "neutral"
    one_month = market_snapshot.returns.one_month_pct or 0
    if one_month >= 10:
        signal = "positive"
    elif one_month <= -10:
        signal = "negative"

    status = "success" if instrument.symbol and market_snapshot.last_price is not None else "partial"
    summary = (
        f"{instrument.display_name or brief.company_name} 的市场画像已生成，"
        f"最新价 {market_snapshot.last_price or '未知'}，"
        f"近1个月收益 {market_snapshot.returns.one_month_pct or '未知'}%，"
        f"20日波动率 {market_snapshot.volatility.realized_20d_pct or '未知'}%。"
    )
    warning = None
    if market_snapshot.valuation.pe_ttm is None and market_snapshot.valuation.pb is None:
        warning = "Valuation snapshot is incomplete; the agent fell back to partial market evidence."
    if scratchpad.get("errors"):
        status = "partial"
        error_warning = " | ".join(str(item) for item in scratchpad["errors"][:2])
        warning = f"{warning + ' ' if warning else ''}Capability fallback triggered: {error_warning}"

    payload.update(
        {
            "instrument": instrument.model_dump(),
            "market_snapshot": market_snapshot.model_dump(),
            "signal_bias": signal,
            "financial_snapshot": financials,
        }
    )
    return AgentResult(
        agent_name="market",
        applicable=True,
        status=status,
        summary=summary,
        key_points=key_points,
        metrics={"instrument": instrument.model_dump()},
        payload=payload,
        evidence=[EvidenceItem.model_validate(item) for item in scratchpad.get("evidence", [])],
        observations=observations,
        warning=warning,
        reason="Instrument unresolved." if not instrument.symbol else None,
    )


def _pick_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) < periods:
        return None
    base = float(series.iloc[-periods])
    latest = float(series.iloc[-1])
    if not base:
        return None
    return round((latest - base) / base * 100, 2)


def _to_float(value: Any) -> float | None:
    try:
        if value in {"", None, "nan"}:
            return None
        return float(value)
    except Exception:
        return None


def _to_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw or None
