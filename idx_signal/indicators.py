"""Technical indicators recomputed in pandas, TA-Lib compatible.

The research pipeline used TA-Lib. Against the committed Fusion_Data columns,
SMA and the Bollinger bands reproduce exactly (the bands to float noise, since
TA-Lib uses the population standard deviation). The recursive indicators, EMA,
RSI, and MACD, converge to within a small offset that comes from a warm-up
difference: TA-Lib started them on a longer series than the fused one, and a
recursive average never forgets its seed. Tests pin both facts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

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


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    """TA-Lib EMA: the first output is the SMA seed, then the recursive step."""
    values = close.to_numpy(dtype=float)
    out = np.full(values.shape, np.nan)
    if len(values) < period:
        return pd.Series(out, index=close.index)
    alpha = 2.0 / (period + 1.0)
    previous = float(np.mean(values[:period]))
    out[period - 1] = previous
    for i in range(period, len(values)):
        previous = (values[i] - previous) * alpha + previous
        out[i] = previous
    return pd.Series(out, index=close.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI with the average-gain/loss seed TA-Lib uses."""
    values = close.to_numpy(dtype=float)
    out = np.full(values.shape, np.nan)
    if len(values) <= period:
        return pd.Series(out, index=close.index)
    deltas = np.diff(values)
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    out[period] = 100.0 - 100.0 / (1.0 + (avg_gain / avg_loss if avg_loss else np.inf))
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        ratio = avg_gain / avg_loss if avg_loss else np.inf
        out[i + 1] = 100.0 - 100.0 / (1.0 + ratio)
    return pd.Series(out, index=close.index)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    signal_line = ema(line.dropna(), signal).reindex(line.index)
    return line, signal_line


def bollinger(
    close: pd.Series, period: int = 20, deviations: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(window=period).mean()
    # TA-Lib's BBANDS uses the population standard deviation (ddof=0).
    std = close.rolling(window=period).std(ddof=0)
    return middle + deviations * std, middle, middle - deviations * std


def compute_indicators(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Return a frame of price_date plus the 14 indicator columns."""
    frame = ohlcv.copy()
    close = frame["close"].astype(float)
    result = pd.DataFrame({"price_date": frame["date"]})
    for period in (5, 10, 20, 50):
        result[f"sma_{period}"] = sma(close, period)
        result[f"ema_{period}"] = ema(close, period)
    result["rsi"] = rsi(close)
    result["macd"], result["macd_signal"] = macd(close)
    result["upperband"], result["middleband"], result["lowerband"] = bollinger(close)
    return result[["price_date", *INDICATOR_COLUMNS]]
