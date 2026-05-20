import pandas as pd

from app.services.market_ohlcv import _compute_refresh_start, _frame_to_bars, _normalize_history_frame


def test_frame_to_bars_skips_rows_with_missing_ohlc():
    frame = pd.DataFrame(
        [
            {"date": "2026-05-11", "open": 18.9, "high": 19.27, "low": 17.6, "close": 18.41, "volume": 1732519},
            {"date": "2026-05-12", "open": None, "high": 18.2, "low": 17.05, "close": 17.3, "volume": 827124},
        ]
    )

    bars = _frame_to_bars(frame)

    assert len(bars) == 1
    assert bars[0].date == "2026-05-11"
    assert bars[0].close == 18.41


def test_normalize_history_frame_drops_invalid_ohlc_rows():
    frame = pd.DataFrame(
        [
            {"日期": "2026-05-11", "开盘": "18.90", "最高": "19.27", "最低": "17.60", "收盘": "18.41", "成交量": "1732519"},
            {"日期": "2026-05-12", "开盘": "-", "最高": "18.20", "最低": "17.05", "收盘": "17.30", "成交量": "827124"},
        ]
    )

    normalized = _normalize_history_frame(frame)

    assert len(normalized) == 1
    assert normalized.iloc[0]["date"].isoformat() == "2026-05-11"
    assert normalized.iloc[0]["close"] == 18.41


def test_normalize_history_frame_uses_lowercase_date_column():
    frame = pd.DataFrame(
        [
            {"date": "2026-05-11", "open": 18.90, "high": 19.27, "low": 17.60, "close": 18.41, "volume": 1732519},
        ]
    )

    normalized = _normalize_history_frame(frame)

    assert len(normalized) == 1
    assert normalized.iloc[0]["date"].isoformat() == "2026-05-11"


def test_compute_refresh_start_ignores_tiny_stale_cache():
    refresh_start = _compute_refresh_start(pd.Timestamp("1970-01-01").date(), lookback_days=90, cached_count=1)

    assert refresh_start.year >= 2025
