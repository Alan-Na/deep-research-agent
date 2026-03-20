from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    # 中文注释：统一使用 UTC，便于跨数据源比较时间。
    return datetime.now(UTC)


def days_ago_iso(days: int) -> str:
    return (utc_now() - timedelta(days=days)).date().isoformat()


def safe_parse_date(value: str | None) -> datetime | None:
    # 中文注释：兼容常见 ISO 时间格式。
    if not value:
        return None

    candidate = value.strip()
    candidate = candidate.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(candidate[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC)


def is_recent(date_value: str | None, threshold_days: int) -> bool:
    parsed = safe_parse_date(date_value)
    if parsed is None:
        return False
    return parsed >= utc_now() - timedelta(days=threshold_days)
