import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from data_pipeline import TechnicalIndicatorExtractor
from database import engine
from models import Stock, StockPrice


logger = logging.getLogger(__name__)
SUPPORTED_SYMBOLS = ("ADRO", "ANTM", "BMRI", "BNGA", "EXCL", "INCO", "INKP", "MEDC", "PGAS", "TLKM")
PERIODS = {"6mo": 130, "1y": 260, "5y": None}
RESEARCH_DATA_DIRECTORY = Path(__file__).resolve().parent / "data" / "research"
PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
INDICATOR_COLUMNS = (
    "sma_5",
    "sma_10",
    "sma_20",
    "sma_50",
    "ema_5",
    "ema_10",
    "ema_20",
    "ema_50",
    "rsi",
    "macd",
    "macd_signal",
    "upperband",
    "middleband",
    "lowerband",
)


class MarketDataUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    source: str
    data_as_of: date
    warning: str | None
    frame: pd.DataFrame


def ensure_supported_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Ticker '{normalized}' belum tersedia pada artefak penelitian.")
    return normalized


def _normalize_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    frame = frame.rename(columns={column: str(column).strip().lower() for column in frame.columns})
    frame = frame.reset_index()
    date_column = next(
        (column for column in frame.columns if str(column).lower() in {"date", "datetime"}),
        None,
    )
    if date_column is None:
        raise MarketDataUnavailable("Penyedia data tidak mengembalikan kolom tanggal.")

    frame = frame.rename(columns={date_column: "date"})
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    frame["date"] = dates
    frame = frame.dropna(subset=["date"])
    if "close" not in frame.columns:
        raise MarketDataUnavailable("Penyedia data tidak mengembalikan harga penutupan.")

    for column in PRICE_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan if column != "volume" else 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["close"])
    frame["volume"] = frame["volume"].fillna(0).clip(lower=0).astype("int64")
    return frame[["date", *PRICE_COLUMNS]].sort_values("date").drop_duplicates("date")


def fetch_yahoo_history(symbol: str, period: str) -> pd.DataFrame:
    last_error = None
    for attempt in range(2):
        try:
            import yfinance as yf

            frame = yf.download(
                f"{symbol}.JK",
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=12,
            )
            if frame.empty:
                raise MarketDataUnavailable(f"Yahoo Finance tidak memiliki data untuk {symbol}.JK.")
            return _normalize_prices(frame)
        except Exception as error:
            last_error = error
            if attempt == 0:
                logger.warning("Yahoo Finance attempt failed for %s; retrying once: %s", symbol, error)
                time.sleep(0.5)

    raise MarketDataUnavailable(
        f"Yahoo Finance gagal mengambil data {symbol}.JK setelah dua percobaan."
    ) from last_error


def load_research_history(symbol: str, period: str) -> pd.DataFrame:
    path = RESEARCH_DATA_DIRECTORY / f"Fusion_Data_{symbol}.csv"
    if not path.is_file():
        raise MarketDataUnavailable(f"Dataset penelitian untuk {symbol} tidak ditemukan.")

    frame = pd.read_csv(path, usecols=["datetime", *PRICE_COLUMNS], parse_dates=["datetime"])
    frame = frame.rename(columns={"datetime": "date"})
    frame = _normalize_prices(frame.set_index("date"))
    count = PERIODS[period]
    if count is not None:
        frame = frame.tail(count)
    if frame.empty:
        raise MarketDataUnavailable(f"Dataset penelitian untuk {symbol} tidak memiliki harga.")
    return frame


def _frame_from_database(db: Session, symbol: str, period: str) -> pd.DataFrame:
    query = (
        select(StockPrice)
        .where(StockPrice.symbol == symbol)
        .order_by(StockPrice.price_date.desc())
    )
    count = PERIODS[period]
    if count is not None:
        query = query.limit(count)
    records = db.scalars(query).all()
    if not records:
        return pd.DataFrame(columns=["date", *PRICE_COLUMNS])
    rows = [
        {
            "date": record.price_date,
            "open": record.open,
            "high": record.high,
            "low": record.low,
            "close": record.close,
            "volume": record.volume,
            "source": record.source,
        }
        for record in reversed(records)
    ]
    return pd.DataFrame(rows)


def _store_prices(db: Session, symbol: str, frame: pd.DataFrame, source: str) -> None:
    db.merge(Stock(symbol=symbol))
    records = [
        {
            "symbol": symbol,
            "price_date": row.date.date(),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": int(row.volume),
            "source": source,
        }
        for row in frame.itertuples(index=False)
    ]
    if not records:
        return

    insert_statement = (
        sqlite_insert(StockPrice) if engine.dialect.name == "sqlite" else postgresql_insert(StockPrice)
    )
    statement = insert_statement.values(records)
    statement = statement.on_conflict_do_update(
        index_elements=["symbol", "price_date"],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
            "source": statement.excluded.source,
        },
    )
    db.execute(statement)
    db.commit()


def get_market_snapshot(db: Session, symbol: str, period: str = "1y") -> MarketSnapshot:
    normalized = ensure_supported_symbol(symbol)
    if period not in PERIODS:
        raise ValueError(f"Rentang '{period}' tidak didukung.")

    warning = None
    try:
        frame = fetch_yahoo_history(normalized, period)
    except Exception as error:
        logger.warning("Yahoo Finance request failed for %s: %s", normalized, error)
        cached = _frame_from_database(db, normalized, period)
        if not cached.empty:
            frame = cached
            cached_source = str(cached["source"].iloc[-1])
            if cached_source == "research_dataset":
                source = "research_dataset"
                warning = (
                    "Yahoo Finance tidak dapat dijangkau. Dataset penelitian historis dari cache "
                    "ditampilkan, bukan harga terkini."
                )
            else:
                source = "database_cache"
                warning = "Yahoo Finance tidak dapat dijangkau. Data pasar yang tersimpan lokal ditampilkan."
        else:
            try:
                frame = load_research_history(normalized, period)
            except (OSError, ValueError, MarketDataUnavailable) as fallback_error:
                logger.error("No market data fallback is available for %s: %s", normalized, fallback_error)
                raise MarketDataUnavailable(
                    f"Data harga {normalized} tidak tersedia dari Yahoo Finance, cache, atau dataset penelitian."
                ) from fallback_error
            _store_prices(db, normalized, frame, "research_dataset")
            source = "research_dataset"
            warning = (
                "Yahoo Finance tidak dapat dijangkau. Dataset penelitian historis ditampilkan, "
                "bukan harga terkini."
            )
    else:
        _store_prices(db, normalized, frame, "yahoo_finance")
        source = "yahoo_finance"

    if frame.empty:
        raise MarketDataUnavailable(f"Tidak ada data harga untuk {normalized}.")
    return MarketSnapshot(
        symbol=normalized,
        source=source,
        data_as_of=pd.Timestamp(frame["date"].max()).date(),
        warning=warning,
        frame=frame,
    )


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    return TechnicalIndicatorExtractor.compute_indicators(frame)


def indicator_values(frame: pd.DataFrame) -> dict[str, float | None]:
    enriched = add_indicators(frame)
    latest = enriched.iloc[-1]
    result = {}
    for column in INDICATOR_COLUMNS:
        value = latest[column]
        result[column] = float(value) if pd.notna(value) else None
    return result
