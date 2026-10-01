from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Stock(Base):
    __tablename__ = "stocks"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(120))
    sector: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StockPrice(Base):
    __tablename__ = "stock_prices"
    __table_args__ = (
        UniqueConstraint("symbol", "price_date", name="uq_stock_prices_symbol_date"),
        Index("ix_stock_prices_symbol_date", "symbol", "price_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint("symbol", "indicator_date", name="uq_indicators_symbol_date"),
        Index("ix_indicators_symbol_date", "symbol", "indicator_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    indicator_date: Mapped[date] = mapped_column(Date, nullable=False)
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


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (Index("ix_news_articles_symbol_published", "symbol", "published_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    sentiment_flag: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NewsSentiment(Base):
    __tablename__ = "news_sentiment"
    __table_args__ = (
        UniqueConstraint("symbol", "sentiment_date", name="uq_sentiment_symbol_date"),
        Index("ix_sentiment_symbol_date", "symbol", "sentiment_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    sentiment_date: Mapped[date] = mapped_column(Date, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_news: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sentiment_flag: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class FusedMarketData(Base):
    __tablename__ = "fused_market_data"
    __table_args__ = (
        UniqueConstraint("symbol", "market_date", name="uq_fused_symbol_date"),
        Index("ix_fused_symbol_date", "symbol", "market_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    ground_truth_signal: Mapped[int | None] = mapped_column(Integer)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_versions_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    architecture: Mapped[str] = mapped_column(String(80), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(255), nullable=False)
    feature_set: Mapped[str] = mapped_column(String(120), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_production: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PredictionRequest(Base):
    __tablename__ = "prediction_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_predictions_symbol_created", "symbol", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_requests.id"), unique=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    prediction_date: Mapped[date] = mapped_column(Date, nullable=False)
    input_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_price: Mapped[float] = mapped_column(Float, nullable=False)
    return_percent: Mapped[float] = mapped_column(Float, nullable=False)
    signal: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_percent: Mapped[float] = mapped_column(Float, nullable=False)
    feature_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
