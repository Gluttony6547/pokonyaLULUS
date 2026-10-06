from __future__ import annotations

from datetime import date

import pytest

from prog5.trading_calendar import add_trading_days, is_trading_day, next_trading_day, target_date


def test_user_example_oct_6_plus_10_sessions_is_oct_20():
    # Tuesday 2026-10-06 + 10 trading sessions: two weekends inside, ends
    # Tuesday 2026-10-20, exactly the case from the request.
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


def test_long_horizon_never_lands_on_a_weekend():
    start = date(2026, 10, 6)
    for sessions in (1, 5, 10, 20, 50, 51, 60):
        landing = target_date(start, sessions)
        assert is_trading_day(landing), (sessions, landing)


def test_next_trading_day_is_strict_and_skips_both_weekend_days():
    assert next_trading_day(date(2026, 10, 9)) == date(2026, 10, 12)
    assert next_trading_day(date(2026, 10, 10)) == date(2026, 10, 12)
    assert next_trading_day(date(2026, 10, 6)) == date(2026, 10, 7)
