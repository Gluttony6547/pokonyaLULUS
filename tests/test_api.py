"""The HTTP surface: what the dashboard reads, and the two actions it can take."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from idx_signal import db
from idx_signal.api import app
from idx_signal.refresh import ensure_model_versions
from idx_signal.storage import ensure_reference_data


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_and_assets_are_served(client):
    root = client.get("/")
    assert root.status_code == 200
    assert "Sinyal" in root.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_health_reports_the_backend_and_artifact_inventory(client, reference_assets):
    payload = client.get("/api/v1/health").json()
    assert payload["status"] == "ok"
    assert payload["storage_backend"] == "sqlite"
    assert payload["stocks"] == 10
    assert payload["artifacts"]["ADRO"] == 5


def test_stocks_are_listed_with_their_public_identity(client):
    rows = client.get("/api/v1/stocks").json()
    assert [row["symbol"] for row in rows] == sorted(row["symbol"] for row in rows)
    assert {"ADRO", "TLKM"} <= {row["symbol"] for row in rows}
    adro = next(row for row in rows if row["symbol"] == "ADRO")
    assert adro["name"] == "Adaro Energy Indonesia Tbk"
    assert adro["last_close"] is None


def test_signals_start_empty_and_say_nothing_was_skipped(client, reference_assets):
    payload = client.get("/api/v1/stocks/ADRO/signals").json()
    assert payload["symbol"] == "ADRO"
    assert payload["signals"] == []


def test_unknown_ticker_is_a_404(client):
    assert client.get("/api/v1/stocks/TSLA/signals").status_code == 404
    assert client.get("/api/v1/prices/TSLA").status_code == 404


def test_unsupported_horizon_is_a_422(client):
    assert client.get("/api/v1/predictions/ADRO?horizon_days=9").status_code == 422


def test_manual_update_populates_the_dashboard(client, offline_fetch, reference_assets):
    response = client.post("/api/v1/update-logs/refresh")
    assert response.status_code == 200, response.text
    entry = response.json()
    assert entry["status"] == "success"
    assert entry["trigger_type"] == "manual"
    assert entry["rows_inserted"] > 0

    signals = client.get("/api/v1/stocks/ADRO/signals").json()
    assert [row["horizon_days"] for row in signals["signals"]] == [1, 5, 10, 20, 50]
    assert signals["last_close"] is not None
    first = signals["signals"][0]
    assert first["signal"] in {"BUY", "HOLD", "SELL"}
    assert first["model_artifact"] == "LSTM_ADRO_Target_1.h5"
    assert first["model_metrics"]["accuracy"] is not None

    prices = client.get("/api/v1/prices/ADRO?limit=180").json()
    assert len(prices["rows"]) == 180
    assert prices["context"]["sma_20"] is not None
    assert prices["context"]["rsi"] is not None

    history = client.get("/api/v1/predictions/ADRO?horizon_days=20").json()
    assert len(history) == 1
    assert history[0]["horizon_days"] == 20

    versions = client.get("/api/v1/model-versions/ADRO").json()
    assert len(versions) == 5
    assert all(version["is_active"] for version in versions)


def test_training_reuses_the_model_that_already_exists(client, reference_assets):
    with db.session() as session:
        ensure_reference_data(session)
        ensure_model_versions(session, ["ADRO"], [1])

    response = client.post(
        "/api/v1/training-jobs", json={"symbol": "ADRO", "horizon_days": 1, "force": False}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["reused"] is True
    assert payload["job"] is None
    assert payload["model_version"] is not None
    assert client.get("/api/v1/training-jobs").json() == []


def test_activation_switches_the_serving_version(client, reference_assets):
    with db.session() as session:
        versions = ensure_model_versions(session, ["ADRO"], [1])
    reference_version = versions[("ADRO", 1)]

    response = client.post(f"/api/v1/model-versions/{reference_version.id}/activate")
    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert client.post("/api/v1/model-versions/999999/activate").status_code == 404
