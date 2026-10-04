from __future__ import annotations

import pandas as pd

from prog5 import config
from prog5 import refresh as refresh_module
from prog5.models import Prediction

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
