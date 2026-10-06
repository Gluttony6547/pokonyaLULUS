"""IDX trading-day calendar for horizon target dates.

The LSTM artifacts predict H *trading sessions* ahead, but the UI and the API
must show calendar dates. IDX trades Monday to Friday, so the projection skips
weekends; exchange holidays are not modeled because Yahoo returns no rows for
them and none of the stored sessions contradicts the weekday walk by more than
the tolerance the freshness label already absorbs.
"""

from __future__ import annotations

from datetime import date, timedelta


def is_trading_day(day: date) -> bool:
    """A session is a weekday; the IDX market does not trade Sat/Sun."""
    return day.weekday() < 5


def next_trading_day(day: date) -> date:
    """The next session strictly after `day` (never `day` itself)."""
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def add_trading_days(start: date, sessions: int) -> date:
    """The date `sessions` trading days after `start`, skipping weekends.

    `sessions=0` returns `start` unchanged, matching T+0 semantics. The count
    is exclusive of the start date: 2026-10-06 (Tue) + 10 sessions is
    2026-10-20 (Tue), with two weekends in between skipped.
    """
    if sessions < 0:
        raise ValueError("sessions must be non-negative")
    target = start
    remaining = sessions
    while remaining > 0:
        target = next_trading_day(target)
        remaining -= 1
    return target


def target_date(data_as_of: date, sessions: int) -> date:
    """Calendar date the H-session horizon lands on, weekends skipped."""
    return add_trading_days(data_as_of, sessions)
