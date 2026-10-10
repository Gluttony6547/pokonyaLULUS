"""IDX trading-day calendar for horizon target dates.

The LSTM artifacts predict H *trading sessions* ahead, but the UI and the API
show calendar dates, so the projection walks only real IDX sessions. The
exchange holiday lists below come from IDX's own Trading Holiday Calendar
(announcement series Peng-00169/BEI.POP); religious dates are initial variants
that IDX occasionally adjusts, so holidays_for_year() treats every year outside
HOLIDAYS as unknown and never invents dates for it.
"""

from __future__ import annotations

from datetime import date, timedelta

# Weekday-only holiday tables (Sat/Sun closures are already covered by the
# weekend rule and would be redundant, and the freshness checks compare dates
# that Yahoo prices on, so only weekday sessions matter here).
HOLIDAYS: dict[int, frozenset[date]] = {
    2026: frozenset({
        date(2026, 1, 1),   # New Year
        date(2026, 1, 16),  # Isra Mikraj
        date(2026, 2, 16),  # Chinese New Year (joint leave schedule)
        date(2026, 2, 17),  # Chinese New Year
        date(2026, 3, 18),  # Nyepi
        date(2026, 3, 19),  # Nyepi (joint leave schedule)
        date(2026, 3, 20),  # Eid al-Fitr day 1
        date(2026, 3, 23),  # Eid al-Fitr day 2
        date(2026, 3, 24),  # Eid al-Fitr (joint leave schedule)
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 1),   # Labour Day
        date(2026, 5, 14),  # Ascension
        date(2026, 5, 27),  # Eid al-Adha
        date(2026, 5, 28),  # Eid al-Adha (holiday)
        date(2026, 6, 1),   # Pancasila Day
        date(2026, 6, 16),  # Islamic New Year
        date(2026, 8, 17),  # Independence Day
        date(2026, 8, 25),  # Mawlid
        date(2026, 12, 24), # Christmas (joint leave schedule)
        date(2026, 12, 25), # Christmas
        date(2026, 12, 31), # New Year's Eve (market holiday)
    }),
    2027: frozenset({
        date(2027, 1, 1),   # New Year
        date(2027, 1, 5),   # Isra Mikraj
        date(2027, 2, 5),   # Chinese New Year (joint leave schedule)
        date(2027, 3, 9),   # Nyepi
        date(2027, 3, 10),  # Eid al-Fitr day 1
        date(2027, 3, 11),  # Eid al-Fitr day 2
        date(2027, 3, 12),  # Eid al-Fitr (joint leave schedule)
        date(2027, 3, 26),  # Good Friday
        date(2027, 5, 6),   # Ascension
        date(2027, 5, 17),  # Eid al-Adha
        date(2027, 5, 18),  # Eid al-Adha (holiday)
        date(2027, 5, 20),  # Waisak
        date(2027, 6, 1),   # Pancasila Day
        date(2027, 8, 17),  # Independence Day
        date(2027, 12, 31), # New Year's Eve (market holiday)
    }),
}

UNKNOWN_HOLIDAYS = None  # a year absent from HOLIDAYS resolves to this


def holidays_for_year(year: int) -> frozenset[date] | None:
    """The weekday IDX holidays for a known year, else None for unknown years."""
    return HOLIDAYS.get(year)


def is_trading_day(day: date) -> bool:
    """A weekday that is not an IDX exchange holiday."""
    if day.weekday() >= 5:
        return False
    year_holidays = holidays_for_year(day.year)
    return year_holidays is None or day not in year_holidays


def next_trading_day(day: date) -> date:
    """The next session strictly after `day` (never `day` itself)."""
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def add_trading_days(start: date, sessions: int) -> date:
    """The date `sessions` real IDX sessions after `start`.

    `sessions=0` returns `start` unchanged, matching T+0 semantics. The count
    is exclusive of the start date: 2026-10-06 (Tue) + 10 sessions is
    2026-10-20 (Tue), with two weekends in between skipped. Holidays inside
    the window are skipped the same way, and a target in an unknown future
    year walks weekends only (never lands on a weekend).
    """
    if sessions < 0:
        raise ValueError("sessions must be non-negative")
    target = start
    remaining = sessions
    while remaining > 0:
        target = next_trading_day(target)
        remaining -= 1
    return target


def lands_on_unverified_session(start: date, sessions: int) -> bool:
    """True when the walk crosses a year with no holiday table.

    Such a target is an estimate, not a verified IDX session date: the caller
    should present it as approximate rather than final.
    """
    target = add_trading_days(start, sessions)
    return any(holidays_for_year(year) is None for year in range(start.year, target.year + 1))


def target_date(data_as_of: date, sessions: int) -> date:
    """Calendar date the H-session horizon lands on, weekends and IDX holidays skipped."""
    return add_trading_days(data_as_of, sessions)
