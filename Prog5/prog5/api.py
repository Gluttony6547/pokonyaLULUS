"""Read-only API. Writing happens only through the refresh pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import __version__, config, db
from .indicators import INDICATOR_COLUMNS
from .model_registry import artifact_inventory
from .models import Prediction, RefreshRun, Stock, StockPrice, TechnicalIndicator
from .schemas import HealthOut, PredictionOut, PriceResponse, PriceRow, RunOut, StockOut
from .snapshot import import_snapshot

DESCRIPTION = (
    "Prediction service around the lecturer's saved LSTM price models. "
    "Rows are written by the refresh pipeline; this API only reads them."
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if db.engine().dialect.name == "postgresql":
        snapshot = config.snapshot_path()
        if not snapshot.is_file():
            raise RuntimeError(f"Production seed snapshot is missing: {snapshot}")
        imported = import_snapshot(snapshot, only_if_empty=True)
        if sum(imported.values()):
            print(f"Prog5 seeded empty PostgreSQL storage from bundled snapshot: {imported}")
    yield


app = FastAPI(
    title="Prog5 Stock Signal API", version=__version__, description=DESCRIPTION, lifespan=lifespan
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
# The browser UI is plain static files served by this same process. It reads
# only the endpoints below, so it adds no new data path.
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


def get_session() -> Iterator[Session]:
    with db.session() as session:
        yield session


def _require_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized not in config.SUPPORTED_SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"No research artifacts for '{normalized}'.",
        )
    return normalized


@app.get("/", tags=["system"])
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/health", response_model=HealthOut, tags=["system"])
def health(session: Session = Depends(get_session)) -> HealthOut:
    storage_backend = "postgresql" if db.engine().dialect.name == "postgresql" else "sqlite"
    last_run = session.scalars(
        select(RefreshRun).order_by(RefreshRun.id.desc()).limit(1)
    ).first()
    return HealthOut(
        status="ok",
        version=__version__,
        db_path="PostgreSQL" if storage_backend == "postgresql" else str(config.db_path()),
        storage_backend=storage_backend,
        stocks=session.scalar(select(func.count()).select_from(Stock)) or 0,
        price_rows=session.scalar(select(func.count()).select_from(StockPrice)) or 0,
        indicator_rows=session.scalar(select(func.count()).select_from(TechnicalIndicator)) or 0,
        prediction_rows=session.scalar(select(func.count()).select_from(Prediction)) or 0,
        artifacts=artifact_inventory(),
        last_run=RunOut.model_validate(last_run) if last_run else None,
    )


@app.get("/api/v1/stocks", response_model=list[StockOut], tags=["market data"])
def list_stocks(session: Session = Depends(get_session)) -> list[StockOut]:
    stocks = session.scalars(select(Stock).order_by(Stock.symbol)).all()
    result: list[StockOut] = []
    for stock in stocks:
        last_price = session.scalars(
            select(StockPrice)
            .where(StockPrice.symbol == stock.symbol)
            .order_by(StockPrice.price_date.desc())
            .limit(1)
        ).first()
        result.append(
            StockOut(
                symbol=stock.symbol,
                is_research_ticker=stock.is_research_ticker,
                last_price_date=last_price.price_date if last_price else None,
                last_close=last_price.close if last_price else None,
            )
        )
    return result


@app.get("/api/v1/prices/{symbol}", response_model=PriceResponse, tags=["market data"])
def get_prices(
    symbol: str,
    limit: int = Query(default=120, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> PriceResponse:
    normalized = _require_symbol(symbol)
    rows = session.scalars(
        select(StockPrice)
        .where(StockPrice.symbol == normalized)
        .order_by(StockPrice.price_date.desc())
        .limit(limit)
    ).all()
    latest_indicator = session.scalars(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.symbol == normalized)
        .order_by(TechnicalIndicator.price_date.desc())
        .limit(1)
    ).first()
    indicators = (
        {column: getattr(latest_indicator, column) for column in INDICATOR_COLUMNS}
        if latest_indicator
        else {column: None for column in INDICATOR_COLUMNS}
    )
    return PriceResponse(
        symbol=normalized,
        rows=[
            PriceRow(
                price_date=row.price_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                source=row.source,
            )
            for row in reversed(rows)
        ],
        latest_indicators=indicators,
    )


@app.get("/api/v1/predictions/{symbol}", response_model=list[PredictionOut], tags=["predictions"])
def list_predictions(
    symbol: str,
    horizon_days: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[PredictionOut]:
    normalized = _require_symbol(symbol)
    query = select(Prediction).where(Prediction.symbol == normalized)
    if horizon_days is not None:
        if horizon_days not in config.HORIZONS:
            raise HTTPException(status_code=422, detail=f"horizon_days must be one of {config.HORIZONS}")
        query = query.where(Prediction.horizon_days == horizon_days)
    rows = session.scalars(
        query.order_by(Prediction.data_as_of.desc(), Prediction.id.desc()).limit(limit)
    ).all()
    return [PredictionOut.model_validate(row) for row in rows]


@app.get(
    "/api/v1/predictions/latest/{symbol}",
    response_model=list[PredictionOut],
    tags=["predictions"],
)
def latest_predictions(
    symbol: str, session: Session = Depends(get_session)
) -> list[PredictionOut]:
    normalized = _require_symbol(symbol)
    rows = session.scalars(
        select(Prediction)
        .where(Prediction.symbol == normalized)
        .order_by(Prediction.data_as_of.desc(), Prediction.id.desc())
    ).all()
    latest: dict[int, Prediction] = {}
    for row in rows:
        latest.setdefault(row.horizon_days, row)
    return [PredictionOut.model_validate(latest[horizon]) for horizon in sorted(latest)]


@app.get("/api/v1/runs", response_model=list[RunOut], tags=["system"])
def list_runs(
    limit: int = Query(default=20, ge=1, le=200), session: Session = Depends(get_session)
) -> list[RunOut]:
    rows = session.scalars(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(limit)).all()
    return [RunOut.model_validate(row) for row in rows]
