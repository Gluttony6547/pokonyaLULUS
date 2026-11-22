"""The HTTP surface: what the dashboard reads, and the two actions it can take."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from idx_signal import config, db
from idx_signal.api import app
from idx_signal.historical import format_date_id
from idx_signal.market_data import MarketDataUnavailable
from idx_signal.refresh import ensure_model_versions
from idx_signal.storage import (
    active_model_version,
    ensure_reference_data,
    model_artifact_bytes,
    store_prediction,
    store_prices,
)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client


def test_guarded_endpoints_reject_anonymous_callers(client):
    assert client.post("/api/v1/update-logs/refresh").status_code == 401
    assert client.post("/api/v1/model-versions/1/activate").status_code == 401


def test_dashboard_and_assets_are_served(client):
    root = client.get("/")
    assert root.status_code == 200
    assert "Sinyal" in root.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_intraday_quote_endpoint_returns_price_and_timestamp(client, monkeypatch):
    observed_at = datetime(2026, 10, 14, 7, 26, tzinfo=timezone.utc)
    monkeypatch.setattr("idx_signal.api.fetch_intraday_quote", lambda symbol: (2530.0, observed_at))

    response = client.get("/api/v1/quotes/ADRO")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "ADRO",
        "price": 2530.0,
        "observed_at": "2026-10-14T07:26:00Z",
        "source": "Yahoo Finance",
    }


def test_intraday_quote_endpoint_rejects_unsupported_ticker(client):
    assert client.get("/api/v1/quotes/NOPE").status_code == 404


def test_intraday_quote_endpoint_reports_provider_unavailable(client, monkeypatch):
    def unavailable(_symbol):
        raise MarketDataUnavailable("Kuotasi intrahari belum tersedia.")

    monkeypatch.setattr("idx_signal.api.fetch_intraday_quote", unavailable)

    response = client.get("/api/v1/quotes/ADRO")

    assert response.status_code == 503
    assert response.json()["detail"] == "Kuotasi intrahari belum tersedia."


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
    assert adro["first_usable_reference_date"] is None
    assert adro["price_session_count"] == 0


def test_signals_start_empty_and_say_nothing_was_skipped(client, reference_assets):
    payload = client.get("/api/v1/stocks/ADRO/signals").json()
    assert payload["symbol"] == "ADRO"
    assert payload["signals"] == []


def test_unknown_ticker_is_a_404(client):
    assert client.get("/api/v1/stocks/TSLA/signals").status_code == 404
    assert client.get("/api/v1/prices/TSLA").status_code == 404


def test_unsupported_horizon_is_a_422(client):
    assert client.get("/api/v1/predictions/ADRO?horizon_days=9").status_code == 422


def test_manual_update_populates_the_dashboard(admin_client, offline_fetch, reference_assets):
    client = admin_client
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


def store_history(prices, symbol: str = "ADRO") -> None:
    with db.session() as session:
        store_prices(session, symbol, prices)


def test_stocks_report_the_stored_date_range(client, prices):
    store_history(prices)

    adro = next(row for row in client.get("/api/v1/stocks").json() if row["symbol"] == "ADRO")

    assert adro["first_price_date"] == str(prices.iloc[0]["date"])
    assert adro["last_price_date"] == str(prices.iloc[-1]["date"])
    assert adro["earliest_reference_date"] == adro["first_price_date"]
    assert adro["first_usable_reference_date"] == str(
        prices.iloc[max(config.HORIZONS) - 1]["date"]
    )
    assert adro["price_session_count"] == len(prices)


def test_historical_signals_are_recomputed_for_a_stored_session(client, prices, reference_assets):
    store_history(prices)
    reference = prices.iloc[300]["date"]

    response = client.get(f"/api/v1/stocks/ADRO/signals/historical?date={reference}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["symbol"] == "ADRO"
    assert payload["reference_date"] == str(reference)
    assert payload["reference_close"] == pytest.approx(float(prices.iloc[300]["close"]))
    assert payload["first_price_date"] == str(prices.iloc[0]["date"])
    assert payload["last_price_date"] == str(prices.iloc[-1]["date"])
    assert payload["first_usable_reference_date"] == str(
        prices.iloc[max(config.HORIZONS) - 1]["date"]
    )
    assert payload["scorecard"]["realized"] >= 1
    assert [row["horizon_days"] for row in payload["signals"]] == list(config.HORIZONS)

    first = payload["signals"][0]
    assert first["data_as_of"] == str(reference)
    assert first["model_artifact"] == "LSTM_ADRO_Target_1.h5"
    assert first["signal"] in {"BUY", "HOLD", "SELL"}
    assert date.fromisoformat(first["target_date"]) > reference
    assert first["outcome_status"] == "realized"
    assert first["actual_close"] is not None
    assert first["actual_date"] == first["target_date"]
    assert first["direction_correct"] in {True, False}


def test_historical_signals_accept_the_first_usable_date(client, prices, reference_assets):
    store_history(prices)
    usable = prices.iloc[max(config.HORIZONS) - 1]["date"]
    before = prices.iloc[max(config.HORIZONS) - 2]["date"]

    accepted = client.get(
        f"/api/v1/stocks/ADRO/signals/historical?date={usable}"
    )
    rejected = client.get(
        f"/api/v1/stocks/ADRO/signals/historical?date={before}"
    )

    assert accepted.status_code == 200, accepted.text
    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert format_date_id(usable) in detail
    assert str(before) not in detail


def test_historical_signals_leave_the_stored_signals_alone(client, prices, reference_assets):
    store_history(prices)
    reference = prices.iloc[300]["date"]

    assert client.get("/api/v1/predictions/ADRO").json() == []
    assert client.get(f"/api/v1/stocks/ADRO/signals/historical?date={reference}").status_code == 200

    assert client.get("/api/v1/predictions/ADRO").json() == []
    assert client.get("/api/v1/stocks/ADRO/signals").json()["signals"] == []


def test_historical_signals_reject_a_malformed_date(client):
    response = client.get("/api/v1/stocks/ADRO/signals/historical?date=17-10-2026")

    assert response.status_code == 422
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_historical_signals_reject_a_date_after_the_newest_price(client, prices, reference_assets):
    store_history(prices)
    newest = prices.iloc[-1]["date"]

    response = client.get(
        f"/api/v1/stocks/ADRO/signals/historical?date={newest + timedelta(days=1)}"
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert format_date_id(newest) in detail
    assert str(newest) not in detail


def test_historical_signals_reject_a_date_without_a_price(client, prices, reference_assets):
    store_history(prices)
    reference = prices.iloc[300]["date"]
    saturday = next(
        reference + timedelta(days=offset)
        for offset in range(1, 8)
        if (reference + timedelta(days=offset)).weekday() >= 5
    )

    response = client.get(f"/api/v1/stocks/ADRO/signals/historical?date={saturday}")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Tidak ada harga penutupan" in detail
    assert format_date_id(saturday) in detail
    assert str(saturday) not in detail


def test_historical_signals_reject_an_unknown_ticker(client):
    response = client.get("/api/v1/stocks/TSLA/signals/historical?date=2024-06-03")

    assert response.status_code == 404


def test_training_reuses_the_model_that_already_exists(admin_client, reference_assets):
    client = admin_client
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


def test_activation_switches_the_serving_version(admin_client, reference_assets):
    client = admin_client
    with db.session() as session:
        versions = ensure_model_versions(session, ["ADRO"], [1])
    reference_version = versions[("ADRO", 1)]

    response = client.post(f"/api/v1/model-versions/{reference_version.id}/activate")
    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert client.post("/api/v1/model-versions/999999/activate").status_code == 404


def ensemble_bytes(horizon_days: int) -> bytes:
    import io

    import joblib
    import numpy as np

    from idx_signal.model_registry import build_ensemble

    rng = np.random.default_rng(11)
    windows = rng.normal(2000.0, 100.0, size=(40, horizon_days))
    targets = windows[:, -1] + rng.normal(0.0, 20.0, size=40)
    buffer = io.BytesIO()
    joblib.dump(build_ensemble().fit(windows, targets), buffer)
    return buffer.getvalue()


def test_upload_saves_a_candidate_without_touching_the_active_version(
    admin_client, reference_assets
):
    client = admin_client
    with db.session() as session:
        ensure_model_versions(session, ["ADRO"], [1])
    payload = ensemble_bytes(1)

    response = client.post(
        "/api/v1/model-versions/upload",
        files={"file": ("custom_adro.joblib", payload, "application/octet-stream")},
        data={"symbol": "ADRO", "horizon_days": "1"},
    )

    assert response.status_code == 200, response.text
    version = response.json()
    assert version["is_active"] is False
    assert version["config"]["source"] == "uploaded"
    assert version["artifact_path"].startswith("UPLOADED_ADRO_Target_1_")
    with db.session() as session:
        assert model_artifact_bytes(session, version["id"]) == payload
        active = active_model_version(session, "ADRO", 1)
    assert active.id != version["id"]

    duplicate = client.post(
        "/api/v1/model-versions/upload",
        files={"file": ("custom_adro.joblib", payload, "application/octet-stream")},
        data={"symbol": "ADRO", "horizon_days": "1"},
    )
    assert duplicate.status_code == 409
    assert f"versi #{version['id']}" in duplicate.json()["detail"]


def test_upload_rejects_a_model_fitted_for_another_horizon(admin_client, reference_assets):
    response = admin_client.post(
        "/api/v1/model-versions/upload",
        files={"file": ("custom_adro.joblib", ensemble_bytes(5), "application/octet-stream")},
        data={"symbol": "ADRO", "horizon_days": "1"},
    )

    assert response.status_code == 422
    assert "mengharapkan 5 masukan" in response.json()["detail"]


def test_upload_requires_the_admin_token_and_a_joblib_file(client):
    anonymous = client.post(
        "/api/v1/model-versions/upload",
        files={"file": ("custom_adro.joblib", b"x", "application/octet-stream")},
        data={"symbol": "ADRO", "horizon_days": "1"},
    )
    assert anonymous.status_code == 401


def test_upload_refuses_a_file_with_another_extension(admin_client):
    response = admin_client.post(
        "/api/v1/model-versions/upload",
        files={"file": ("custom_adro.pkl", b"x", "application/octet-stream")},
        data={"symbol": "ADRO", "horizon_days": "1"},
    )

    assert response.status_code == 422
    assert ".joblib" in response.json()["detail"]


def seed_predictions(count: int = 12) -> None:
    with db.session() as session:
        version = ensure_model_versions(session, ["ADRO"], [1])[("ADRO", 1)]
        for offset in range(count):
            store_prediction(
                session,
                {
                    "symbol": "ADRO",
                    "horizon_days": 1,
                    "model_version_id": version.id,
                    "data_as_of": date(2026, 1, 1) + timedelta(days=offset),
                    "target_date": date(2026, 1, 2) + timedelta(days=offset),
                    "signal": "HOLD",
                    "predicted_price": 2000.0,
                    "last_close": 2000.0,
                    "return_pct": 0.5,
                    "threshold_pct": 1.5,
                    "ood_z": 0.1,
                    "ood_flag": False,
                    "warnings": None,
                },
            )


def test_guest_history_stops_at_the_ten_newest_rows(client, reference_assets):
    seed_predictions()

    rows = client.get("/api/v1/predictions/ADRO?limit=200").json()

    assert len(rows) == 10
    assert rows[0]["data_as_of"] > rows[-1]["data_as_of"]


def test_admin_history_returns_every_stored_row(admin_client, reference_assets):
    seed_predictions()

    rows = admin_client.get("/api/v1/predictions/ADRO?limit=200").json()

    assert len(rows) == 12


def test_training_finishes_inside_the_request_on_serverless(admin_client, prices, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with db.session() as session:
        store_prices(session, "ADRO", prices)

    response = admin_client.post(
        "/api/v1/training-jobs", json={"symbol": "ADRO", "horizon_days": 1, "force": True}
    )

    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["status"] == "success", job
    assert job["model_version_id"] is not None
