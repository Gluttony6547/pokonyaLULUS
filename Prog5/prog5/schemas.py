"""API response models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    requested_symbols: str
    horizons: str
    started_at: datetime
    finished_at: datetime | None
    summary: str | None


class StockOut(BaseModel):
    symbol: str
    is_research_ticker: bool
    last_price_date: date | None = None
    last_close: float | None = None


class PriceRow(BaseModel):
    price_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


class PriceResponse(BaseModel):
    symbol: str
    rows: list[PriceRow]
    latest_indicators: dict[str, float | None]


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    horizon_days: int
    data_as_of: date
    window_start_date: date
    window_size: int
    last_close: float
    predicted_price: float
    return_pct: float
    threshold_pct: float
    signal: int
    signal_label: str
    ood_z: float
    ood_flag: bool
    model_file: str
    model_sha256: str
    input_mean: float
    input_scale: float
    target_mean: float
    target_scale: float
    warnings: str | None
    created_at: datetime


class HealthOut(BaseModel):
    status: str
    version: str
    db_path: str
    storage_backend: str
    stocks: int
    price_rows: int
    indicator_rows: int
    prediction_rows: int
    artifacts: dict[str, int]
    last_run: RunOut | None
