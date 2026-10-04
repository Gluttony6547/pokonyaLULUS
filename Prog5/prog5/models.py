"""Persistence layer: market data, indicators, refresh runs, and predictions."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "prog5_stocks"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    is_research_ticker: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StockPrice(Base):
    __tablename__ = "prog5_stock_prices"
    __table_args__ = (UniqueConstraint("symbol", "price_date", name="uq_prog5_stock_prices_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("prog5_stocks.symbol"), nullable=False, index=True)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo_finance")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class TechnicalIndicator(Base):
    __tablename__ = "prog5_technical_indicators"
    __table_args__ = (
        UniqueConstraint("symbol", "price_date", name="uq_prog5_technical_indicators_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("prog5_stocks.symbol"), nullable=False, index=True)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    sma_5: Mapped[float | None] = mapped_column(Float)
    sma_10: Mapped[float | None] = mapped_column(Float)
    sma_20: Mapped[float | None] = mapped_column(Float)
    sma_50: Mapped[float | None] = mapped_column(Float)
    ema_5: Mapped[float | None] = mapped_column(Float)
    ema_10: Mapped[float | None] = mapped_column(Float)
    ema_20: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)
    rsi: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    upperband: Mapped[float | None] = mapped_column(Float)
    middleband: Mapped[float | None] = mapped_column(Float)
    lowerband: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class RefreshRun(Base):
    __tablename__ = "prog5_refresh_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="on_demand")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    requested_symbols: Mapped[str] = mapped_column(Text, nullable=False, default="")
    horizons: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)


class Prediction(Base):
    __tablename__ = "prog5_predictions"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "horizon_days", "data_as_of", name="uq_prog5_predictions_symbol_horizon_asof"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("prog5_refresh_runs.id"))
    symbol: Mapped[str] = mapped_column(ForeignKey("prog5_stocks.symbol"), nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    window_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False)
    last_close: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_price: Mapped[float] = mapped_column(Float, nullable=False)
    return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_pct: Mapped[float] = mapped_column(Float, nullable=False)
    signal: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_label: Mapped[str] = mapped_column(String(8), nullable=False)
    ood_z: Mapped[float] = mapped_column(Float, nullable=False)
    ood_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_file: Mapped[str] = mapped_column(Text, nullable=False)
    model_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_mean: Mapped[float] = mapped_column(Float, nullable=False)
    input_scale: Mapped[float] = mapped_column(Float, nullable=False)
    target_mean: Mapped[float] = mapped_column(Float, nullable=False)
    target_scale: Mapped[float] = mapped_column(Float, nullable=False)
    warnings: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
