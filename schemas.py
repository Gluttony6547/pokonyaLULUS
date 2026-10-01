from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StockResponse(BaseModel):
    symbol: str
    company_name: str | None
    sector: str | None


class PricePoint(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class IndicatorsResponse(BaseModel):
    sma_5: float | None
    sma_20: float | None
    sma_50: float | None
    ema_20: float | None
    rsi: float | None
    macd: float | None
    macd_signal: float | None


class MarketDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    source: str
    data_as_of: date
    warning: str | None
    prices: list[PricePoint]
    indicators: IndicatorsResponse


class PredictionResponse(BaseModel):
    id: int
    symbol: str
    prediction_date: date
    input_as_of: date
    horizon_days: int
    current_price: float
    predicted_price: float
    return_percent: float
    signal: Literal[-1, 0, 1]
    signal_label: str
    threshold_percent: float
    architecture: str
    feature_set: str
    data_source: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]
    available_models: int
    checked_at: datetime
