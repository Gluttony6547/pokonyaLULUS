import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("KERAS_BACKEND", "torch")

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend_api
from data_pipeline import TemporalDataFuser, TechnicalIndicatorExtractor, generate_sample_fused_dataset
from database import Base, engine
from market_data import MarketSnapshot, fetch_yahoo_history, load_research_history
from model_service import SUPPORTED_HORIZONS, classify_return, predict_price


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(backend_api.app) as test_client:
        yield test_client


def test_data_pipeline_builds_technical_and_sentiment_features():
    fused = generate_sample_fused_dataset()

    assert not fused.empty
    assert {"rsi", "macd", "sentiment", "positive_count", "negative_count"} <= set(fused.columns)
    assert fused["close"].notna().all()


def test_after_close_news_rolls_to_the_next_business_day():
    after_close = pd.Timestamp("2026-09-25 16:30:00")

    adjusted = TemporalDataFuser.adjust_news_trading_date(after_close)

    assert adjusted == pd.Timestamp("2026-09-28")


def test_indicators_are_calculated_from_ohlcv_prices():
    close = np.linspace(100, 160, 60)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(60, 1000),
        }
    )

    result = TechnicalIndicatorExtractor.compute_indicators(frame)

    assert result["sma_50"].notna().iloc[-1]
    assert result["rsi"].notna().iloc[-1]
    assert result["upperband"].iloc[-1] > result["middleband"].iloc[-1]


@pytest.mark.parametrize(
    ("horizon_days", "threshold_percent"), [(1, 1.5), (5, 3), (10, 6), (20, 9), (50, 11)]
)
def test_signal_uses_research_threshold_for_each_horizon(horizon_days, threshold_percent):
    signal, return_percent = classify_return(100 * (1 + threshold_percent / 100), 100, horizon_days)

    assert signal == 1
    assert return_percent == pytest.approx(threshold_percent)


def test_pseudolabeler_retrains_on_high_confidence_samples():
    from data_pipeline import SVMPseudolabeler

    rows = ["saham untung", "saham naik", "saham rugi", "saham turun"]
    seed = [("saham untung", 2), ("saham naik", 2), ("saham rugi", -1), ("saham turun", -1)]

    result = SVMPseudolabeler(min_confidence=0.8).pseudolabel(rows, seed)

    assert len(result) == len(rows)
    assert set(result["sentiment_flag"]) <= {-1, 0, 1, 2}
    assert result["sentiment_flag"].isin([-1, 2]).all()


def test_health_reports_database_and_available_artifacts(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["database"] == "connected"
    assert response.json()["available_models"] == 50


def test_stock_list_matches_available_research_models(client):
    response = client.get("/api/v1/stocks")

    assert response.status_code == 200
    assert {item["symbol"] for item in response.json()} == {
        "ADRO",
        "ANTM",
        "BMRI",
        "BNGA",
        "EXCL",
        "INCO",
        "INKP",
        "MEDC",
        "PGAS",
        "TLKM",
    }


def test_latest_prediction_has_an_empty_state_instead_of_a_seeded_example(client):
    response = client.get("/api/v1/predictions/latest/ADRO")

    assert response.status_code == 404
    assert "Belum ada prediksi" in response.json()["detail"]


def test_market_endpoint_falls_back_to_labeled_research_dataset(client, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise TimeoutError("provider unavailable")

    monkeypatch.setattr("market_data.fetch_yahoo_history", unavailable)

    response = client.get("/api/v1/market-data/ADRO?period=1y")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "research_dataset"
    assert body["warning"]
    assert body["data_as_of"] < date.today().isoformat()
    assert body["prices"]


def test_yahoo_fetch_retries_once_after_a_transient_failure(monkeypatch):
    import yfinance

    attempts = 0

    def download(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary provider timeout")
        dates = pd.date_range("2026-09-01", periods=2, freq="B", name="Date")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [102.0, 103.0],
                "Low": [99.0, 100.0],
                "Close": [101.0, 102.0],
                "Volume": [1000, 1100],
            },
            index=dates,
        )

    monkeypatch.setattr(yfinance, "download", download)
    monkeypatch.setattr("market_data.time.sleep", lambda _seconds: None)

    prices = fetch_yahoo_history("ADRO", "1y")

    assert attempts == 2
    assert prices["close"].tolist() == [101.0, 102.0]


def test_market_cache_keeps_the_research_dataset_label(client, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise TimeoutError("provider unavailable")

    monkeypatch.setattr("market_data.fetch_yahoo_history", unavailable)

    first_response = client.get("/api/v1/market-data/ADRO?period=6mo")
    cached_response = client.get("/api/v1/market-data/ADRO?period=6mo")

    assert first_response.json()["source"] == "research_dataset"
    assert cached_response.json()["source"] == "research_dataset"
    assert "dataset penelitian" in cached_response.json()["warning"].casefold()


def test_prediction_uses_model_result_and_persists_history(client, monkeypatch):
    research = load_research_history("ADRO", "5y")
    snapshot = MarketSnapshot(
        symbol="ADRO",
        source="research_dataset",
        data_as_of=research["date"].max().date(),
        warning="Dataset penelitian historis.",
        frame=research,
    )
    monkeypatch.setattr(backend_api, "get_market_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(backend_api, "predict_price", lambda *_args, **_kwargs: 1500.0)

    response = client.post("/api/v1/predictions/ADRO?horizon_days=20")

    assert response.status_code == 201
    result = response.json()
    assert result["signal"] in {-1, 0, 1}
    assert result["predicted_price"] == 1500.0
    assert result["architecture"] == "LSTM regression"
    assert result["horizon_days"] == 20
    assert result["threshold_percent"] == 9

    history = client.get("/api/v1/predictions/history/ADRO?horizon_days=20")
    assert history.status_code == 200
    assert len(history.json()) == 1


@pytest.mark.parametrize("horizon_days", SUPPORTED_HORIZONS)
def test_saved_h5_model_returns_a_price_in_the_ticker_scale(horizon_days):
    research = load_research_history("ADRO", "5y")

    predicted_price = predict_price("ADRO", research["close"], horizon_days)

    assert np.isfinite(predicted_price)
    assert predicted_price > 0
    assert predicted_price < 100_000


def test_prediction_rejects_unsupported_horizon(client):
    response = client.post("/api/v1/predictions/ADRO?horizon_days=7")

    assert response.status_code == 422
