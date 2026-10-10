"""Prediction policies: baseline regression on session-relative returns.

Each policy fits on (features, labels) rows from history.build_frame and
predicts one forward relative return from one feature row. Policies are pure
objects with no I/O, so the backtest can instantiate them per window.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Policy(ABC):
    """A fitted session-relative continuation predictor."""

    name: str

    @abstractmethod
    def fit(self, features: np.ndarray, labels: np.ndarray) -> None: ...

    @abstractmethod
    def predict(self, feature: np.ndarray) -> float: ...


class MomentumPolicy(Policy):
    """Continuation = mean of the last K lagged returns (sign-kept trend)."""

    def __init__(self, k: int = 5):
        if k < 1:
            raise ValueError("momentum window must be at least 1")
        self.k = k
        self.name = f"momentum_{k}"

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        # A trend policy has nothing to learn beyond confirming the window.
        if features.shape[0] == 0:
            raise ValueError("momentum policy needs at least one training row")

    def predict(self, feature: np.ndarray) -> float:
        recent = feature[-self.k :]
        return float(np.mean(recent))


class RidgePolicy(Policy):
    """Ridge regression from the lag matrix to forward returns."""

    def __init__(self, lags: int = 5, alpha: float = 1.0):
        self.lags = lags
        self.alpha = alpha
        self.name = f"ridge_l{lags}_a{alpha:g}"
        self._weights: np.ndarray | None = None

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        if features.shape[0] < self.lags + 2:
            raise ValueError("ridge policy needs at least lags + 2 training rows")
        design = np.column_stack([np.ones(len(features)), features])
        penalty = self.alpha * np.eye(design.shape[1])
        penalty[0, 0] = 0.0  # do not shrink the intercept
        self._weights = np.linalg.solve(design.T @ design + penalty, design.T @ labels)

    def predict(self, feature: np.ndarray) -> float:
        if self._weights is None:
            raise RuntimeError("ridge policy used before fit")
        row = np.concatenate(([1.0], np.asarray(feature, dtype=float)))
        return float(row @ self._weights)


def policies_for(horizons: tuple[int, ...], lags: int = 5) -> dict[int, list[Policy]]:
    """One untrained instance per policy per horizon, keyed by horizon."""
    return {
        horizon: [MomentumPolicy(k=5), MomentumPolicy(k=20), RidgePolicy(lags=lags)]
        for horizon in horizons
    }
