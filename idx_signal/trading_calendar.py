"""IDX trading-day arithmetic for horizon target dates.

The saved artifacts predict H *trading sessions* ahead, while the interface
shows calendar dates, so the projection walks real sessions. The holiday table
lives in the database (`market_holidays`) so a policy change is a data update
rather than a code change. A year with no rows at all is treated as unknown:
the walk then skips weekends only and the caller labels the date approximate
instead of presenting a guess as a verified session.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MarketHoliday


def load_holidays(session: Session) -> tuple[frozenset[date], frozenset[int]]:
    """Every non-trading weekday on record, plus the years those records cover."""
    rows = session.scalars(select(MarketHoliday.holiday_date)).all()
    holidays = frozenset(day for day in rows if day.weekday() < 5)
    years = frozenset(day.year for day in holidays)
    return holidays, years


@lru_cache(maxsize=1)
def _seed_holidays() -> frozenset[date]:
    """Fallback used when no database is reachable (tests, first boot)."""
    from .seed import MARKET_HOLIDAYS

    return frozenset(MARKET_HOLIDAYS)


def is_trading_day(day: date, holidays: frozenset[date] | None = None) -> bool:
    known = _seed_holidays() if holidays is None else holidays
    if day.weekday() >= 5:
        return False
    return day not in known


def add_trading_days(
    start: date, sessions: int, holidays: frozenset[date] | None = None
) -> date:
    """The date `sessions` IDX sessions after `start` (exclusive of `start`)."""
    if sessions < 0:
        raise ValueError("sessions must be non-negative")
    known = _seed_holidays() if holidays is None else holidays
    target = start
    for _ in range(sessions):
        target += timedelta(days=1)
        while not is_trading_day(target, known):
            target += timedelta(days=1)
    return target


def target_date(
    data_as_of: date, sessions: int, holidays: frozenset[date] | None = None
) -> date:
    """Calendar date the H-session horizon lands on, weekends and holidays skipped."""
    return add_trading_days(data_as_of, sessions, holidays)


def crosses_unknown_year(
    start: date, sessions: int, known_years: frozenset[int] | None = None
) -> bool:
    """True when the walk leaves the years the holiday table covers."""
    if known_years is None:
        return False
    finish = add_trading_days(start, sessions)
    return any(year not in known_years for year in range(start.year, finish.year + 1))
