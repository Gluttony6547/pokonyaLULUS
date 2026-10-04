"""Daily OHLCV ingestion from Yahoo Finance with validation."""

from __future__ import annotations

import logging
import time
from datetime import date

import numpy as np
import pandas as pd

from . import config

logger = logging.getLogger(__name__)

PRICE_COLUMNS = ("date", "open", "high", "low", "close", "volume")
SOURCE = "yahoo_finance"


class MarketDataUnavailable(RuntimeError):
    pass


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """Reduce a yfinance frame to date/open/high/low/close/volume, oldest first."""
    if frame is None or frame.empty:
        raise MarketDataUnavailable("Provider returned no rows.")
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns={column: str(column).strip().lower() for column in frame.columns})
    frame = frame.reset_index()
    date_column = next(
        (column for column in frame.columns if str(column).lower() in {"date", "datetime"}),
        None,
    )
    if date_column is None:
        raise MarketDataUnavailable("Provider response has no date column.")
    frame = frame.rename(columns={date_column: "date"})

    dates = pd.to_datetime(frame["date"], errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    frame["date"] = dates
    frame = frame.dropna(subset=["date"])

    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["close"])
    frame = frame[frame["close"] > 0]
    frame["volume"] = frame["volume"].fillna(0).clip(lower=0).round().astype("int64")
    for column in ("open", "high", "low"):
        frame[column] = frame[column].fillna(frame["close"])
    frame["date"] = frame["date"].dt.date
    frame = frame[list(PRICE_COLUMNS)]
    frame = frame.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if frame.empty:
        raise MarketDataUnavailable("No usable rows after normalization.")
    return frame


def fetch_daily_ohlcv(
    symbol: str,
    period: str = config.DEFAULT_HISTORY_PERIOD,
    attempts: int = 2,
) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            import yfinance as yf

            frame = yf.download(
                f"{symbol}.JK",
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=20,
            )
            result = normalize(frame)
            logger.info("Fetched %s rows for %s from Yahoo Finance", len(result), symbol)
            return result
        except Exception as error:  # network and shape errors both retried once
            last_error = error
            logger.warning("Yahoo Finance attempt %s failed for %s: %s", attempt + 1, symbol, error)
            if attempt + 1 < attempts:
                time.sleep(0.5)
    raise MarketDataUnavailable(f"Yahoo Finance failed for {symbol}.JK: {last_error}")


def corporate_action_dates(
    frame: pd.DataFrame, threshold: float = config.CORPORATE_ACTION_JUMP
) -> list[date]:
    """Dates whose close moved more than `threshold` overnight (splits, reverse splits)."""
    closes = frame["close"].astype(float)
    moves = closes.pct_change().abs()
    return [day for day, flagged in zip(frame["date"], moves > threshold) if bool(flagged)]


def window_has_corporate_action(frame: pd.DataFrame, window_size: int) -> bool:
    """True when a corporate action falls inside the last `window_size` closes."""
    if len(frame) < 2:
        return False
    tail = frame.tail(max(window_size, 2)).reset_index(drop=True)
    return bool(corporate_action_dates(tail))


def validation_issues(frame: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    gaps = pd.to_datetime(frame["date"]).diff().dt.days.dropna()
    if not gaps.empty and gaps.max() > 10:
        issues.append(f"largest calendar gap is {int(gaps.max())} days")
    if frame["volume"].tail(20).eq(0).all():
        issues.append("last 20 sessions report zero volume")
    upside = frame["high"] < frame["low"]
    if bool(upside.any()):
        issues.append(f"{int(upside.sum())} rows where high < low")
    return issues


