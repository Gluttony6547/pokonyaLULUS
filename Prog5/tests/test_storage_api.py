from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from fastapi.testclient import TestClient

from prog5 import config
from prog5.api import app
from prog5.indicators import compute_indicators
from prog5.models import RefreshRun
from prog5.storage import store_indicators, store_prices, store_prediction

client = TestClient(app)


def synthetic_prices(rows: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range("2026-06-01", periods=rows).date
    closes = [100.0 + index for index in range(rows)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [close - 1 for close in closes],
            "high": [close + 2 for close in closes],
            "low": [close - 2 for close in closes],
            "close": closes,
            "volume": [10_000 + index for index in range(rows)],
        }
    )


def prediction_record(symbol: str, horizon: int, run_id: int, data_as_of: date) -> dict:
    return {
        "run_id": run_id,
        "symbol": symbol,
        "horizon_days": horizon,
        "data_as_of": data_as_of,
        "window_start_date": date(2026, 6, 1),
        "window_size": horizon,
        "last_close": 159.0,
        "predicted_price": 170.0,
        "return_pct": 6.9,
        "threshold_pct": config.RETURN_THRESHOLDS[horizon] * 100.0,
        "signal": 0,
        "signal_label": "hold",
        "ood_z": 1.2,
        "ood_flag": False,
        "model_file": f"LSTM_{symbol}_Target_{horizon}.h5",
        "model_sha256": "0" * 64,
        "input_mean": 150.0,
        "input_scale": 20.0,
        "target_mean": 160.0,
        "target_scale": 21.0,
        "warnings": None,
    }


def seed(temp_db) -> None:
    frame = synthetic_prices()
    with temp_db.session() as session:
        store_prices(session, "ADRO", frame, "test_fixture")
        store_indicators(session, "ADRO", compute_indicators(frame))
        run = RefreshRun(
            kind="on_demand",
            status="completed",
            requested_symbols="ADRO",
            horizons="1,50",
            finished_at=datetime(2026, 8, 21, 10, 0, 0),
            summary="prices=60 indicators=60 predictions=2 warnings=0",
        )
        session.add(run)
        session.flush()
        last_date = frame["date"].iloc[-1]
        store_prediction(session, prediction_record("ADRO", 1, run.id, last_date))
        store_prediction(session, prediction_record("ADRO", 50, run.id, last_date))


def test_health_reports_counts_and_artifacts(temp_db):
    seed(temp_db)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["stocks"] == 1
    assert body["price_rows"] == 60
    assert body["indicator_rows"] == 60
    assert body["prediction_rows"] == 2
    assert set(body["artifacts"]) == set(config.SUPPORTED_SYMBOLS)
    assert body["last_run"]["status"] == "completed"


def test_stocks_endpoint_returns_latest_close(temp_db):
    seed(temp_db)
    body = client.get("/api/v1/stocks").json()
    assert len(body) == 1
    assert body[0]["symbol"] == "ADRO"
    assert body[0]["last_close"] == 159.0
    assert body[0]["last_price_date"] == "2026-08-21"


def test_prices_endpoint_returns_ascending_rows_and_indicators(temp_db):
    seed(temp_db)
    body = client.get("/api/v1/prices/ADRO", params={"limit": 5}).json()
    assert body["symbol"] == "ADRO"
    assert len(body["rows"]) == 5
    dates = [row["price_date"] for row in body["rows"]]
    assert dates == sorted(dates)
    assert body["latest_indicators"]["sma_50"] is not None
    assert body["latest_indicators"]["rsi"] == 100.0


def test_latest_predictions_are_one_per_horizon(temp_db):
    seed(temp_db)
    body = client.get("/api/v1/predictions/latest/ADRO").json()
    assert [row["horizon_days"] for row in body] == [1, 50]
    assert all(row["symbol"] == "ADRO" for row in body)


def test_predictions_can_be_filtered_by_horizon(temp_db):
    seed(temp_db)
    body = client.get("/api/v1/predictions/ADRO", params={"horizon_days": 50}).json()
    assert len(body) == 1
    assert body[0]["horizon_days"] == 50
    assert body[0]["threshold_pct"] == 11.0
    assert body[0]["model_sha256"] == "0" * 64


def test_predictions_reject_unknown_horizon(temp_db):
    seed(temp_db)
    response = client.get("/api/v1/predictions/ADRO", params={"horizon_days": 7})
    assert response.status_code == 422


def test_unknown_symbol_is_404(temp_db):
    assert client.get("/api/v1/prices/XXXX").status_code == 404
    assert client.get("/api/v1/predictions/XXXX").status_code == 404


def test_runs_endpoint_lists_refresh_runs(temp_db):
    seed(temp_db)
    body = client.get("/api/v1/runs").json()
    assert len(body) == 1
    assert body[0]["requested_symbols"] == "ADRO"
    assert body[0]["horizons"] == "1,50"


def test_root_serves_the_dashboard(temp_db):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Prog5 IDX signal desk" in response.text


def test_health_names_the_active_storage_backend(temp_db):
    body = client.get("/api/v1/health").json()
    assert body["storage_backend"] == "sqlite"


def test_ui_page_is_served_by_the_same_app(temp_db):
    response = client.get("/app/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Prog5" in response.text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/app.css").status_code == 200


def test_prediction_upsert_is_idempotent(temp_db):
    seed(temp_db)
    with temp_db.session() as session:
        store_prediction(session, prediction_record("ADRO", 50, 1, date(2026, 8, 21)))
    with temp_db.session() as session:
        rows = client.get("/api/v1/predictions/ADRO", params={"horizon_days": 50}).json()
    assert len(rows) == 1
    assert rows[0]["predicted_price"] == 170.0


def test_prices_upsert_is_idempotent(temp_db):
    frame = synthetic_prices(5)
    with temp_db.session() as session:
        store_prices(session, "ADRO", frame, "test_fixture")
    with temp_db.session() as session:
        store_prices(session, "ADRO", frame, "test_fixture")
    assert client.get("/api/v1/health").json()["price_rows"] == 5
