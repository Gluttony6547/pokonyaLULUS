"""FastAPI read-only app: same shape as Prog5's, Prog6's own data."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prog5 import config as prog5_config

from . import __version__, storage
from .refresh import SYMBOLS
from .storage import PolicyResult, Prediction


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.ensure_tables()
    yield


app = FastAPI(title="Prog6 Session-Relative Desk", version=__version__, lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


class HealthOut(BaseModel):
    status: str
    version: str
    db_backend: str
    prediction_rows: int
    policy_rows: int


class PolicyOut(BaseModel):
    symbol: str
    horizon_days: int
    policy: str
    hit_rate: float
    mae: float
    mape: float
    backtest_rows: int


class PredictionOut(BaseModel):
    symbol: str
    horizon_days: int
    data_as_of: date
    target_date: date | None
    predicted_relative_return: float
    expected_close: float
    last_close: float
    best_policy: str
    lstm_predicted_price: float | None
    lstm_delta_pct: float | None
    model_sha256: str | None


def get_session():
    with storage.session() as session:
        yield session


@app.get("/", tags=["system"])
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/health", response_model=HealthOut, tags=["system"])
def health(session: Session = Depends(get_session)) -> HealthOut:
    return HealthOut(
        status="ok",
        version=__version__,
        db_backend=storage.db_backend(),
        prediction_rows=session.scalar(select(func.count()).select_from(Prediction)) or 0,
        policy_rows=session.scalar(select(func.count()).select_from(PolicyResult)) or 0,
    )


@app.get("/api/v1/predictions/latest/{symbol}", response_model=list[PredictionOut])
def latest_predictions(symbol: str, session: Session = Depends(get_session)) -> list[PredictionOut]:
    normalized = symbol.strip().upper()
    if normalized not in SYMBOLS:
        raise HTTPException(status_code=404, detail=f"not a probed symbol: {symbol}")
    rows = session.scalars(
        select(Prediction)
        .where(Prediction.symbol == normalized)
        .order_by(Prediction.horizon_days, Prediction.data_as_of.desc())
    ).all()
    latest: dict[int, Prediction] = {}
    for row in rows:
        latest.setdefault(row.horizon_days, row)
    return [PredictionOut.model_validate(r) for r in (latest[h] for h in sorted(latest))]


@app.get("/api/v1/policies/{symbol}", response_model=list[PolicyOut])
def policies(symbol: str, session: Session = Depends(get_session)) -> list[PolicyOut]:
    normalized = symbol.strip().upper()
    if normalized not in SYMBOLS:
        raise HTTPException(status_code=404, detail=f"not a probed symbol: {symbol}")
    rows = session.scalars(select(PolicyResult).where(PolicyResult.symbol == normalized)).all()
    return [PolicyOut.model_validate(r) for r in rows]
