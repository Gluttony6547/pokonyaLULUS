"""Prog6's own tables, created inside whatever database Prog5 is configured for.

The tables are new names, so Prog5's schema and migrations are untouched.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator

from prog5 import db as prog5_db
from prog5 import config as prog5_config
from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PolicyResult(Base):
    """One fitted policy's backtest quality per (symbol, horizon)."""

    __tablename__ = "prog6_policies"
    __table_args__ = (
        UniqueConstraint("symbol", "horizon_days", "policy", name="uq_prog6_policies_tuple"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    policy: Mapped[str] = mapped_column(String(32), nullable=False)
    hit_rate: Mapped[float] = mapped_column(Float, nullable=False)
    mae: Mapped[float] = mapped_column(Float, nullable=False)
    mape: Mapped[float] = mapped_column(Float, nullable=False)
    backtest_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    fit_window: Mapped[int] = mapped_column(Integer, nullable=False)
    score_window: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Prediction(Base):
    """One relative-return prediction per (symbol, horizon, session)."""

    __tablename__ = "prog6_predictions"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "horizon_days", "data_as_of", name="uq_prog6_predictions_tuple"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    target_date: Mapped[date | None] = mapped_column(Date)
    predicted_relative_return: Mapped[float] = mapped_column(Float, nullable=False)
    expected_close: Mapped[float] = mapped_column(Float, nullable=False)
    last_close: Mapped[float] = mapped_column(Float, nullable=False)
    best_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    lstm_predicted_price: Mapped[float | None] = mapped_column(Float)
    lstm_delta_pct: Mapped[float | None] = mapped_column(Float)
    model_sha256: Mapped[str | None] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


def ensure_tables() -> None:
    """Create Prog6 tables in the Prog5 database idempotently."""
    engine = prog5_db.engine()
    Base.metadata.create_all(engine)


@contextmanager
def session() -> Iterator:
    """A Prog6 session on the same engine Prog5 resolves."""
    with prog5_db.session() as db_session:
        yield db_session


def load_closes(from_symbol: str, session) -> tuple[list, list[float]]:
    """Newest-first to session-safe order: (dates, closes) oldest first."""
    from prog5.models import StockPrice
    from sqlalchemy import select

    rows = session.scalars(
        select(StockPrice)
        .where(StockPrice.symbol == from_symbol)
        .order_by(StockPrice.price_date.desc())
        .limit(300)  # overlays for about 14 months of sessions, 5x more than needed
    ).all()
    rows.reverse()
    return [row.price_date for row in rows], [float(row.close) for row in rows]


def latest_lstm_prediction(symbol: str, horizon: int, session) -> tuple[float | None, str | None]:
    """The most recent Prog5 LSTM prediction for one (symbol, horizon)."""
    from prog5.models import Prediction
    from sqlalchemy import select

    row = session.scalars(
        select(Prediction)
        .where(Prediction.symbol == symbol, Prediction.horizon_days == horizon)
        .order_by(Prediction.data_as_of.desc(), Prediction.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return float(row.predicted_price), row.model_sha256


def db_backend() -> str:
    return prog5_db.engine().dialect.name
