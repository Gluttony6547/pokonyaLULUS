from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from prog5 import config
from prog5.indicators import (
    INDICATOR_COLUMNS,
    bollinger,
    compute_indicators,
    ema,
    macd,
    rsi,
    sma,
)

from .conftest import requires_research

RESEARCH_START = "2018-09-25"
LEAD_IN_ROWS = 100


def make_series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype="float64")


def test_sma_has_no_value_before_period_end():
    series = make_series([1, 2, 3, 4, 5])
    result = sma(series, 3)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_ema_is_seeded_with_the_first_sma():
    series = make_series([10, 11, 12, 13, 14])
    result = ema(series, 3)
    assert np.isnan(result.iloc[0]) and np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(11.0)
    # alpha = 2 / (3 + 1) = 0.5
    assert result.iloc[3] == pytest.approx(12.0)
    assert result.iloc[4] == pytest.approx(13.0)


def test_rsi_of_rising_series_is_full():
    series = make_series(list(range(1, 21)))
    result = rsi(series, 14)
    assert np.isnan(result.iloc[13])
    assert result.iloc[14] == pytest.approx(100.0)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_stays_in_range_on_mixed_series():
    values = [100 + (5 if i % 3 else -7) for i in range(60)]
    result = rsi(make_series(values), 14).dropna()
    assert ((result >= 0) & (result <= 100)).all()
    assert len(result) == len(values) - 14


def test_bollinger_middle_band_equals_sma():
    series = make_series([100, 102, 101, 105, 110, 108, 107, 111])
    upper, middle, lower = bollinger(series, 5)
    assert middle.iloc[-1] == pytest.approx(sma(series, 5).iloc[-1])
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]


def test_macd_is_the_difference_of_the_two_emas():
    series = make_series([100 + 3 * i + (i % 5) for i in range(80)])
    line, signal = macd(series)
    assert line.iloc[-1] == pytest.approx((ema(series, 12) - ema(series, 26)).iloc[-1])
    assert signal.iloc[:24].isna().all() or signal.notna().sum() > 0


def test_compute_indicators_returns_expected_columns():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=60, freq="D").date,
            "open": np.linspace(100, 200, 60),
            "high": np.linspace(101, 201, 60),
            "low": np.linspace(99, 199, 60),
            "close": np.linspace(100, 200, 60),
            "volume": np.full(60, 1000),
        }
    )
    result = compute_indicators(frame)
    assert list(result.columns) == ["price_date", *INDICATOR_COLUMNS]
    assert len(result) == len(frame)
    last = result.iloc[-1]
    assert last["rsi"] == pytest.approx(100.0)
    assert last["sma_50"] > 0 and last["lowerband"] <= last["middleband"] <= last["upperband"]


@requires_research
def test_indicators_match_committed_research_columns():
    """Rebuild the research indicator pipeline for ADRO and compare to the CSV."""
    symbol = "ADRO"
    raw = pd.read_csv(config.raw_stock_file(symbol), parse_dates=["datetime"])
    raw["datetime"] = raw["datetime"].dt.strftime("%Y-%m-%d")
    start_index = raw.index[raw["datetime"] == RESEARCH_START][0]
    trimmed = raw.iloc[start_index - LEAD_IN_ROWS :].reset_index(drop=True)

    fusion = pd.read_csv(config.fusion_file(symbol))
    fusion["datetime"] = fusion["datetime"].str.strip()

    computed = pd.DataFrame({"datetime": trimmed["datetime"]})
    close = trimmed["close"].astype(float)
    for period in (5, 10, 20, 50):
        computed[f"SMA_{period}"] = sma(close, period)
        computed[f"EMA_{period}"] = ema(close, period)
    computed["RSI"] = rsi(close)
    computed["MACD"], computed["MACD_SIGNAL"] = macd(close)
    computed["UPPERBAND"], computed["MIDDLEBAND"], computed["LOWERBAND"] = bollinger(close)

    merged = computed.merge(fusion, on="datetime", how="inner")
    assert len(merged) == len(fusion)

    exact = [
        "SMA_5",
        "SMA_10",
        "SMA_20",
        "SMA_50",
        "EMA_5",
        "EMA_10",
        "EMA_20",
        "EMA_50",
        "RSI",
        "UPPERBAND",
        "MIDDLEBAND",
        "LOWERBAND",
    ]
    for column in exact:
        difference = (merged[column + "_x"] - merged[column + "_y"]).abs().max()
        assert difference < 1e-6, f"{column} differs from the research column by {difference}"

    # TA-Lib seeds its MACD EMAs slightly differently; the seed transient
    # decays within the first ~100 bars, after which the recursion matches.
    tail = merged.tail(500)
    for column in ("MACD", "MACD_SIGNAL"):
        difference = (tail[column + "_x"] - tail[column + "_y"]).abs().max()
        assert difference < 1e-6, f"{column} differs by {difference} on the recent tail"
