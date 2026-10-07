"""Idempotent writes and reads for the SQLite store."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .indicators import INDICATOR_COLUMNS
from .models import Prediction, RefreshTelemetry, Stock, StockPrice, TechnicalIndicator


def _insert(session: Session, model):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError(f"Unsupported database dialect: {dialect}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_stock(session: Session, symbol: str) -> None:
    session.merge(Stock(symbol=symbol, is_research_ticker=True))


def store_prices(session: Session, symbol: str, frame: pd.DataFrame, source: str) -> int:
    ensure_stock(session, symbol)
    records = [
        {
            "symbol": symbol,
            "price_date": row.date,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": int(row.volume),
            "source": source,
            "fetched_at": _utcnow(),
        }
        for row in frame.itertuples(index=False)
    ]
    if not records:
        return 0
    statement = _insert(session, StockPrice).values(records)
    statement = statement.on_conflict_do_update(
        index_elements=["symbol", "price_date"],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
            "source": statement.excluded.source,
            "fetched_at": statement.excluded.fetched_at,
        },
    )
    session.execute(statement)
    return len(records)


def store_indicators(session: Session, symbol: str, frame: pd.DataFrame) -> int:
    ensure_stock(session, symbol)
    records = []
    for row in frame.itertuples(index=False):
        record: dict[str, object] = {
            "symbol": symbol,
            "price_date": row.price_date,
            "computed_at": _utcnow(),
        }
        for column in INDICATOR_COLUMNS:
            value = getattr(row, column)
            record[column] = None if value is None or pd.isna(value) else float(value)
        records.append(record)
    if not records:
        return 0
    statement = _insert(session, TechnicalIndicator).values(records)
    statement = statement.on_conflict_do_update(
        index_elements=["symbol", "price_date"],
        set_={column: getattr(statement.excluded, column) for column in (*INDICATOR_COLUMNS, "computed_at")},
    )
    session.execute(statement)
    return len(records)


def store_prediction(session: Session, record: dict[str, object]) -> None:
    """Insert or refresh one prediction row, keyed on (symbol, horizon, data_as_of)."""
    payload = dict(record)
    payload["created_at"] = _utcnow()
    statement = _insert(session, Prediction).values(**payload)
    update_columns = {
        column: getattr(statement.excluded, column)
        for column in (
            "run_id",
            "target_date",
            "window_start_date",
            "window_size",
            "last_close",
            "predicted_price",
            "return_pct",
            "threshold_pct",
            "signal",
            "signal_label",
            "ood_z",
            "ood_flag",
            "model_file",
            "model_sha256",
            "input_mean",
            "input_scale",
            "target_mean",
            "target_scale",
            "warnings",
            "created_at",
        )
    }
    statement = statement.on_conflict_do_update(
        index_elements=["symbol", "horizon_days", "data_as_of"],
        set_=update_columns,
    )
    session.execute(statement)


def latest_price_date(session: Session, symbol: str) -> date | None:
    return session.scalar(
        select(StockPrice.price_date)
        .where(StockPrice.symbol == symbol)
        .order_by(StockPrice.price_date.desc())
        .limit(1)
    )


def record_successful_refresh(
    session: Session, source: str, key: str, success_at: datetime | None
) -> None:
    """Upsert the single telemetry row for (source, key)."""
    statement = _insert(session, RefreshTelemetry).values(
        source=source, key=key, success_at=success_at
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["source", "key"],
            set_={"success_at": success_at, "updated_at": _utcnow()},
        )
    )


def last_successful_refresh_at(session: Session, source: str, key: str) -> datetime | None:
    """When the (source, key) refresh last completed, or None if it never has."""
    return session.scalar(
        select(RefreshTelemetry.success_at).where(
            RefreshTelemetry.source == source, RefreshTelemetry.key == key
        )
    )
