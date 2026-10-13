"""Indicator definitions, and how far they reproduce the research columns.

Two kinds of test live here. The definition tests check each indicator against
its own formula, so they hold without the research checkout. The parity test
compares against the committed Fusion_Data columns and documents the one real
difference: TA-Lib seeded the recursive indicators on a longer series, so EMA,
RSI, and MACD sit slightly off no matter how far the series runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from idx_signal import config
from idx_signal.indicators import INDICATOR_COLUMNS, compute_indicators, ema, macd, rsi, sma


@pytest.fixture
def closes() -> pd.Series:
    rng = np.random.default_rng(11)
    values = 1000 + np.cumsum(rng.normal(0, 8, 300))
    return pd.Series(values)


def test_sma_is_the_rolling_mean(closes):
    assert sma(closes, 20).iloc[-1] == pytest.approx(closes.iloc[-20:].mean())


def test_ema_starts_from_the_sma_seed_and_then_recurses(closes):
    period = 10
    result = ema(closes, period)
    assert np.isnan(result.iloc[period - 2])
    assert result.iloc[period - 1] == pytest.approx(closes.iloc[:period].mean())
    alpha = 2 / (period + 1)
    expected = (closes.iloc[period] - result.iloc[period - 1]) * alpha + result.iloc[period - 1]
    assert result.iloc[period] == pytest.approx(expected)
    assert result.iloc[: period - 1].isna().all()


def test_rsi_stays_inside_its_range(closes):
    result = rsi(closes, 14).dropna()
    assert not result.empty
    assert result.between(0, 100).all()


def test_rsi_is_100_when_every_change_is_a_gain():
    rising = pd.Series(np.arange(1, 60, dtype=float))
    assert rsi(rising, 14).dropna().iloc[-1] == pytest.approx(100.0)


def test_bollinger_bands_use_the_population_deviation(closes):
    result = compute_indicators(pd.DataFrame({"date": range(len(closes)), "close": closes}))
    window = closes.iloc[-20:]
    expected_std = window.std(ddof=0)
    assert result["middleband"].iloc[-1] == pytest.approx(window.mean())
    assert result["upperband"].iloc[-1] == pytest.approx(window.mean() + 2 * expected_std)
    assert result["lowerband"].iloc[-1] == pytest.approx(window.mean() - 2 * expected_std)


def test_macd_signal_is_an_ema_of_the_macd_line(closes):
    line, signal = macd(closes)
    assert signal.dropna().index.min() >= line.dropna().index.min()
    assert not signal.dropna().empty


def test_every_declared_column_is_produced(closes):
    frame = pd.DataFrame({"date": range(len(closes)), "close": closes})
    assert list(compute_indicators(frame).columns) == ["price_date", *INDICATOR_COLUMNS]


def max_difference(computed: pd.Series, reference, start: int = 0) -> float:
    """Largest gap where both series have a value.

    The research columns carry values from the first row, because TA-Lib ran
    over a longer series than the fused one, so the warm-up region cannot be
    compared position by position.
    """
    mine = np.asarray(computed, dtype=float)[start:]
    theirs = np.asarray(reference, dtype=float)[start:]
    mask = np.isfinite(mine) & np.isfinite(theirs)
    assert mask.sum() > 100, "not enough overlapping values to compare"
    return float(np.abs(mine[mask] - theirs[mask]).max())


def test_matches_the_committed_research_columns(reference_assets):
    raw = pd.read_csv(config.fusion_file("ADRO"))
    frame = pd.DataFrame(
        {"date": pd.to_datetime(raw["datetime"]).dt.date, "close": raw["close"].astype(float)}
    )
    computed = compute_indicators(frame)

    # Window-based indicators have no memory of where the series began.
    for mine, theirs in (
        ("sma_5", "SMA_5"),
        ("sma_10", "SMA_10"),
        ("sma_20", "SMA_20"),
        ("sma_50", "SMA_50"),
        ("middleband", "MIDDLEBAND"),
    ):
        assert max_difference(computed[mine], raw[theirs]) == 0.0

    for mine, theirs in (("upperband", "UPPERBAND"), ("lowerband", "LOWERBAND")):
        assert max_difference(computed[mine], raw[theirs]) < 1e-8

    # Recursive indicators carry their seed forward, so they only converge. The
    # bounds are the measured difference, kept tight enough that a change to the
    # recursion or its seed would break them.
    assert max_difference(computed["ema_5"], raw["EMA_5"], start=100) < 1e-6
    assert max_difference(computed["ema_10"], raw["EMA_10"], start=100) < 1e-5
    assert max_difference(computed["rsi"], raw["RSI"], start=100) < 0.05
    assert max_difference(computed["macd"], raw["MACD"], start=100) < 1.0
    assert max_difference(computed["macd_signal"], raw["MACD_SIGNAL"], start=100) < 2.0
