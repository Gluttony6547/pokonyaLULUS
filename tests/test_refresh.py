"""The refresh pipeline is the only writer, so its guarantees are the important ones."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from idx_signal import db
from idx_signal.models import DataUpdateLog, Prediction
from idx_signal.refresh import RefreshInProgress, refresh, refresh_guard
from idx_signal.storage import recent_updates


def prediction_count() -> int:
    with db.session() as session:
        return session.scalar(select(func.count()).select_from(Prediction)) or 0


def test_manual_refresh_writes_prices_predictions_and_a_log(offline_fetch, reference_assets):
    report = refresh(["ADRO"], horizons=(1, 5), kind="manual")

    assert report.status == "success"
    assert report.rows_inserted > 0
    assert len(report.predictions) == 2
    assert offline_fetch["count"] == 1
    assert prediction_count() == 2
    with db.session() as session:
        entry = recent_updates(session, 1)[0]
    assert entry.trigger_type == "manual"
    assert entry.status == "success"
    assert entry.rows_inserted == report.rows_inserted

    for row in report.predictions:
        assert row["signal"] in {"BUY", "HOLD", "SELL"}
        assert row["target_date"] > row["data_as_of"]
        assert row["model_version_id"] > 0


def test_running_twice_updates_in_place(offline_fetch, reference_assets):
    refresh(["ADRO"], horizons=(1,), kind="manual")
    refresh(["ADRO"], horizons=(1,), kind="manual")

    assert prediction_count() == 1
    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(DataUpdateLog)) == 2


def test_a_scheduled_run_on_a_weekend_is_skipped_without_fetching(
    offline_fetch, reference_assets
):
    report = refresh(["ADRO"], horizons=(1,), kind="scheduled", today=date(2026, 10, 10))

    assert report.status == "skipped"
    assert "bukan hari bursa" in report.message
    assert offline_fetch["count"] == 0
    assert prediction_count() == 0


def test_a_scheduled_run_on_an_exchange_holiday_is_skipped(offline_fetch, reference_assets):
    report = refresh(["ADRO"], horizons=(1,), kind="scheduled", today=date(2026, 3, 20))

    assert report.status == "skipped"
    assert offline_fetch["count"] == 0
    with db.session() as session:
        assert recent_updates(session, 1)[0].status == "skipped"


def test_a_manual_run_is_never_blocked_by_the_calendar(offline_fetch, reference_assets):
    report = refresh(["ADRO"], horizons=(1,), kind="manual", today=date(2026, 3, 20))
    assert report.status == "success"
    assert offline_fetch["count"] == 1


def test_a_second_writer_is_refused(offline_fetch, reference_assets):
    with db.session() as session:
        with refresh_guard(session):
            with pytest.raises(RefreshInProgress):
                refresh(["ADRO"], horizons=(1,), kind="manual")


def test_the_lock_is_released_after_a_run(offline_fetch, reference_assets):
    assert refresh(["ADRO"], horizons=(1,), kind="manual").status == "success"
    assert refresh(["ADRO"], horizons=(1,), kind="manual").status == "success"


def test_unsupported_input_is_rejected(reference_assets):
    with pytest.raises(ValueError):
        refresh(["ADRO"], horizons=(3,), kind="manual")
    with pytest.raises(ValueError):
        refresh(["TIDAKADA"], horizons=(1,), kind="manual")
