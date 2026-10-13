"""Persistence layer matching the project's Physical Data Model.

All timestamps are TIMESTAMPTZ in UTC; the interface renders them in WIB.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

from . import config

# JSONB on Postgres, plain JSON on the local SQLite fallback.
JsonColumn = JSONB().with_variant(JSON(), "sqlite")
Money = Numeric(14, 2, asdecimal=False)
Ratio = Numeric(10, 4, asdecimal=False)
# SQLite only auto-increments INTEGER PRIMARY KEY, so BIGSERIAL needs the variant.
PkId = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    # Table names come from the project's Physical Data Model. A schema is only
    # attached when one is configured, so a database that hosts other work can
    # keep the app's tables in their own namespace.
    metadata = MetaData(schema=config.database_schema())


class Stock(Base):
    __tablename__ = "stocks"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DailyPrice(Base):
    __tablename__ = "daily_prices"

    symbol: Mapped[str] = mapped_column(
        ForeignKey("stocks.symbol", ondelete="CASCADE"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Money, nullable=False)
    high: Mapped[float] = mapped_column(Money, nullable=False)
    low: Mapped[float] = mapped_column(Money, nullable=False)
    close: Mapped[float] = mapped_column(Money, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_daily_prices_date", "trade_date"),)


class MarketHoliday(Base):
    __tablename__ = "market_holidays"

    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    description: Mapped[str | None] = mapped_column(String(120))


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(PkId, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    data_until: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict] = mapped_column(JsonColumn, nullable=False, default=dict)
    config: Mapped[dict] = mapped_column(JsonColumn, nullable=False, default=dict)
    artifact_path: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("symbol", "horizon_days", "trained_at", name="uq_model_versions_identity"),
        CheckConstraint("horizon_days IN (1, 5, 10, 20, 50)", name="ck_model_versions_horizon"),
        Index("idx_model_versions_lookup", "symbol", "horizon_days", "is_active"),
    )


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id: Mapped[int] = mapped_column(PkId, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed')", name="ck_training_jobs_status"
        ),
        CheckConstraint("horizon_days IN (1, 5, 10, 20, 50)", name="ck_training_jobs_horizon"),
        Index("idx_training_jobs_status", "status"),
    )


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(PkId, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    horizon_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    signal: Mapped[str] = mapped_column(String(4), nullable=False)
    predicted_price: Mapped[float | None] = mapped_column(Money)
    last_close: Mapped[float] = mapped_column(Money, nullable=False)
    return_pct: Mapped[float] = mapped_column(Ratio, nullable=False)
    threshold_pct: Mapped[float] = mapped_column(Ratio, nullable=False)
    ood_z: Mapped[float] = mapped_column(Ratio, nullable=False, default=0.0)
    ood_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warnings: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "symbol", "horizon_days", "data_as_of", name="uq_predictions_symbol_horizon_asof"
        ),
        CheckConstraint("signal IN ('BUY', 'HOLD', 'SELL')", name="ck_predictions_signal"),
        CheckConstraint("horizon_days IN (1, 5, 10, 20, 50)", name="ck_predictions_horizon"),
        Index("idx_predictions_lookup", "symbol", "horizon_days", "created_at"),
    )


class DataUpdateLog(Base):
    __tablename__ = "data_update_logs"

    id: Mapped[int] = mapped_column(PkId, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    trigger_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('scheduled', 'manual')", name="ck_data_update_logs_trigger"
        ),
        CheckConstraint(
            "status IN ('success', 'partial', 'failed', 'skipped')",
            name="ck_data_update_logs_status",
        ),
        Index("idx_data_update_logs_run", "run_at"),
    )
