"""Idempotent reads and writes over the PDM tables."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import (
    DataUpdateLog,
    DailyPrice,
    MarketHoliday,
    ModelVersion,
    Prediction,
    Stock,
    TrainingJob,
)
from .seed import MARKET_HOLIDAYS, STOCKS


def _insert(session: Session, model):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError(f"Unsupported database dialect: {dialect}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_reference_data(session: Session) -> None:
    """Seed the supported tickers and the holiday calendar once."""
    stock_rows = [
        {"symbol": symbol, "name": name, "sector": sector, "is_active": True}
        for symbol, name, sector in STOCKS
    ]
    statement = _insert(session, Stock).values(stock_rows)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "name": statement.excluded.name,
                "sector": statement.excluded.sector,
                "is_active": statement.excluded.is_active,
            },
        )
    )
    session.execute(
        _insert(session, MarketHoliday)
        .values([{"holiday_date": day} for day in MARKET_HOLIDAYS])
        .on_conflict_do_nothing(index_elements=["holiday_date"])
    )


def store_prices(session: Session, symbol: str, frame: pd.DataFrame) -> int:
    """Upsert daily bars; a re-run overwrites the same (symbol, trade_date) row."""
    records = [
        {
            "symbol": symbol,
            "trade_date": row.date,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": int(row.volume),
            "fetched_at": utcnow(),
        }
        for row in frame.itertuples(index=False)
    ]
    if not records:
        return 0
    statement = _insert(session, DailyPrice).values(records)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "volume": statement.excluded.volume,
                "fetched_at": statement.excluded.fetched_at,
            },
        )
    )
    return len(records)


def store_prediction(session: Session, record: dict) -> None:
    payload = dict(record)
    payload["created_at"] = utcnow()
    statement = _insert(session, Prediction).values(**payload)
    updatable = (
        "model_version_id",
        "target_date",
        "signal",
        "predicted_price",
        "last_close",
        "return_pct",
        "threshold_pct",
        "ood_z",
        "ood_flag",
        "warnings",
        "created_at",
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["symbol", "horizon_days", "data_as_of"],
            set_={column: getattr(statement.excluded, column) for column in updatable},
        )
    )


def log_update(
    session: Session,
    trigger_type: str,
    status: str,
    rows_inserted: int,
    message: str | None,
) -> DataUpdateLog:
    entry = DataUpdateLog(
        run_at=utcnow(),
        trigger_type=trigger_type,
        status=status,
        rows_inserted=rows_inserted,
        message=message,
    )
    session.add(entry)
    session.flush()
    return entry


def active_model_version(
    session: Session, symbol: str, horizon_days: int
) -> ModelVersion | None:
    return session.scalars(
        select(ModelVersion)
        .where(
            ModelVersion.symbol == symbol,
            ModelVersion.horizon_days == horizon_days,
            ModelVersion.is_active.is_(True),
        )
        .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
        .limit(1)
    ).first()


def register_model_version(
    session: Session,
    symbol: str,
    horizon_days: int,
    artifact_path: str,
    artifact_sha256: str,
    data_until: date,
    metrics: dict,
    config_payload: dict,
) -> ModelVersion:
    """Insert the version or return the existing row with the same artifact."""
    existing = session.scalars(
        select(ModelVersion).where(
            ModelVersion.symbol == symbol,
            ModelVersion.horizon_days == horizon_days,
            ModelVersion.artifact_sha256 == artifact_sha256,
        )
    ).first()
    if existing is not None:
        existing.metrics = metrics or existing.metrics
        existing.config = config_payload or existing.config
        existing.data_until = data_until
        existing.is_active = True
        return existing

    version = ModelVersion(
        symbol=symbol,
        horizon_days=horizon_days,
        trained_at=utcnow(),
        data_until=data_until,
        metrics=metrics,
        config=config_payload,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        is_active=True,
    )
    session.add(version)
    session.flush()
    return version


def latest_price_date(session: Session, symbol: str) -> date | None:
    return session.scalar(
        select(func.max(DailyPrice.trade_date)).where(DailyPrice.symbol == symbol)
    )


def price_date_range(session: Session, symbol: str) -> tuple[date | None, date | None]:
    """First and last stored session for a symbol."""
    first, last = session.execute(
        select(func.min(DailyPrice.trade_date), func.max(DailyPrice.trade_date)).where(
            DailyPrice.symbol == symbol
        )
    ).one()
    return first, last


def nth_price_date(session: Session, symbol: str, sessions: int) -> date | None:
    """Date of the `sessions`-th oldest session, named so an early reference
    date can suggest the first date whose model window fits."""
    if sessions < 1:
        raise ValueError("sessions must be positive")
    return session.scalar(
        select(DailyPrice.trade_date)
        .where(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.trade_date)
        .offset(sessions - 1)
        .limit(1)
    )


def first_price_date_on_or_after(session: Session, symbol: str, start: date) -> date | None:
    """The first stored session at or after `start`."""
    return session.scalar(
        select(DailyPrice.trade_date)
        .where(DailyPrice.symbol == symbol, DailyPrice.trade_date >= start)
        .order_by(DailyPrice.trade_date)
        .limit(1)
    )


def close_on_or_after(
    session: Session, symbol: str, start: date, days: int = 7
) -> tuple[date, float] | None:
    """The first close in the `days` after `start`, used to score a target date."""
    row = session.execute(
        select(DailyPrice.trade_date, DailyPrice.close)
        .where(
            DailyPrice.symbol == symbol,
            DailyPrice.trade_date >= start,
            DailyPrice.trade_date <= start + timedelta(days=days),
        )
        .order_by(DailyPrice.trade_date)
        .limit(1)
    ).first()
    return (row.trade_date, float(row.close)) if row else None


def _price_frame(rows) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    frame["volume"] = frame["volume"].astype("int64")
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column].astype(float)
    return frame.sort_values("date").reset_index(drop=True)


def price_frame(session: Session, symbol: str, limit: int = 400) -> pd.DataFrame:
    """The newest `limit` bars for a symbol, oldest first."""
    rows = session.execute(
        select(DailyPrice.trade_date, DailyPrice.open, DailyPrice.high, DailyPrice.low,
               DailyPrice.close, DailyPrice.volume)
        .where(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.trade_date.desc())
        .limit(limit)
    ).all()
    return _price_frame(rows)


def price_frame_until(
    session: Session, symbol: str, end_date: date, limit: int = 400
) -> pd.DataFrame:
    """The newest `limit` bars at or before `end_date`, oldest first."""
    rows = session.execute(
        select(DailyPrice.trade_date, DailyPrice.open, DailyPrice.high, DailyPrice.low,
               DailyPrice.close, DailyPrice.volume)
        .where(DailyPrice.symbol == symbol, DailyPrice.trade_date <= end_date)
        .order_by(DailyPrice.trade_date.desc())
        .limit(limit)
    ).all()
    return _price_frame(rows)


def price_frame_between(
    session: Session, symbol: str, start: date, end: date
) -> pd.DataFrame:
    """The stored bars from `start` to `end`, oldest first."""
    rows = session.execute(
        select(DailyPrice.trade_date, DailyPrice.open, DailyPrice.high, DailyPrice.low,
               DailyPrice.close, DailyPrice.volume)
        .where(
            DailyPrice.symbol == symbol,
            DailyPrice.trade_date >= start,
            DailyPrice.trade_date <= end,
        )
        .order_by(DailyPrice.trade_date)
    ).all()
    return _price_frame(rows)


def last_successful_update(session: Session) -> DataUpdateLog | None:
    return session.scalars(
        select(DataUpdateLog)
        .where(DataUpdateLog.status.in_(("success", "partial")))
        .order_by(DataUpdateLog.run_at.desc())
        .limit(1)
    ).first()


def recent_updates(session: Session, limit: int = 12) -> list[DataUpdateLog]:
    return list(
        session.scalars(select(DataUpdateLog).order_by(DataUpdateLog.run_at.desc()).limit(limit))
    )


def recent_training_jobs(session: Session, limit: int = 12) -> list[TrainingJob]:
    return list(
        session.scalars(select(TrainingJob).order_by(TrainingJob.id.desc()).limit(limit))
    )


def clear_stale_training_jobs(session: Session, stale_seconds: int) -> list[int]:
    """Mark jobs left running by a dead process as failed."""
    cutoff = utcnow().timestamp() - stale_seconds
    repaired: list[int] = []
    rows = session.scalars(select(TrainingJob).where(TrainingJob.status == "running")).all()
    for job in rows:
        started = job.started_at or job.requested_at
        if started.timestamp() < cutoff:
            job.status = "failed"
            job.finished_at = utcnow()
            job.error_message = f"interrupted: still running after {stale_seconds}s"
            repaired.append(job.id)
    return repaired
