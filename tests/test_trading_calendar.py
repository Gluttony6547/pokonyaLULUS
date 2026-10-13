"""Horizon target dates have to land on real IDX sessions."""

from __future__ import annotations

from datetime import date

from idx_signal import db
from idx_signal.trading_calendar import (
    add_trading_days,
    crosses_unknown_year,
    is_trading_day,
    load_holidays,
    target_date,
)


def holidays():
    with db.session() as session:
        return load_holidays(session)


def test_weekend_is_not_a_session():
    known, _ = holidays()
    assert is_trading_day(date(2026, 10, 10), known) is False  # Saturday
    assert is_trading_day(date(2026, 10, 11), known) is False  # Sunday
    assert is_trading_day(date(2026, 10, 12), known) is True  # Monday


def test_recorded_holiday_is_not_a_session():
    known, _ = holidays()
    assert is_trading_day(date(2026, 3, 20), known) is False  # Idul Fitri
    assert is_trading_day(date(2026, 8, 17), known) is False  # Independence Day


def test_a_run_of_holidays_is_skipped_as_one_gap():
    known, _ = holidays()
    # 18 to 24 March 2026 is Nyepi plus Idul Fitri plus joint leave, with the
    # weekend in the middle, so the next session after the 17th is the 25th.
    assert add_trading_days(date(2026, 3, 17), 1, known) == date(2026, 3, 25)


def test_weekends_are_skipped_without_holidays():
    known, _ = holidays()
    # Friday plus one session is the following Monday.
    assert add_trading_days(date(2026, 10, 9), 1, known) == date(2026, 10, 12)


def test_zero_sessions_returns_the_same_day():
    known, _ = holidays()
    assert add_trading_days(date(2026, 10, 13), 0, known) == date(2026, 10, 13)


def test_fifty_sessions_regression():
    # The dashboard showed this target for data as of 13 October 2026.
    known, _ = holidays()
    assert target_date(date(2026, 10, 13), 50, known) == date(2026, 12, 22)


def test_target_never_lands_on_a_weekend():
    known, _ = holidays()
    for sessions in (1, 5, 10, 20, 50):
        assert target_date(date(2026, 10, 13), sessions, known).weekday() < 5


def test_years_without_holiday_data_are_flagged():
    _, known_years = holidays()
    assert crosses_unknown_year(date(2026, 10, 13), 50, known_years) is False
    assert crosses_unknown_year(date(2028, 12, 1), 50, known_years) is True
