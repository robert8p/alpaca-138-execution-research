from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def decision_timestamp(trade_date: date) -> datetime:
    return datetime.combine(trade_date, time(17, 0), tzinfo=LONDON).astimezone(UTC)


def alpaca_session_timestamp(trade_date: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(trade_date, time(hour, minute), tzinfo=NEW_YORK).astimezone(UTC)


def time_exit_timestamp(trade_date: date) -> datetime:
    return datetime.combine(trade_date, time(15, 55), tzinfo=NEW_YORK).astimezone(UTC)
