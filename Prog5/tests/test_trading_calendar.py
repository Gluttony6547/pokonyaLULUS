from __future__ import annotations

from datetime import date

import pytest

from prog5.trading_calendar import (
    HOLIDAYS,
    add_trading_days,
    holidays_for_year,
    is_trading_day,
    lands_on_unverified_session,
    next_trading_day,
    target_date,
)


def test_user_example_oct_6_plus_10_sessions_is_oct_20():
    # Tuesday 2026-10-06 + 10 sessions: no holidays inside (next IDX holiday
    # is Dec 24), so two weekends in between and it ends Tue 2026-10-20.
    assert target_date(date(2026, 10, 6), 10) == date(2026, 10, 20)


def test_horizons_from_a_tuesday():
    start = date(2026, 10, 6)
    assert target_date(start, 1) == date(2026, 10, 7)
    assert target_date(start, 5) == date(2026, 10, 13)
    assert target_date(start, 20) == date(2026, 11, 3)


def test_friday_plus_one_is_monday():
    friday = date(2026, 10, 9)
    assert target_date(friday, 1) == date(2026, 10, 12)


def test_friday_plus_five_lands_on_the_next_friday():
    friday = date(2026, 10, 9)
    assert target_date(friday, 5) == date(2026, 10, 16)


def test_zero_sessions_is_the_start_date():
    start = date(2026, 10, 6)
    assert target_date(start, 0) == start


def test_negative_sessions_are_rejected():
    with pytest.raises(ValueError):
        add_trading_days(date(2026, 10, 6), -1)


def test_long_horizon_never_lands_on_a_weekend_or_known_holiday():
    start = date(2026, 10, 6)
    for sessions in (1, 5, 10, 20, 50, 51, 60):
        landing = target_date(start, sessions)
        assert is_trading_day(landing) or lands_on_unverified_session(start, sessions), (
            sessions,
            landing,
        )


def test_next_trading_day_is_strict_and_skips_both_weekend_days():
    assert next_trading_day(date(2026, 10, 9)) == date(2026, 10, 12)
    assert next_trading_day(date(2026, 10, 10)) == date(2026, 10, 12)
    assert next_trading_day(date(2026, 10, 6)) == date(2026, 10, 7)


def test_known_holiday_is_not_a_trading_day():
    assert date(2026, 12, 24) in holidays_for_year(2026)
    assert not is_trading_day(date(2026, 12, 24))
    # Dec 31 is a weekday market holiday; the next session after it is 2027
    # Jan 4 (Jan 1 was New Year, Jan 2-3 the weekend).
    assert next_trading_day(date(2026, 12, 30)) == date(2027, 1, 4)


def test_unknown_year_falls_back_to_weekend_only_walk():
    # No published table for 2030 yet: weekends still excluded, holidays not.
    assert is_trading_day(date(2030, 7, 17))  # a normal weekday in an unknown year
    assert next_trading_day(date(2030, 7, 12)) == date(2030, 7, 15)


def test_holiday_lists_only_contain_weekdays():
    for year, days in HOLIDAYS.items():
        for day in days:
            assert day.weekday() < 5, (year, day)


def test_target_into_unknown_year_is_flagged_as_unverified():
    # T+50 from late Dec 2026 lands in Mar 2027, which has a table: verified.
    assert not lands_on_unverified_session(date(2026, 12, 23), 50)
    # T+50 from mid 2027 lands in Sep/Oct 2027 (inside table) but T+50 from an
    # unknown-year start cannot be verified.
    assert lands_on_unverified_session(date(2028, 1, 3), 50)
