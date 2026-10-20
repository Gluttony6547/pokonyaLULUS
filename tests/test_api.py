"""The HTTP surface: what the dashboard reads, and the two actions it can take."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from idx_signal import config, db
from idx_signal.api import app
from idx_signal.market_data import MarketDataUnavailable
from idx_signal.refresh import ensure_model_versions
from idx_signal.storage import ensure_reference_data, store_prices


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


def store_history(prices, symbol: str = "ADRO") -> None:
    with db.session() as session:
        store_prices(session, symbol, prices)


def test_stocks_report_the_stored_date_range(client, prices):
    store_history(prices)

    adro = next(row for row in client.get("/api/v1/stocks").json() if row["symbol"] == "ADRO")

    assert adro["first_price_date"] == str(prices.iloc[0]["date"])
    assert adro["last_price_date"] == str(prices.iloc[-1]["date"])
    assert adro["earliest_reference_date"] == adro["first_price_date"]


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
    assert [row["horizon_days"] for row in payload["signals"]] == list(config.HORIZONS)

    first = payload["signals"][0]
    assert first["data_as_of"] == str(reference)
    assert first["model_artifact"] == "LSTM_ADRO_Target_1.h5"
    assert first["signal"] in {"BUY", "HOLD", "SELL"}
    assert date.fromisoformat(first["target_date"]) > reference


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
    assert str(newest) in response.json()["detail"]


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
    assert "Tidak ada harga penutupan" in response.json()["detail"]


def test_historical_signals_reject_an_unknown_ticker(client):
    response = client.get("/api/v1/stocks/TSLA/signals/historical?date=2024-06-03")

    assert response.status_code == 404


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
