from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from prog5 import config
from prog5 import refresh as refresh_module
from prog5.models import Prediction, RefreshRun

from .conftest import requires_artifacts


def synthetic_frame(rows: int = 260, last_close: float = 2500.0, jump: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-10-02", periods=rows).date
    closes = [last_close - 0.5 * (rows - index) for index in range(rows)]
    if jump:
        # A reverse split on the final session: inside every input window.
        closes[-1] = closes[-2] / 5.0
    return pd.DataFrame(
        {
            "date": dates,
            "open": [close - 2 for close in closes],
            "high": [close + 5 for close in closes],
            "low": [close - 5 for close in closes],
            "close": closes,
            "volume": [1_000_000] * rows,
        }
    )


@requires_artifacts
def test_refresh_stores_one_prediction_per_horizon(temp_db, monkeypatch):
    frame = synthetic_frame()
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    # Keep the pipeline fast: the real inference is covered by the replication
    # and registry tests, this test covers orchestration and storage.
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1]) * 1.5
    )

    report = refresh_module.refresh(["ADRO"], horizons=config.HORIZONS)

    assert report.status == "completed"
    assert len(report.predictions) == len(config.HORIZONS)
    assert {row["horizon_days"] for row in report.predictions} == set(config.HORIZONS)
    assert all(row["signal"] == 1 for row in report.predictions)  # +50% clears every threshold
    assert all(row["model_sha256"] for row in report.predictions)

    with temp_db.session() as session:
        assert session.query(Prediction).count() == len(config.HORIZONS)


@requires_artifacts
def test_refresh_records_the_trading_day_target_date(temp_db, monkeypatch):
    frame = synthetic_frame()
    data_as_of = frame["date"].iloc[-1]  # a Friday, so every target crosses a weekend
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1])
    )

    report = refresh_module.refresh(["ADRO"], horizons=(1, 10))

    assert report.status == "completed"
    by_horizon = {row["horizon_days"]: row for row in report.predictions}
    assert by_horizon[1]["target_date"] == date(2026, 10, 5)  # Friday close, Monday target
    assert by_horizon[10]["target_date"] == date(2026, 10, 16)  # two weekend days skipped
    with temp_db.session() as session:
        row = session.query(Prediction).filter(Prediction.horizon_days == 10).one()
        assert row.target_date == date(2026, 10, 16)
        assert row.data_as_of == data_as_of


@requires_artifacts
def test_refresh_is_idempotent_for_the_same_session(temp_db, monkeypatch):
    frame = synthetic_frame()
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1])
    )

    first = refresh_module.refresh(["ADRO"], horizons=(1, 50))
    second = refresh_module.refresh(["ADRO"], horizons=(1, 50))

    assert first.status == "completed" and second.status == "completed"
    with temp_db.session() as session:
        assert session.query(Prediction).count() == 2


@requires_artifacts
def test_refresh_skips_horizons_with_a_corporate_action_in_the_window(temp_db, monkeypatch):
    frame = synthetic_frame(jump=True)
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1])
    )

    report = refresh_module.refresh(["ADRO"], horizons=(1, 50))

    assert report.status == "failed"
    assert not report.predictions
    assert any("T1: corporate action" in warning for warning in report.warnings)
    assert any("T50: corporate action" in warning for warning in report.warnings)


@requires_artifacts
def test_refresh_stores_only_the_last_completed_session(temp_db, monkeypatch):
    """A forming intraday bar must never be stored or predicted on."""
    frame = synthetic_frame()
    last_session = frame["date"].iloc[-1]
    # Yahoo during a live session: full history plus an extra bar dated
    # later with some unfinished price.
    forming = pd.concat(
        [
            frame,
            pd.DataFrame(
                {
                    "date": [last_session + pd.Timedelta(days=3)],
                    "open": [2600.0],
                    "high": [2620.0],
                    "low": [2580.0],
                    "close": [2590.0],
                    "volume": [900_000],
                }
            ),
        ],
        ignore_index=True,
    )

    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: forming.copy())
    # Freeze the clock inside the forming window of the extra bar. The fake
    # subclasses datetime so constructor calls keep working.
    frozen_moment = refresh_module._forming_since(
        last_session + pd.Timedelta(days=3)
    ) - refresh_module.timedelta(hours=1)

    class FrozenClock(datetime):
        @staticmethod
        def now(tz=None):
            return frozen_moment

        def __add__(self, other):
            return datetime.__add__(self, other)

    monkeypatch.setattr(refresh_module, "datetime", FrozenClock)
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1])
    )

    report = refresh_module.refresh(["ADRO"], horizons=(1,))

    assert report.status == "completed"  # the last closed session still predicts
    assert any("still forming" in warning for warning in report.warnings), report.warnings
    assert all(p["last_close"] != 2590.0 for p in report.predictions)
    with temp_db.session() as session:
        stored = session.query(Prediction).one()
        assert stored.data_as_of == last_session


@requires_artifacts
def test_a_telemetry_failure_keeps_the_completed_run(temp_db, monkeypatch):
    frame = synthetic_frame()
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1])
    )

    def telemetry_down(*args, **kwargs):
        raise RuntimeError("telemetry store unavailable")

    monkeypatch.setattr(refresh_module, "record_successful_refresh", telemetry_down)

    report = refresh_module.refresh(["ADRO"], horizons=(1,))

    assert report.status == "completed"
    assert any("telemetry" in warning for warning in report.warnings)
    with temp_db.session() as session:
        run = session.get(RefreshRun, report.run_id)
        assert run.status == "completed"
        assert run.finished_at is not None
        assert session.query(Prediction).count() == 1
