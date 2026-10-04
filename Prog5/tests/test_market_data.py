from __future__ import annotations

import pandas as pd
import pytest

from prog5.market_data import (
    MarketDataUnavailable,
    corporate_action_dates,
    normalize,
    validation_issues,
    window_has_corporate_action,
)


def yfinance_like_frame() -> pd.DataFrame:
    """A frame shaped like yfinance's single-ticker output (MultiIndex columns)."""
    index = pd.date_range("2026-09-28", periods=4, freq="B", name="Date")
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["ADRO.JK"]])
    data = [
        [2400.0, 2450.0, 2380.0, 2440.0, 1000],
        [2440.0, 2460.0, 2400.0, 2410.0, 1200],
        [2410.0, 2420.0, 2300.0, 2350.0, 0],
        [2350.0, 2390.0, 2340.0, 2380.0, 900],
    ]
    return pd.DataFrame(data, index=index, columns=columns)


def test_normalize_flattens_and_sorts():
    frame = normalize(yfinance_like_frame())
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert frame["date"].is_monotonic_increasing
    assert frame["volume"].tolist() == [1000, 1200, 0, 900]
    assert frame["close"].tolist() == [2440.0, 2410.0, 2350.0, 2380.0]


def test_normalize_rejects_empty_input():
    with pytest.raises(MarketDataUnavailable):
        normalize(pd.DataFrame())


def test_normalize_drops_duplicate_dates_and_bad_closes():
    frame = normalize(yfinance_like_frame())
    broken = pd.concat([frame, frame.tail(1)], ignore_index=True)
    broken.loc[len(broken) - 1, "close"] = 0.0
    cleaned = normalize(
        broken.rename(columns={"date": "Date"}).set_index("Date")
    )
    assert len(cleaned) == 4
    assert (cleaned["close"] > 0).all()


def test_corporate_action_detection_flags_split_like_moves():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="B").date,
            "close": [3000.0, 3050.0, 620.0, 615.0],
        }
    )
    flagged = corporate_action_dates(frame)
    assert flagged == [frame["date"].iloc[2]]


def test_window_corporate_action_check():
    """The guard is scoped to the input window, not to history."""
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="B").date,
            "close": [3000.0, 3050.0, 620.0, 615.0],
        }
    )
    # The split sits between rows 1 and 2: inside a 3-close window, outside a 2-close one.
    assert window_has_corporate_action(frame, window_size=3) is True
    assert window_has_corporate_action(frame, window_size=2) is False
    calm = frame.assign(close=[1000.0, 1010.0, 1005.0, 1020.0])
    assert window_has_corporate_action(calm, window_size=3) is False


def test_validation_reports_zero_volume_and_inverted_high_low():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=25, freq="B").date,
            "open": [100.0] * 25,
            "high": [101.0] * 25,
            "low": [99.0] * 25,
            "close": [100.0] * 25,
            "volume": [0] * 25,
        }
    )
    frame.loc[24, "high"] = 90.0
    issues = validation_issues(frame)
    assert any("zero volume" in issue for issue in issues)
    assert any("high < low" in issue for issue in issues)


def test_validation_is_quiet_on_clean_data():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=60, freq="B").date,
            "open": [100.0] * 60,
            "high": [102.0] * 60,
            "low": [98.0] * 60,
            "close": [100.0] * 60,
            "volume": [5000] * 60,
        }
    )
    assert validation_issues(frame) == []
