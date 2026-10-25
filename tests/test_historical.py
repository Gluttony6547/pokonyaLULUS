"""Historical lookups: closes stop at the chosen date and nothing is stored."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select

from idx_signal import config, db
from idx_signal.historical import (
    HistoricalDateError,
    first_usable_reference_date,
    first_usable_reference_date_from_window,
    format_date_id,
    reference_bounds,
    signals_for_date,
)
from idx_signal.model_registry import scalers_from_research
from idx_signal.models import Prediction
from idx_signal.refresh import ensure_model_versions
from idx_signal.storage import nth_price_date, store_prices
from idx_signal.trading_calendar import load_holidays, target_date


def store(frame: pd.DataFrame) -> None:
    with db.session() as session:
        store_prices(session, "ADRO", frame)


def lookup(reference: date, symbol: str = "ADRO"):
    with db.session() as session:
        return signals_for_date(session, symbol, reference)


def test_closes_after_the_reference_date_are_ignored(prices, reference_assets):
    reference = prices.iloc[300]["date"]
    store(prices)
    baseline = lookup(reference)

    tail = prices.copy()
    tail.loc[tail.index[301]:, ["open", "high", "low", "close"]] *= 3
    store(tail)

    again = lookup(reference)
    assert again.reference_close == baseline.reference_close == float(prices.iloc[300]["close"])
    assert [row.predicted_price for row in again.signals] == [
        row.predicted_price for row in baseline.signals
    ]


def test_every_horizon_lands_on_an_exchange_session(prices, reference_assets):
    reference = prices.iloc[300]["date"]
    store(prices)
    result = lookup(reference)

    assert [row.horizon_days for row in result.signals] == list(config.HORIZONS)
    with db.session() as session:
        holidays, _ = load_holidays(session)
    for row in result.signals:
        assert row.data_as_of == reference
        assert row.reference_close == pytest.approx(float(prices.iloc[300]["close"]))
        assert row.target_date == target_date(reference, row.horizon_days, holidays)
        assert row.target_date.weekday() < 5
        assert row.model_artifact == f"LSTM_ADRO_Target_{row.horizon_days}.h5"

    # The holiday table covers 2026 and 2027 only, so a 2025 lookup says so once
    # rather than repeating the note on every row.
    coverage = [warning for warning in result.warnings if "kalender libur bursa" in warning]
    assert len(coverage) == 1


def test_the_active_version_is_preferred_and_the_reference_artifact_fills_the_rest(
    prices, reference_assets
):
    store(prices)
    reference = prices.iloc[300]["date"]
    with db.session() as session:
        version_id = ensure_model_versions(session, ["ADRO"], [1])[("ADRO", 1)].id

    result = lookup(reference)

    by_horizon = {row.horizon_days: row for row in result.signals}
    assert by_horizon[1].model_version_id == version_id
    assert by_horizon[5].model_version_id is None


def test_a_date_without_a_price_row_is_rejected(prices, reference_assets):
    reference = prices.iloc[300]["date"]
    store(prices)
    saturday = next(
        reference + timedelta(days=offset)
        for offset in range(1, 8)
        if (reference + timedelta(days=offset)).weekday() >= 5
    )

    with pytest.raises(HistoricalDateError) as error:
        lookup(saturday)
    assert "Tidak ada harga penutupan" in str(error.value)


def test_a_short_window_names_the_first_usable_date(prices, reference_assets):
    store(prices)

    with pytest.raises(HistoricalDateError) as error:
        lookup(prices.iloc[10]["date"])

    needed = max(config.HORIZONS)
    message = str(error.value)
    assert f"model butuh {needed} sesi" in message
    assert format_date_id(prices.iloc[needed - 1]["date"]) in message
    assert str(prices.iloc[needed - 1]["date"]) not in message


def test_dates_outside_the_allowed_range_are_rejected(prices, reference_assets):
    store(prices)
    newest = prices.iloc[-1]["date"]

    with pytest.raises(HistoricalDateError) as future:
        lookup(newest + timedelta(days=7))
    assert format_date_id(newest) in str(future.value)
    assert str(newest) not in str(future.value)

    with pytest.raises(HistoricalDateError) as older:
        lookup(prices.iloc[0]["date"] - timedelta(days=1))
    with db.session() as session:
        usable = first_usable_reference_date(session, "ADRO")
    assert format_date_id(usable) in str(older.value)
    assert str(prices.iloc[0]["date"]) not in str(older.value)


def test_a_historical_lookup_never_writes_a_prediction(prices, reference_assets):
    store(prices)
    lookup(prices.iloc[300]["date"])

    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0


def test_a_close_outside_the_training_range_is_flagged(prices, reference_assets):
    scalers = scalers_from_research("ADRO", 1)
    target = scalers.input_mean + 3 * scalers.input_scale
    frame = prices.copy()
    # Scaling the whole series keeps every overnight move small, so the
    # corporate-action guard stays quiet and only the level is out of range.
    frame[["open", "high", "low", "close"]] *= target / float(prices.iloc[300]["close"])
    store(frame)

    result = lookup(frame.iloc[300]["date"])

    assert result.signals and all(row.ood_flag for row in result.signals)
    assert "simpangan baku" in (result.signals[0].warnings or "")


def test_the_reference_range_is_capped_at_ten_years():
    first, last = date(2010, 1, 4), date(2026, 10, 16)
    assert reference_bounds(first, last) == (date(2016, 10, 16), last)


def test_the_picker_minimum_is_the_first_session_that_fills_the_window(
    prices, reference_assets
):
    store(prices)
    with db.session() as session:
        usable = first_usable_reference_date(session, "ADRO")

    assert usable == prices.iloc[max(config.HORIZONS) - 1]["date"]
    result = lookup(usable)
    assert result.first_usable_reference_date == usable
    assert len(result.signals) == len(config.HORIZONS)


def test_a_precomputed_window_gives_the_same_picker_minimum(prices, reference_assets):
    store(prices)
    with db.session() as session:
        window_start = nth_price_date(session, "ADRO", max(config.HORIZONS))
        usable = first_usable_reference_date_from_window(
            session,
            "ADRO",
            (prices.iloc[0]["date"], prices.iloc[-1]["date"]),
            window_start,
        )

    assert usable == prices.iloc[max(config.HORIZONS) - 1]["date"]


def test_a_realized_target_shows_the_actual_close_and_direction(prices, reference_assets):
    store(prices)
    reference = prices.iloc[300]["date"]
    closes = dict(zip(prices["date"], prices["close"]))

    result = lookup(reference)

    for row in result.signals:
        assert row.outcome_status == "realized"
        assert row.actual_date == row.target_date
        assert row.actual_close == pytest.approx(float(closes[row.target_date]))
        assert row.actual_signal in {"BUY", "HOLD", "SELL"}
        assert row.direction_correct is (row.actual_signal == row.signal)
        expected = (row.actual_close - row.predicted_price) / row.predicted_price * 100
        assert row.prediction_error_pct == pytest.approx(expected)
    assert result.scorecard.realized == len(result.signals)
    assert result.scorecard.direction_total == len(result.signals)
    assert result.scorecard.mean_abs_error_pct is not None


def test_a_target_after_the_newest_price_is_pending(prices, reference_assets):
    store(prices)

    result = lookup(prices.iloc[-1]["date"])

    assert all(row.outcome_status == "pending" for row in result.signals)
    assert all(row.actual_close is None for row in result.signals)
    assert result.scorecard.realized == 0
    assert result.scorecard.pending == len(result.signals)


def test_a_missing_target_is_marked_no_price(prices, reference_assets):
    reference = prices.iloc[300]["date"]
    with db.session() as session:
        holidays, _ = load_holidays(session)
    target = target_date(reference, 1, holidays)
    gap_end = target + timedelta(days=7)
    modified = prices[~((prices["date"] >= target) & (prices["date"] <= gap_end))].copy()
    store(modified)

    result = lookup(reference)

    first = next(row for row in result.signals if row.horizon_days == 1)
    assert first.outcome_status == "no_price"
    assert first.actual_close is None
    assert result.scorecard.no_price >= 1


def test_a_corporate_action_in_the_outcome_window_is_not_scored(
    prices, reference_assets
):
    reference = prices.iloc[300]["date"]
    with db.session() as session:
        holidays, _ = load_holidays(session)
    target = target_date(reference, 1, holidays)
    modified = prices.copy()
    mask = modified["date"] == target
    modified.loc[mask, "close"] = modified.loc[mask, "close"] * 2
    store(modified)

    result = lookup(reference)

    first = next(row for row in result.signals if row.horizon_days == 1)
    assert first.outcome_status == "corporate_action"
    assert first.direction_correct is None
    assert result.scorecard.corporate_action >= 1
    assert result.scorecard.direction_total == result.scorecard.realized
