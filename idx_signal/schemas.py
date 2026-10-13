"""API response models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StockOut(BaseModel):
    symbol: str
    name: str
    sector: str | None = None
    is_active: bool
    last_price_date: date | None = None
    last_close: float | None = None


class UpdateLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_at: datetime
    trigger_type: str
    status: str
    rows_inserted: int
    message: str | None = None


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    horizon_days: int
    trained_at: datetime
    data_until: date
    metrics: dict
    config: dict
    artifact_path: str
    artifact_sha256: str
    is_active: bool


class SignalOut(BaseModel):
    symbol: str
    horizon_days: int
    data_as_of: date
    target_date: date | None = None
    signal: str
    last_close: float
    predicted_price: float | None = None
    return_pct: float
    threshold_pct: float
    ood_z: float
    ood_flag: bool
    warnings: str | None = None
    created_at: datetime
    model_version_id: int
    model_artifact: str | None = None
    model_metrics: dict | None = None


class SignalsResponse(BaseModel):
    symbol: str
    name: str
    last_price_date: date | None = None
    last_close: float | None = None
    signals: list[SignalOut]


class PriceRow(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceResponse(BaseModel):
    symbol: str
    rows: list[PriceRow]
    context: dict[str, float | None]


class TrainingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    horizon_days: int
    status: str
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    model_version_id: int | None = None


class TrainingRequest(BaseModel):
    symbol: str
    horizon_days: int
    force: bool = False


class TrainingAccepted(BaseModel):
    reused: bool
    message: str
    job: TrainingJobOut | None = None
    model_version: ModelVersionOut | None = None


class HealthOut(BaseModel):
    status: str
    version: str
    storage_backend: str
    stocks: int
    price_rows: int
    prediction_rows: int
    artifacts: dict[str, int]
    last_update: UpdateLogOut | None = None
    # The scheduled slot that is currently waiting to run, if one is overdue.
    pending_slot: datetime | None = None
