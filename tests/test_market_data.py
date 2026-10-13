"""Provider frames get normalized, and an unfinished session is never stored."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from idx_signal import config
from idx_signal.market_data import (
    MarketDataUnavailable,
    bar_is_still_forming,
    drop_forming_bar,
    normalize,
    validation_issues,
    window_has_corporate_action,
)

WIB = config.WIB


def test_empty_frame_is_rejected():
    with pytest.raises(MarketDataUnavailable):
        normalize(pd.DataFrame())


def test_multi_index_columns_are_flattened():
    index = pd.to_datetime(["2026-10-12", "2026-10-13"])
    index.name = "Date"
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["ADRO.JK"]])
    frame = pd.DataFrame(
        [[2500, 2560, 2480, 2550, 1000], [2550, 2600, 2520, 2580, 1200]],
        index=index,
        columns=columns,
    )
    result = normalize(frame)
    assert list(result.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert result["date"].tolist() == [date(2026, 10, 12), date(2026, 10, 13)]
    assert result["close"].tolist() == [2550.0, 2580.0]


def test_rows_without_a_close_are_dropped_and_sorted():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-10-13", "2026-10-12", "2026-10-14"]),
            "Close": [2580, 2550, None],
            "Volume": [1200, 1000, 900],
        }
    )
    result = normalize(frame)
    assert result["date"].tolist() == [date(2026, 10, 12), date(2026, 10, 13)]
    assert result["volume"].tolist() == [1000, 1200]


def test_a_bar_is_forming_until_the_session_closes():
    session = date(2026, 10, 13)  # a Tuesday
    assert bar_is_still_forming(session, datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc))
    # 10:00 WIB is still inside the second session.
    assert bar_is_still_forming(session, datetime(2026, 10, 13, 3, 0, tzinfo=timezone.utc))
    # 16:05 WIB plus the grace period has passed.
    assert not bar_is_still_forming(session, datetime(2026, 10, 13, 9, 6, tzinfo=timezone.utc))


def test_a_replayed_session_is_always_final():
    # An older session can no longer be forming, and a weekend date never forms.
    now = datetime(2026, 10, 13, 9, 6, tzinfo=timezone.utc)
    assert not bar_is_still_forming(date(2026, 10, 12), now)
    assert not bar_is_still_forming(date(2026, 10, 10), now)  # Saturday


def test_drop_forming_bar_trims_only_while_forming(prices):
    forming_at = datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)
    tail = prices.tail(3).copy()
    tail.iloc[-1, tail.columns.get_loc("date")] = date(2026, 10, 13)
    trimmed, notes = drop_forming_bar(tail, forming_at)
    assert len(trimmed) == 2
    assert notes and "belum final" in notes[0]

    settled, notes = drop_forming_bar(tail, datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc))
    assert len(settled) == 3
    assert notes == []


def test_validation_flags_inverted_high_low(prices):
    broken = prices.copy()
    broken.loc[broken.index[-1], "high"] = 1.0
    issues = validation_issues(broken)
    assert any("high di bawah low" in issue for issue in issues)


def test_corporate_action_inside_the_window_is_detected():
    rows = 60
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1) + timedelta(days=i) for i in range(rows)],
            "close": np.full(rows, 1000.0),
        }
    )
    assert not window_has_corporate_action(frame, 20)
    frame.loc[rows - 5, "close"] = 400.0  # a 60 percent overnight drop
    assert window_has_corporate_action(frame, 20)
