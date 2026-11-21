"""The refresh pipeline is the only writer, so its guarantees are the important ones."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from idx_signal import config, db
from idx_signal.models import DataUpdateLog, Prediction
from idx_signal.refresh import RefreshInProgress, refresh, refresh_guard
from idx_signal.storage import active_model_version, recent_updates, store_prices
from idx_signal.training import activate_version, queue_training_job, run_job


def prediction_count() -> int:
    with db.session() as session:
        return session.scalar(select(func.count()).select_from(Prediction)) or 0


def test_refresh_keeps_an_activated_candidate(offline_fetch, prices, reference_assets):
    with db.session() as session:
        store_prices(session, "ADRO", prices)
        job, _ = queue_training_job(session, "ADRO", 1, force=True)
        job_id = job.id
    finished = run_job(job_id)
    with db.session() as session:
        activate_version(session, finished.model_version_id)

    report = refresh(["ADRO"], horizons=(1,), kind="manual")

    assert report.status == "success", report.warnings
    with db.session() as session:
        active = active_model_version(session, "ADRO", 1)
        row = session.scalars(
            select(Prediction)
            .where(Prediction.symbol == "ADRO", Prediction.horizon_days == 1)
            .order_by(Prediction.id.desc())
            .limit(1)
        ).first()
    assert active.id == finished.model_version_id
    assert row.model_version_id == finished.model_version_id


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


@pytest.mark.parametrize(
    ("today", "expected_target"),
    ((date(2026, 10, 13), date(2026, 10, 14)), (date(2026, 10, 17), date(2026, 10, 19))),
)
def test_target_date_uses_today_and_skips_weekends(
    offline_fetch, reference_assets, today, expected_target
):
    report = refresh(["ADRO"], horizons=(1,), kind="manual", today=today)

    assert report.status == "success"
    row = report.predictions[0]
    assert row["data_as_of"] < today
    assert row["target_date"] == expected_target


def test_running_twice_updates_in_place(offline_fetch, reference_assets):
    refresh(["ADRO"], horizons=(1,), kind="manual")
    refresh(["ADRO"], horizons=(1,), kind="manual")

    assert prediction_count() == 1
    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(DataUpdateLog)) == 2


def test_refresh_rebases_reference_model_path_from_another_os(offline_fetch, reference_assets):
    first = refresh(["ADRO"], horizons=(1,), kind="manual")
    assert first.status == "success"

    with db.session() as session:
        version = active_model_version(session, "ADRO", 1)
        assert version is not None
        version.artifact_path = r"C:\SMT_7\PRATAAA\models\ADRO\LSTM_ADRO_Target_1.h5"

    second = refresh(["ADRO"], horizons=(1,), kind="manual")

    assert second.status == "success"
    assert len(second.predictions) == 1
    with db.session() as session:
        version = active_model_version(session, "ADRO", 1)
        assert version is not None
        assert version.artifact_path == str(config.artifact_file("ADRO", 1))


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

