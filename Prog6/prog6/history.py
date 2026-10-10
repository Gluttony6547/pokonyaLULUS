"""Session-relative features and labels.

Prog5's models predict absolute prices from absolute closes, which is why a
2026 close above anything in their 2018-2023 training window flags as out of
distribution. This module instead expresses each session as a vector of
percent changes versus recent closes, and labels each session with the
relative move H sessions ahead. Level drift cancels exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def log_returns(closes: np.ndarray) -> np.ndarray:
    """One return per session transition, so len(result) == len(closes) - 1."""
    if len(closes) < 2:
        return np.empty(0)
    closes = np.asarray(closes, dtype=float)
    positive = closes > 0
    if not positive.all():
        raise ValueError("closes must be strictly positive")
    return np.log(closes[1:] / closes[:-1])


def lag_matrix(returns: np.ndarray, lags: int) -> np.ndarray:
    """Rows of [r_t-lags+1 ... r_t]; row i is the feature for predicting r_(i+1)."""
    if lags < 1:
        raise ValueError("lags must be at least 1")
    if len(returns) < lags:
        return np.empty((0, lags))
    window = np.lib.stride_tricks.sliding_window_view(returns, lags)
    return window.astype(float)


def forward_returns(returns: np.ndarray, horizon: int) -> np.ndarray:
    """Sum of the next `horizon` returns starting strictly after each position.

    Value at index i is r_i + ... + r_(i+horizon-1) — the window STARTING
    at i (r_i included, since features end at index i-1 for aligned rows).
    Length is len(returns) - horizon, aligned with returns[:-horizon].
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    usable = len(returns) - horizon
    if usable <= 0:
        return np.empty(0)
    cumulative = np.concatenate(([0.0], np.cumsum(returns)))
    # Position i sums returns[i : i + horizon]. With cumulative[k] = sum(returns[:k]),
    # that is cumulative[i + horizon] - cumulative[i], for i in 0..usable-1.
    start = cumulative[:usable]
    end = cumulative[horizon : horizon + usable]
    return end - start


@dataclass(frozen=True)
class SessionFrame:
    """Feature/label matrices that row-align for one (symbol, horizon)."""

    dates: tuple  # session dates for each usable row
    features: np.ndarray  # shape (rows, lags)
    labels: np.ndarray  # shape (rows,): forward relative return
    feature_lags: int
    horizon: int

    def __len__(self) -> int:
        return len(self.dates)


def build_frame(dates: list, closes: list[float], horizon: int, lags: int = 5) -> SessionFrame:
    """Row-aligned features and labels for one (symbol, horizon) pair.

    Feature row p covers returns p..p+lags-1 (as-of close index p+lags); its
    label is the relative return measured from that close over `horizon`
    sessions ahead, i.e. labels[lags + p]. Requires lags + horizon + 2 closes
    minimum so at least one row exists; raises ValueError otherwise.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if lags < 1:
        raise ValueError("lags must be at least 1")
    closes_array = np.asarray(closes, dtype=float)
    if not (closes_array > 0).all():
        raise ValueError("closes must be strictly positive")
    returns = log_returns(closes_array)
    features = lag_matrix(returns, lags)
    labels = forward_returns(returns, horizon)
    pairs = len(labels) - lags
    if pairs < 1:
        minimum = lags + horizon + 2
        raise ValueError(f"need at least {minimum} closes, got {len(closes_array)}")

    # Pair p: features row p with labels[lags + p]; the as-of close is index
    # p + lags, so the date for row p is dates[lags + p].
    aligned_features = features[:pairs]
    aligned_labels = labels[lags : lags + pairs]
    aligned_dates = tuple(dates[lags : lags + pairs])
    return SessionFrame(
        dates=aligned_dates,
        features=aligned_features,
        labels=aligned_labels,
        feature_lags=lags,
        horizon=horizon,
    )


def last_feature_vector(closes: list[float], lags: int = 5) -> np.ndarray:
    """The feature row for predicting from the newest session."""
    closes_array = np.asarray(closes, dtype=float)
    returns = log_returns(closes_array)
    if len(returns) < lags:
        raise ValueError(f"need at least {lags + 1} closes for a {lags}-lag feature")
    return returns[-lags:].astype(float)
