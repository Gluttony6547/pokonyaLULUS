"""Read-mostly HTTP API plus the dashboard it serves.

Writes are limited to the two actions a user actually asks for: refreshing the
market data, and queueing a training run. Everything else the dashboard shows
was written by the refresh pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from secrets import compare_digest

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import __version__, config, db, training
from .historical import (
    HistoricalDateError,
    first_usable_reference_date as usable_reference_date,
    reference_bounds,
    signals_for_date,
)
from .indicators import compute_indicators
from .market_data import MarketDataUnavailable, fetch_intraday_quote
from .model_registry import ModelUnavailable, artifact_filename, artifact_inventory
from .models import DailyPrice, ModelVersion, Prediction, Stock
from .refresh import RefreshInProgress, refresh
from .scheduler import due_slot, last_success_utc, run_scheduled
from .schemas import (
    HealthOut,
    HistoricalSignalOut,
    HistoricalSignalsOut,
    IntradayQuoteOut,
    ModelVersionOut,
    PriceResponse,
    PriceRow,
    ScorecardOut,
    SignalOut,
    SignalsResponse,
    StockOut,
    TrainingAccepted,
    TrainingJobOut,
    TrainingRequest,
    UpdateLogOut,
)
from .storage import (
    recent_training_jobs,
    recent_updates,
    price_frame,
)
from .models import DataUpdateLog

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Buy, hold, and sell signals from the saved LSTM price models for ten IDX "
    "tickers at horizons of 1, 5, 10, 20, and 50 sessions. Decision support "
    "only: the service does not place orders."
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    from .storage import ensure_reference_data

    db.init_db()
    with db.session() as session:
        ensure_reference_data(session)
    yield


app = FastAPI(title="Sinyal IDX API", version=__version__, description=DESCRIPTION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_session() -> Iterator[Session]:
    with db.session() as session:
        yield session


def _require_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized not in config.SUPPORTED_SYMBOLS:
        raise HTTPException(
            status_code=404, detail=f"{normalized} bukan emiten yang didukung."
        )
    return normalized


def _require_horizon(horizon_days: int) -> int:
    if horizon_days not in config.HORIZONS:
        raise HTTPException(
            status_code=422, detail=f"horizon_days harus salah satu dari {config.HORIZONS}."
        )
    return horizon_days


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/health", response_model=HealthOut, tags=["system"])
def health(session: Session = Depends(get_session)) -> HealthOut:
    updates = recent_updates(session, limit=1)
    pending_slot = due_slot(datetime.now(timezone.utc), last_success_utc())
    return HealthOut(
        status="ok",
        version=__version__,
        storage_backend=db.storage_backend(),
        stocks=session.scalar(select(func.count()).select_from(Stock)) or 0,
        price_rows=session.scalar(select(func.count()).select_from(DailyPrice)) or 0,
        prediction_rows=session.scalar(select(func.count()).select_from(Prediction)) or 0,
        artifacts=artifact_inventory(),
        last_update=UpdateLogOut.model_validate(updates[0]) if updates else None,
        pending_slot=pending_slot,
    )


@app.get("/api/v1/stocks", response_model=list[StockOut], tags=["market data"])
def list_stocks(session: Session = Depends(get_session)) -> list[StockOut]:
    # One window query for every ticker's newest close. A per-ticker lookup
    # would add a round trip each against a remote database.
    newest = (
        select(
            DailyPrice.symbol,
            DailyPrice.trade_date,
            DailyPrice.close,
            func.row_number()
            .over(partition_by=DailyPrice.symbol, order_by=DailyPrice.trade_date.desc())
            .label("rank"),
        )
        .subquery()
    )
    latest = {
        row.symbol: (row.trade_date, row.close)
        for row in session.execute(select(newest).where(newest.c.rank == 1))
    }
    oldest = dict(
        session.execute(
            select(DailyPrice.symbol, func.min(DailyPrice.trade_date)).group_by(DailyPrice.symbol)
        ).all()
    )
    counts = dict(
        session.execute(
            select(DailyPrice.symbol, func.count()).group_by(DailyPrice.symbol)
        ).all()
    )
    rows: list[StockOut] = []
    for stock in session.scalars(select(Stock).order_by(Stock.symbol)):
        last_date, last_close = latest.get(stock.symbol, (None, None))
        first_date = oldest.get(stock.symbol)
        rows.append(
            StockOut(
                symbol=stock.symbol,
                name=stock.name,
                sector=stock.sector,
                is_active=stock.is_active,
                first_price_date=first_date,
                last_price_date=last_date,
                last_close=float(last_close) if last_close is not None else None,
                earliest_reference_date=(
                    reference_bounds(first_date, last_date)[0]
                    if first_date is not None and last_date is not None
                    else None
                ),
                first_usable_reference_date=(
                    usable_reference_date(
                        session, stock.symbol, (first_date, last_date)
                    )
                    if first_date is not None and last_date is not None
                    else None
                ),
                price_session_count=counts.get(stock.symbol, 0),
            )
        )
    return rows


@app.get("/api/v1/quotes/{symbol}", response_model=IntradayQuoteOut, tags=["market data"])
def intraday_quote(symbol: str) -> IntradayQuoteOut:
    normalized = _require_symbol(symbol)
    try:
        price, observed_at = fetch_intraday_quote(normalized)
    except MarketDataUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return IntradayQuoteOut(symbol=normalized, price=price, observed_at=observed_at)


@app.get("/api/v1/stocks/{symbol}/signals", response_model=SignalsResponse, tags=["signals"])
def signals(symbol: str, session: Session = Depends(get_session)) -> SignalsResponse:
    normalized = _require_symbol(symbol)
    stock = session.get(Stock, normalized)
    rows = session.scalars(
        select(Prediction)
        .where(Prediction.symbol == normalized)
        .order_by(Prediction.data_as_of.desc(), Prediction.id.desc())
    ).all()
    latest: dict[int, Prediction] = {}
    for row in rows:
        latest.setdefault(row.horizon_days, row)

    versions = {
        version.id: version
        for version in session.scalars(
            select(ModelVersion).where(ModelVersion.symbol == normalized)
        )
    }
    price_date = session.scalar(
        select(func.max(DailyPrice.trade_date)).where(DailyPrice.symbol == normalized)
    )
    last_close = None
    if price_date is not None:
        last_close = session.scalar(
            select(DailyPrice.close).where(
                DailyPrice.symbol == normalized, DailyPrice.trade_date == price_date
            )
        )

    signals_out: list[SignalOut] = []
    for horizon in sorted(latest):
        row = latest[horizon]
        version = versions.get(row.model_version_id)
        signals_out.append(
            SignalOut(
                symbol=row.symbol,
                horizon_days=row.horizon_days,
                data_as_of=row.data_as_of,
                target_date=row.target_date,
                signal=row.signal,
                last_close=float(row.last_close),
                predicted_price=float(row.predicted_price) if row.predicted_price is not None else None,
                return_pct=float(row.return_pct),
                threshold_pct=float(row.threshold_pct),
                ood_z=float(row.ood_z),
                ood_flag=row.ood_flag,
                warnings=row.warnings,
                created_at=row.created_at,
                model_version_id=row.model_version_id,
                model_artifact=artifact_filename(version.artifact_path) if version else None,
                model_metrics=version.metrics if version else None,
            )
        )

    return SignalsResponse(
        symbol=normalized,
        name=stock.name if stock else normalized,
        last_price_date=price_date,
        last_close=float(last_close) if last_close is not None else None,
        signals=signals_out,
    )


@app.get(
    "/api/v1/stocks/{symbol}/signals/historical",
    response_model=HistoricalSignalsOut,
    tags=["signals"],
)
def historical_signals(
    symbol: str,
    reference_date: str = Query(alias="date", description="Tanggal acuan, format YYYY-MM-DD"),
    session: Session = Depends(get_session),
) -> HistoricalSignalsOut:
    """Recompute the five horizons from the closes up to a chosen session.

    Kept apart from the stored-signal endpoint so that one keeps returning
    exactly what the refresh pipeline wrote.
    """
    normalized = _require_symbol(symbol)
    try:
        parsed = date.fromisoformat(reference_date)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"Tanggal acuan harus berformat YYYY-MM-DD, bukan {reference_date!r}.",
        ) from error

    try:
        result = signals_for_date(session, normalized, parsed)
    except HistoricalDateError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ModelUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    stock = session.get(Stock, normalized)
    return HistoricalSignalsOut(
        symbol=normalized,
        name=stock.name if stock else normalized,
        reference_date=result.reference_date,
        reference_close=result.reference_close,
        first_price_date=result.first_price_date,
        last_price_date=result.last_price_date,
        earliest_reference_date=result.earliest_reference_date,
        first_usable_reference_date=result.first_usable_reference_date,
        signals=[HistoricalSignalOut.model_validate(row) for row in result.signals],
        scorecard=ScorecardOut(
            realized=result.scorecard.realized,
            pending=result.scorecard.pending,
            no_price=result.scorecard.no_price,
            corporate_action=result.scorecard.corporate_action,
            direction_correct=result.scorecard.direction_correct,
            direction_total=result.scorecard.direction_total,
            mean_abs_error_pct=result.scorecard.mean_abs_error_pct,
        ),
        warnings=result.warnings,
    )


@app.get("/api/v1/prices/{symbol}", response_model=PriceResponse, tags=["market data"])
def prices(
    symbol: str,
    limit: int = Query(default=180, ge=20, le=1000),
    session: Session = Depends(get_session),
) -> PriceResponse:
    normalized = _require_symbol(symbol)
    frame = price_frame(session, normalized, limit=limit)
    if frame.empty:
        return PriceResponse(symbol=normalized, rows=[], context={})
    indicators = compute_indicators(frame)
    last = indicators.iloc[-1]
    context = {
        column: (float(last[column]) if last[column] == last[column] else None)
        for column in ("sma_20", "sma_50", "rsi", "macd", "upperband", "lowerband")
    }
    return PriceResponse(
        symbol=normalized,
        rows=[
            PriceRow(
                trade_date=row.date,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=int(row.volume),
            )
            for row in frame.itertuples(index=False)
        ],
        context=context,
    )


@app.get(
    "/api/v1/predictions/{symbol}", response_model=list[SignalOut], tags=["signals"]
)
def prediction_history(
    symbol: str,
    horizon_days: int | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[SignalOut]:
    normalized = _require_symbol(symbol)
    query = select(Prediction).where(Prediction.symbol == normalized)
    if horizon_days is not None:
        query = query.where(Prediction.horizon_days == _require_horizon(horizon_days))
    rows = session.scalars(
        query.order_by(Prediction.data_as_of.desc(), Prediction.id.desc()).limit(limit)
    ).all()
    versions = {
        version.id: artifact_filename(version.artifact_path)
        for version in session.scalars(
            select(ModelVersion).where(ModelVersion.symbol == normalized)
        )
    }
    return [
        SignalOut(
            symbol=row.symbol,
            horizon_days=row.horizon_days,
            data_as_of=row.data_as_of,
            target_date=row.target_date,
            signal=row.signal,
            last_close=float(row.last_close),
            predicted_price=float(row.predicted_price) if row.predicted_price is not None else None,
            return_pct=float(row.return_pct),
            threshold_pct=float(row.threshold_pct),
            ood_z=float(row.ood_z),
            ood_flag=row.ood_flag,
            warnings=row.warnings,
            created_at=row.created_at,
            model_version_id=row.model_version_id,
            model_artifact=versions.get(row.model_version_id),
            model_metrics=None,
        )
        for row in rows
    ]


@app.get(
    "/api/v1/model-versions/{symbol}", response_model=list[ModelVersionOut], tags=["models"]
)
def model_versions(
    symbol: str,
    horizon_days: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[ModelVersionOut]:
    normalized = _require_symbol(symbol)
    query = select(ModelVersion).where(ModelVersion.symbol == normalized)
    if horizon_days is not None:
        query = query.where(ModelVersion.horizon_days == _require_horizon(horizon_days))
    rows = session.scalars(
        query.order_by(ModelVersion.horizon_days, ModelVersion.trained_at.desc())
    ).all()
    return [ModelVersionOut.model_validate(row) for row in rows]


@app.post(
    "/api/v1/model-versions/{version_id}/activate",
    response_model=ModelVersionOut,
    tags=["models"],
)
def activate_model_version(
    version_id: int, session: Session = Depends(get_session)
) -> ModelVersionOut:
    try:
        version = training.activate_version(session, version_id)
    except training.TrainingUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return ModelVersionOut.model_validate(version)


@app.get("/api/v1/cron/refresh", tags=["system"])
def cron_refresh(authorization: str | None = Header(default=None)) -> dict:
    """Scheduled entry point for an external scheduler.

    Hosting that scales to zero cannot run the in-process scheduler loop, so a
    cron trigger calls this instead. It is the same due check and the same
    refresh the `schedule` command runs, which keeps one data path. Without a
    configured CRON_SECRET the endpoint refuses rather than exposing a public
    trigger that starts a full fetch.
    """
    expected = config.cron_secret()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET belum diatur, jadi jadwal otomatis tidak dijalankan.",
        )
    if not compare_digest(authorization or "", f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="Token jadwal tidak cocok.")

    outcome = run_scheduled()
    return {
        "ran": outcome.ran,
        "reason": outcome.reason,
        "attempts": outcome.attempts,
        "log_id": outcome.report.log_id if outcome.report else None,
    }


@app.get("/api/v1/update-logs", response_model=list[UpdateLogOut], tags=["system"])
def update_logs(
    limit: int = Query(default=12, ge=1, le=100), session: Session = Depends(get_session)
) -> list[UpdateLogOut]:
    return [UpdateLogOut.model_validate(row) for row in recent_updates(session, limit)]


@app.post("/api/v1/update-logs/refresh", response_model=UpdateLogOut, tags=["system"])
def trigger_refresh(
    symbol: str | None = Query(default=None), session: Session = Depends(get_session)
) -> UpdateLogOut:
    """Manual data update (UC-06). Runs the same pipeline the scheduler runs."""
    symbols = (_require_symbol(symbol),) if symbol else config.SUPPORTED_SYMBOLS
    try:
        report = refresh(symbols, horizons=config.HORIZONS, kind="manual")
    except RefreshInProgress as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if report.status == "failed":
        detail = report.message or "Pembaruan data gagal."
        raise HTTPException(status_code=502, detail=f"{detail} " + "; ".join(report.warnings[:3]))
    entry = session.get(DataUpdateLog, report.log_id)
    if entry is None:
        raise HTTPException(
            status_code=500, detail="Pembaruan selesai tetapi baris lognya tidak ditemukan."
        )
    return UpdateLogOut.model_validate(entry)


@app.get("/api/v1/training-jobs", response_model=list[TrainingJobOut], tags=["models"])
def training_jobs(
    limit: int = Query(default=12, ge=1, le=100), session: Session = Depends(get_session)
) -> list[TrainingJobOut]:
    return [TrainingJobOut.model_validate(row) for row in recent_training_jobs(session, limit)]


@app.post("/api/v1/training-jobs", response_model=TrainingAccepted, tags=["models"])
def queue_training(
    payload: TrainingRequest = Body(...), session: Session = Depends(get_session)
) -> TrainingAccepted:
    """Start a training run, or reuse the version that already covers the pair."""
    symbol = _require_symbol(payload.symbol)
    horizon = _require_horizon(payload.horizon_days)
    job, existing = training.queue_training_job(session, symbol, horizon, force=payload.force)
    if job is None:
        return TrainingAccepted(
            reused=True,
            message=(
                f"{symbol} T{horizon} sudah punya model aktif, jadi tidak dilatih ulang. "
                "Centang latih ulang bila memang ingin versi baru."
            ),
            model_version=ModelVersionOut.model_validate(existing) if existing else None,
        )
    session.commit()
    training.start_background_worker()
    return TrainingAccepted(
        reused=False,
        message=f"Pelatihan {symbol} T{horizon} masuk antrean. Statusnya muncul di bawah.",
        job=TrainingJobOut.model_validate(job),
    )


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):  # pragma: no cover - framework-level safety net
    logger.exception("Unhandled error: %s", exc)
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500, content={"detail": "Terjadi galat di sisi layanan. Coba lagi sebentar."}
    )

