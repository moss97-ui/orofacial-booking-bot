"""Time helpers. The clinic works in Yerevan time (UTC+4, no daylight saving).

All internal times are epoch milliseconds, the same as in the original n8n code,
so the booking arithmetic stays identical.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

OFFSET = "+04:00"
TZ = timezone(timedelta(hours=4))
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000

_fixed_now: int | None = None


def now_ms() -> int:
    return _fixed_now if _fixed_now is not None else int(time.time() * 1000)


def set_now(ms: int | None) -> None:
    """Freeze the clock (tests only). Pass None to use the real time again."""
    global _fixed_now
    _fixed_now = ms


def parse_ms(value) -> int | None:
    """ISO date-time ('2026-10-23T09:00:00+04:00' or '...Z') -> epoch ms, or None."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def at(day: str, hm: str) -> int | None:
    """'2026-10-23', '09:00' -> epoch ms in clinic time."""
    return parse_ms(f"{day}T{hm}:00{OFFSET}")


def ymd(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d")


def hhmm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%H:%M")


def iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def local_stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M")


def weekday(day: str) -> int:
    """JavaScript-style weekday: Sunday = 0 ... Saturday = 6."""
    return (date.fromisoformat(day).weekday() + 1) % 7


def valid_date(day: str) -> bool:
    try:
        return date.fromisoformat(day).isoformat() == day
    except ValueError:
        return False


def add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def start_of_day_iso(ms: int) -> str:
    return f"{ymd(ms)}T00:00:00{OFFSET}"


def start_of_month_plus(ms: int, months: int) -> str:
    d = datetime.fromtimestamp(ms / 1000, TZ)
    m0 = d.month - 1 + months
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return f"{y:04d}-{m:02d}-01T00:00:00{OFFSET}"
