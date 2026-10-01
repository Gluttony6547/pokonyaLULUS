import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from market_data import (
    SUPPORTED_SYMBOLS,
    MarketDataUnavailable,
    add_indicators,
    ensure_supported_symbol,
    get_market_snapshot,
)
from model_service import (
    HORIZON_DAYS,
    RETURN_THRESHOLDS,
    SUPPORTED_HORIZONS,
    SIGNAL_LABELS,
    ModelInferenceError,
    ModelUnavailable,
    available_model_count,
    classify_return,
    predict_price,
)
from models import ModelVersion, Prediction, PredictionRequest, Stock
from schemas import (
    HealthResponse,
    IndicatorsResponse,
    MarketDataResponse,
    PredictionResponse,
    PricePoint,
    StockResponse,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
PROJECT_DIRECTORY = Path(__file__).resolve().parent
STATIC_DIRECTORY = PROJECT_DIRECTORY / "static"
MODEL_VERSION_PREFIX = "target-{}-h5-v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for symbol in SUPPORTED_SYMBOLS:
            if db.get(Stock, symbol) is None:
                db.add(Stock(symbol=symbol))
            for horizon_days in SUPPORTED_HORIZONS:
                version = MODEL_VERSION_PREFIX.format(horizon_days)
                if db.scalar(
                    select(ModelVersion).where(
                        ModelVersion.name == f"LSTM-{symbol}",
                        ModelVersion.version == version,
                    )
                ) is None:
                    db.add(
                        ModelVersion(
                            name=f"LSTM-{symbol}",
                            version=version,
                            architecture="LSTM regression",
                            artifact_path=f"models/LSTM_{symbol}_Target_{horizon_days}.h5",
                            feature_set=f"{horizon_days} harga penutupan harian",
                            horizon_days=horizon_days,
                            is_production=True,
                        )
                    )
        db.commit()
    yield


app = FastAPI(
    title="Stock Signal Prediction",
    description="Dashboard penelitian saham IDX dengan prediksi LSTM untuk horizon 1, 5, 10, 20, atau 50 hari.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIRECTORY / "index.html")


def _supported_symbol(symbol: str) -> str:
    try:
        return ensure_supported_symbol(symbol)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _prediction_response(db: Session, prediction: Prediction) -> PredictionResponse:
    model_version = db.get(ModelVersion, prediction.model_version_id)
    request = db.get(PredictionRequest, prediction.request_id)
    if model_version is None or request is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Relasi model atau permintaan prediksi tidak ditemukan.",
        )

    price_source = prediction.feature_snapshot.get("data_source", "unknown")
    signal_label = SIGNAL_LABELS.get(prediction.signal)
    if signal_label is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sinyal tersimpan memiliki kode yang tidak dikenal.",
        )

    return PredictionResponse(
        id=prediction.id,
        symbol=prediction.symbol,
        prediction_date=prediction.prediction_date,
        input_as_of=prediction.input_as_of,
        horizon_days=prediction.horizon_days,
        current_price=prediction.current_price,
        predicted_price=prediction.predicted_price,
        return_percent=prediction.return_percent,
        signal=prediction.signal,
        signal_label=signal_label,
        threshold_percent=prediction.threshold_percent,
        architecture=model_version.architecture,
        feature_set=model_version.feature_set,
        data_source=price_source,
        created_at=prediction.created_at,
    )


@app.get("/api/v1/health", response_model=HealthResponse, tags=["System"])
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database tidak dapat diakses.",
        ) from error

    return HealthResponse(
        status="ok",
        database="connected",
        available_models=available_model_count(),
        checked_at=datetime.now(timezone.utc),
    )


@app.get("/api/v1/stocks", response_model=list[StockResponse], tags=["Stocks"])
def list_stocks(db: Session = Depends(get_db)):
    stocks = db.scalars(select(Stock).where(Stock.is_active.is_(True)).order_by(Stock.symbol)).all()
    return stocks


@app.get(
    "/api/v1/market-data/{symbol}",
    response_model=MarketDataResponse,
    tags=["Market data"],
)
def market_data(
    symbol: str,
    period: str = Query(default="1y", pattern="^(6mo|1y|5y)$"),
    db: Session = Depends(get_db),
):
    normalized_symbol = _supported_symbol(symbol)
    try:
        snapshot = get_market_snapshot(db, normalized_symbol, period)
    except MarketDataUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    enriched = add_indicators(snapshot.frame)
    prices = [
        PricePoint(
            date=pd.Timestamp(row.date).date(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=int(row.volume),
        )
        for row in enriched.itertuples(index=False)
    ]
    latest = enriched.iloc[-1]
    indicator_columns = ("sma_5", "sma_20", "sma_50", "ema_20", "rsi", "macd", "macd_signal")
    indicators = {
        column: float(latest[column]) if pd.notna(latest[column]) else None
        for column in indicator_columns
    }

    return MarketDataResponse(
        symbol=normalized_symbol,
        source=snapshot.source,
        data_as_of=snapshot.data_as_of,
        warning=snapshot.warning,
        prices=prices,
        indicators=IndicatorsResponse(**indicators),
    )


@app.post(
    "/api/v1/predictions/{symbol}",
    response_model=PredictionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Predictions"],
)
def create_prediction(
    symbol: str,
    horizon_days: int = Query(default=HORIZON_DAYS),
    db: Session = Depends(get_db),
):
    normalized_symbol = _supported_symbol(symbol)
    if horizon_days not in SUPPORTED_HORIZONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Horizon harus salah satu dari {', '.join(map(str, SUPPORTED_HORIZONS))} hari.",
        )
    request = PredictionRequest(symbol=normalized_symbol, status="pending")
    db.add(request)
    db.flush()

    try:
        snapshot = get_market_snapshot(db, normalized_symbol, "5y")
        predicted_price = predict_price(
            normalized_symbol, snapshot.frame["close"], horizon_days
        )
        current_price = float(snapshot.frame["close"].iloc[-1])
        signal, return_percent = classify_return(
            predicted_price, current_price, horizon_days
        )
        model_version = db.scalar(
            select(ModelVersion).where(
                ModelVersion.name == f"LSTM-{normalized_symbol}",
                ModelVersion.version == MODEL_VERSION_PREFIX.format(horizon_days),
            )
        )
        if model_version is None:
            raise ModelUnavailable(f"Versi model untuk {normalized_symbol} belum terdaftar.")
    except (MarketDataUnavailable, ModelUnavailable, ModelInferenceError) as error:
        request.status = "failed"
        request.error_message = str(error)
        db.commit()
        logger.warning("Prediction request failed for %s: %s", normalized_symbol, error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    prediction = Prediction(
        request_id=request.id,
        symbol=normalized_symbol,
        model_version_id=model_version.id,
        prediction_date=date.today(),
        input_as_of=snapshot.data_as_of,
        horizon_days=horizon_days,
        current_price=current_price,
        predicted_price=predicted_price,
        return_percent=return_percent,
        signal=signal,
        threshold_percent=RETURN_THRESHOLDS[horizon_days] * 100,
        feature_snapshot={
            "feature_set": model_version.feature_set,
            "data_source": snapshot.source,
            "threshold_percent": RETURN_THRESHOLDS[horizon_days] * 100,
        },
    )
    request.status = "completed"
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return _prediction_response(db, prediction)


@app.get(
    "/api/v1/predictions/latest/{symbol}",
    response_model=PredictionResponse,
    tags=["Predictions"],
)
def latest_prediction(
    symbol: str,
    horizon_days: int = Query(default=HORIZON_DAYS),
    db: Session = Depends(get_db),
):
    normalized_symbol = _supported_symbol(symbol)
    if horizon_days not in SUPPORTED_HORIZONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Horizon harus salah satu dari {', '.join(map(str, SUPPORTED_HORIZONS))} hari.",
        )
    prediction = db.scalar(
        select(Prediction)
        .where(
            Prediction.symbol == normalized_symbol,
            Prediction.horizon_days == horizon_days,
        )
        .order_by(Prediction.created_at.desc())
        .limit(1)
    )
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Belum ada prediksi tersimpan untuk {normalized_symbol}.",
        )
    return _prediction_response(db, prediction)


@app.get(
    "/api/v1/predictions/history/{symbol}",
    response_model=list[PredictionResponse],
    tags=["Predictions"],
)
def prediction_history(
    symbol: str,
    horizon_days: int = Query(default=HORIZON_DAYS),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    normalized_symbol = _supported_symbol(symbol)
    if horizon_days not in SUPPORTED_HORIZONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Horizon harus salah satu dari {', '.join(map(str, SUPPORTED_HORIZONS))} hari.",
        )
    predictions = db.scalars(
        select(Prediction)
        .where(
            Prediction.symbol == normalized_symbol,
            Prediction.horizon_days == horizon_days,
        )
        .order_by(Prediction.created_at.desc())
        .limit(limit)
    ).all()
    return [_prediction_response(db, prediction) for prediction in predictions]
