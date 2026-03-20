from __future__ import annotations

from typing import Any

import pandas as pd

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

from app.config import get_settings
from app.routers import build_skipped_result, route_price
from app.schemas import CompanyIdentifiers, EvidenceCard, ModuleResult, PlannerOutput
from app.tools.base import PriceDataAdapter, ResolvedInstrument
from app.utils.logging import get_logger
from app.utils.text import normalize_name, truncate_text

logger = get_logger(__name__)


class YFinancePriceAdapter(PriceDataAdapter):
    # 中文注释：通过 Yahoo Finance 搜索公司名称，再拉取近期 K 线。
    def resolve(self, company_name: str) -> ResolvedInstrument | None:
        if yf is None:
            return None

        search = yf.Search(company_name, max_results=8, news_count=0, enable_fuzzy_query=True)
        quotes = getattr(search, "quotes", []) or []

        for quote in quotes:
            quote_type = str(quote.get("quoteType", "")).upper()
            if quote_type not in {"EQUITY", "ETF", "MUTUALFUND"}:
                continue

            symbol = quote.get("symbol")
            if not symbol:
                continue

            website_url = None
            exchange = quote.get("exchange") or quote.get("exchDisp")
            display_name = quote.get("shortname") or quote.get("longname") or symbol

            try:
                info = yf.Ticker(symbol).get_info()
                website_url = info.get("website")
                exchange = exchange or info.get("exchange")
            except Exception:
                logger.debug("Failed to fetch extra yfinance info for %s.", symbol)

            return ResolvedInstrument(
                symbol=symbol,
                display_name=display_name,
                market="US",
                website_url=website_url,
                exchange=exchange,
            )

        return None

    def fetch_recent_history(self, instrument: ResolvedInstrument, lookback_days: int) -> pd.DataFrame:
        if yf is None:
            raise RuntimeError("yfinance is not installed.")
        ticker = yf.Ticker(instrument.symbol)
        history = ticker.history(period=f"{max(lookback_days, 30)}d", interval="1d", auto_adjust=False)
        return history.tail(lookback_days)


class AksharePriceAdapter(PriceDataAdapter):
    # 中文注释：通过 A 股名称映射到代码，再抓取最近日线。
    def resolve(self, company_name: str) -> ResolvedInstrument | None:
        if ak is None:
            return None

        mapping_df = ak.stock_info_a_code_name()
        if mapping_df is None or mapping_df.empty:
            return None

        possible_name_cols = [col for col in mapping_df.columns if "name" in str(col).lower() or "名称" in str(col)]
        possible_code_cols = [col for col in mapping_df.columns if "code" in str(col).lower() or "代码" in str(col)]

        if not possible_name_cols or not possible_code_cols:
            return None

        name_col = possible_name_cols[0]
        code_col = possible_code_cols[0]
        target = normalize_name(company_name)

        best_row = None
        for _, row in mapping_df.iterrows():
            current_name = normalize_name(str(row[name_col]))
            if current_name == target:
                best_row = row
                break
            if target and target in current_name:
                best_row = row

        if best_row is None:
            return None

        raw_code = str(best_row[code_col]).zfill(6)
        symbol = f"sh{raw_code}" if raw_code.startswith(("5", "6", "9")) else f"sz{raw_code}"

        return ResolvedInstrument(
            symbol=symbol,
            display_name=str(best_row[name_col]),
            market="A_SHARE",
            exchange="A_SHARE",
        )

    def fetch_recent_history(self, instrument: ResolvedInstrument, lookback_days: int) -> pd.DataFrame:
        if ak is None:
            raise RuntimeError("akshare is not installed.")
        history = ak.stock_zh_a_hist_tx(
            symbol=instrument.symbol,
            start_date="19900101",
            end_date="20500101",
            adjust="qfq",
        )
        if history is None or history.empty:
            return pd.DataFrame()
        return history.tail(lookback_days)


def _detect_close_column(df: pd.DataFrame) -> str:
    for candidate in ["Close", "close", "收盘"]:
        if candidate in df.columns:
            return candidate
    raise KeyError("Close column not found.")


def _detect_volume_column(df: pd.DataFrame) -> str | None:
    for candidate in ["Volume", "volume", "成交量", "amount", "成交额"]:
        if candidate in df.columns:
            return candidate
    return None


def _normalize_date_value(index_or_value: Any) -> str | None:
    try:
        return pd.to_datetime(index_or_value).date().isoformat()
    except Exception:
        return None


def _compute_metrics(df: pd.DataFrame) -> dict[str, Any]:
    close_col = _detect_close_column(df)
    volume_col = _detect_volume_column(df)
    latest = df.iloc[-1]
    first = df.iloc[0]

    latest_close = float(latest[close_col])
    first_close = float(first[close_col])
    change_pct = None
    if first_close:
        change_pct = round((latest_close - first_close) / first_close * 100, 2)

    metrics: dict[str, Any] = {
        "latest_close": round(latest_close, 4),
        "period_change_pct": change_pct,
        "trading_days": int(len(df)),
        "latest_date": _normalize_date_value(df.index[-1] if hasattr(df.index, "__len__") else None),
    }

    if volume_col:
        try:
            metrics["latest_volume"] = float(latest[volume_col])
            metrics["average_volume"] = float(df[volume_col].tail(min(len(df), 20)).mean())
        except Exception:
            logger.debug("Failed to compute volume metrics.")

    return metrics


def _build_summary(instrument: ResolvedInstrument, metrics: dict[str, Any]) -> str:
    change_text = "n/a"
    if metrics.get("period_change_pct") is not None:
        change_text = f"{metrics['period_change_pct']}%"
    return (
        f"{instrument.display_name} ({instrument.symbol}) latest close was {metrics.get('latest_close')} "
        f"on {metrics.get('latest_date')}, with period change {change_text}."
    )


def _build_evidence(instrument: ResolvedInstrument, metrics: dict[str, Any]) -> list[EvidenceCard]:
    snippet = truncate_text(
        f"Instrument {instrument.symbol}; latest close {metrics.get('latest_close')}; "
        f"period change {metrics.get('period_change_pct')}%; "
        f"average volume {metrics.get('average_volume')}; latest volume {metrics.get('latest_volume')}.",
        max_chars=300,
    )
    return [
        EvidenceCard(
            module="price",
            source_type="market_data",
            title=f"Recent price snapshot for {instrument.display_name}",
            date=metrics.get("latest_date"),
            snippet=snippet,
            url=None,
        )
    ]


def run_price_module(
    company_name: str,
    planner_output: PlannerOutput,
    identifiers: CompanyIdentifiers,
    *,
    us_adapter: PriceDataAdapter | None = None,
    a_share_adapter: PriceDataAdapter | None = None,
) -> tuple[ModuleResult, CompanyIdentifiers]:
    decision = route_price(planner_output)
    if not decision.should_run:
        return build_skipped_result("price", decision.reason), identifiers

    settings = get_settings()
    us_adapter = us_adapter or YFinancePriceAdapter()
    a_share_adapter = a_share_adapter or AksharePriceAdapter()

    try:
        if planner_output.market == "US":
            adapter = us_adapter
        elif planner_output.market == "A_SHARE":
            adapter = a_share_adapter
        else:
            return build_skipped_result("price", f"Unsupported market {planner_output.market}."), identifiers

        instrument = adapter.resolve(company_name)
        if instrument is None:
            result = ModuleResult(
                module="price",
                applicable=True,
                status="partial",
                summary="Price module could not resolve a ticker or tradable symbol.",
                reason="Ticker resolution failed.",
                warning="Ticker could not be resolved from the supplied company name.",
            )
            return result, identifiers

        history_df = adapter.fetch_recent_history(instrument, settings.price_lookback_days)
        if history_df is None or history_df.empty:
            result = ModuleResult(
                module="price",
                applicable=True,
                status="partial",
                summary="Price module found a symbol but no recent trading history was returned.",
                reason="Price history is empty.",
                warning="No recent price history was returned by the price adapter.",
            )
            updated_identifiers = identifiers.model_copy(
                update={
                    "ticker": instrument.symbol,
                    "website_url": identifiers.website_url or instrument.website_url,
                    "exchange": identifiers.exchange or instrument.exchange,
                }
            )
            return result, updated_identifiers

        metrics = _compute_metrics(history_df)
        evidence = _build_evidence(instrument, metrics)
        summary = _build_summary(instrument, metrics)

        updated_identifiers = identifiers.model_copy(
            update={
                "ticker": instrument.symbol,
                "website_url": identifiers.website_url or instrument.website_url,
                "exchange": identifiers.exchange or instrument.exchange,
            }
        )

        result = ModuleResult(
            module="price",
            applicable=True,
            status="success",
            summary=summary,
            metrics=metrics,
            evidence=evidence,
        )
        return result, updated_identifiers
    except Exception as exc:
        logger.exception("Price module failed.")
        result = ModuleResult(
            module="price",
            applicable=True,
            status="failed",
            summary="Price module failed during execution.",
            error=str(exc),
            reason="Unexpected price module exception.",
        )
        return result, identifiers
