from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select

from app.config import get_settings
from app.db import get_db_session
from app.db.models import MarketOhlcvRecord
from app.schemas import InstrumentInfo, MarketName, OhlcvBar, OhlcvSeries
from app.utils.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


@dataclass
class MarketOhlcvLoadResult:
    series: OhlcvSeries
    frame: pd.DataFrame
    fetched_rows: int = 0


def load_or_refresh_ohlcv(
    *,
    symbol: str,
    market: MarketName,
    display_name: str | None = None,
    exchange: str | None = None,
    lookback_days: int | None = None,
    provider: str = "market-data-mcp",
) -> MarketOhlcvLoadResult:
    lookback_days = lookback_days or settings.price_lookback_days
    adjustment = _default_adjustment(market)

    cached_frame = _load_cached_frame(symbol=symbol, market=market, adjustment=adjustment, lookback_days=lookback_days)
    latest_cached_date = _latest_cached_date(cached_frame)
    today = datetime.now(timezone.utc).date()
    required_latest_trade_date = _required_latest_trade_date(today)

    needs_refresh = (
        cached_frame.empty
        or len(cached_frame) < lookback_days
        or latest_cached_date is None
        or latest_cached_date < required_latest_trade_date
    )

    cache_status = "hit"
    fetched_rows = 0
    if needs_refresh:
        refresh_start = _compute_refresh_start(latest_cached_date, lookback_days)
        try:
            fetched_frame = _fetch_provider_history(symbol=symbol, market=market, start_date=refresh_start, adjustment=adjustment)
            if not fetched_frame.empty:
                fetched_rows = _upsert_ohlcv_rows(
                    frame=fetched_frame,
                    symbol=symbol,
                    market=market,
                    display_name=display_name,
                    exchange=exchange,
                    adjustment=adjustment,
                    provider=provider,
                )
        except Exception:
            logger.exception("Failed to refresh OHLCV history for %s (%s).", symbol, market)
        cached_frame = _load_cached_frame(symbol=symbol, market=market, adjustment=adjustment, lookback_days=lookback_days)
        cache_status = "refresh" if not cached_frame.empty else "miss"
    elif not cached_frame.empty:
        cache_status = "hit"

    series = OhlcvSeries(
        symbol=symbol,
        market=market,
        exchange=exchange,
        display_name=display_name,
        adjustment=adjustment,
        provider=provider,
        cache_status=cache_status,  # type: ignore[arg-type]
        cached_until=_latest_cached_date(cached_frame).isoformat() if not cached_frame.empty else None,
        bars=_frame_to_bars(cached_frame),
    )
    return MarketOhlcvLoadResult(series=series, frame=cached_frame, fetched_rows=fetched_rows)


def get_job_market_ohlcv(job_id: str) -> tuple[str, InstrumentInfo, OhlcvSeries] | None:
    from app.db.models import AgentRunRecord, InvestmentJobRecord

    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if job is None:
            return None

        agent_run = session.scalar(
            select(AgentRunRecord).where(
                AgentRunRecord.job_id == job_id,
                AgentRunRecord.agent_name == "market",
            )
        )
        if agent_run is None:
            return None
        payload = dict(agent_run.payload or {})
        instrument_payload = payload.get("instrument") or {}
        instrument = InstrumentInfo.model_validate(
            {
                "display_name": job.company_name,
                "market": job.market,
                **instrument_payload,
            }
        )
        if not instrument.symbol:
            return None

    result = load_or_refresh_ohlcv(
        symbol=instrument.symbol,
        market=instrument.market,
        display_name=instrument.display_name or job.company_name,
        exchange=instrument.exchange,
        lookback_days=settings.price_lookback_days,
    )
    return job.company_name, instrument, result.series


def _default_adjustment(market: MarketName) -> str:
    return "qfq" if market == "A_SHARE" else "raw"


def _compute_refresh_start(latest_cached_date: date | None, lookback_days: int) -> date:
    if latest_cached_date is None:
        return datetime.now(timezone.utc).date() - timedelta(days=max(lookback_days * 3, 365))
    return latest_cached_date - timedelta(days=10)


def _required_latest_trade_date(today: date) -> date:
    weekday = today.weekday()
    if weekday == 0:
        return today - timedelta(days=3)
    if weekday == 6:
        return today - timedelta(days=2)
    return today - timedelta(days=1)


def _load_cached_frame(*, symbol: str, market: MarketName, adjustment: str, lookback_days: int) -> pd.DataFrame:
    with get_db_session() as session:
        rows = session.scalars(
            select(MarketOhlcvRecord)
            .where(
                MarketOhlcvRecord.symbol == symbol,
                MarketOhlcvRecord.market == market,
                MarketOhlcvRecord.adjustment == adjustment,
            )
            .order_by(MarketOhlcvRecord.trade_date.asc())
        ).all()

    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])

    tail_rows = rows[-lookback_days:]
    frame = pd.DataFrame(
        [
            {
                "date": row.trade_date.isoformat(),
                "open": row.open_price,
                "high": row.high_price,
                "low": row.low_price,
                "close": row.close_price,
                "volume": row.volume,
                "amount": row.amount,
            }
            for row in tail_rows
        ]
    )
    return frame


def _latest_cached_date(frame: pd.DataFrame) -> date | None:
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    try:
        return pd.to_datetime(frame["date"]).dt.date.max()
    except Exception:
        return None


def _fetch_provider_history(*, symbol: str, market: MarketName, start_date: date, adjustment: str) -> pd.DataFrame:
    if market == "A_SHARE":
        if ak is None:
            return pd.DataFrame()
        end_date = (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y%m%d")
        history = None
        primary_error = None
        try:
            history = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date,
                adjust=adjustment,
            )
        except Exception as exc:
            primary_error = exc
            logger.warning("Primary A-share OHLCV source failed for %s: %s", symbol, exc)

        if history is None or getattr(history, "empty", True):
            prefixed_symbol = _a_share_prefixed_symbol(symbol)
            try:
                history = ak.stock_zh_a_hist_tx(
                    symbol=prefixed_symbol,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date,
                    adjust=adjustment,
                )
            except Exception:
                if primary_error is not None:
                    raise primary_error
                raise
    else:
        if yf is None:
            return pd.DataFrame()
        history = yf.Ticker(symbol).history(
            start=start_date.isoformat(),
            end=(datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
        )
    return _normalize_history_frame(history)


def _normalize_history_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])

    normalized = frame.copy()
    normalized = normalized.reset_index(drop=False)
    date_series = None
    if "日期" in normalized.columns:
        date_series = pd.to_datetime(normalized["日期"], errors="coerce")
    elif "Date" in normalized.columns:
        date_series = pd.to_datetime(normalized["Date"], errors="coerce")
    else:
        try:
            date_series = pd.to_datetime(normalized.index, errors="coerce")
        except Exception:
            date_series = pd.Series(dtype="datetime64[ns]")

    if isinstance(date_series, pd.DatetimeIndex):
        date_values = pd.Series(date_series.date).reset_index(drop=True)
    else:
        date_values = pd.to_datetime(date_series, errors="coerce").dt.date.reset_index(drop=True)

    mapping = {
        "open": _pick_column(normalized, ["开盘", "Open", "open"]),
        "high": _pick_column(normalized, ["最高", "High", "high"]),
        "low": _pick_column(normalized, ["最低", "Low", "low"]),
        "close": _pick_column(normalized, ["收盘", "Close", "close"]),
        "volume": _pick_column(normalized, ["成交量", "Volume", "volume"]),
        "amount": _pick_column(normalized, ["成交额", "Amount", "amount"]),
    }
    result = pd.DataFrame({"date": date_values})
    for target, source in mapping.items():
        result[target] = pd.to_numeric(normalized[source], errors="coerce").reset_index(drop=True) if source else None

    result = result.dropna(subset=["date", "open", "high", "low", "close"])
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return result.reset_index(drop=True)


def _pick_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _a_share_prefixed_symbol(symbol: str) -> str:
    raw = str(symbol or "").replace("sh", "").replace("sz", "").strip()
    if raw.startswith(("5", "6", "9")):
        return f"sh{raw}"
    return f"sz{raw}"


def _upsert_ohlcv_rows(
    *,
    frame: pd.DataFrame,
    symbol: str,
    market: MarketName,
    display_name: str | None,
    exchange: str | None,
    adjustment: str,
    provider: str,
) -> int:
    if frame.empty:
        return 0

    written = 0
    with get_db_session() as session:
        rows_by_date = {
            row.trade_date: row
            for row in session.scalars(
                select(MarketOhlcvRecord).where(
                    MarketOhlcvRecord.symbol == symbol,
                    MarketOhlcvRecord.market == market,
                    MarketOhlcvRecord.adjustment == adjustment,
                )
            ).all()
        }
        for bar in frame.to_dict(orient="records"):
            trade_date = bar["date"]
            if pd.isna(trade_date):
                continue
            if isinstance(trade_date, pd.Timestamp):
                trade_date = trade_date.date()
            if isinstance(trade_date, datetime):
                trade_date = trade_date.date()
            existing = rows_by_date.get(trade_date)
            values = {
                "exchange": exchange,
                "display_name": display_name,
                "provider": provider,
                "open_price": float(bar["open"]),
                "high_price": float(bar["high"]),
                "low_price": float(bar["low"]),
                "close_price": float(bar["close"]),
                "volume": _to_float(bar.get("volume")),
                "amount": _to_float(bar.get("amount")),
            }
            if existing is None:
                session.add(
                    MarketOhlcvRecord(
                        market=market,
                        symbol=symbol,
                        trade_date=trade_date,
                        adjustment=adjustment,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            written += 1
    return written


def _frame_to_bars(frame: pd.DataFrame) -> list[OhlcvBar]:
    if frame.empty:
        return []
    bars: list[OhlcvBar] = []
    for row in frame.to_dict(orient="records"):
        bars.append(
            OhlcvBar(
                date=str(row["date"]),
                open=round(float(row["open"]), 4),
                high=round(float(row["high"]), 4),
                low=round(float(row["low"]), 4),
                close=round(float(row["close"]), 4),
                volume=_to_float(row.get("volume")),
                amount=_to_float(row.get("amount")),
            )
        )
    return bars


def _to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None
