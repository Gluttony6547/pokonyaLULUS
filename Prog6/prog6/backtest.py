"""Walk-forward backtest: fit on a trailing window, score the next block.

Prog5's freshness failure taught the lesson that a model showing no evidence
of recent performance cannot be trusted at all. The backtest is the evidence
layer: each policy is re-fit on a window ending before the scored block, so
no row is in both the fit and the score set.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .policies import Policy


@dataclass
class Metrics:
    hit_rate: float
    mae: float
    mape: float
    rows: int

    def to_text(self) -> str:
        return (
            f"hit={self.hit_rate:.1%} mae={self.mae:.2%} "
            f"mape={self.mape:.2%} n={self.rows}"
        )


@dataclass
class Slice:
    dates: tuple
    predicted: tuple
    actual: tuple


@dataclass
class Backtest:
    """Per-policy out-of-sample performance over one symbol-horizon pair."""

    policy: str
    horizon: int
    metrics: Metrics
    rows: list[Slice] = field(repr=False)


def metric_row(
    predictions: list[float],
    labels: list[float],
    dates: list,
) -> Metrics:
    """MAE over absolute returns, MAPE over signed relative returns."""
    predicted = np.asarray(predictions, dtype=float)
    actual = np.asarray(labels, dtype=float)
    if len(predicted) == 0:
        raise ValueError("scoring needs at least one prediction")
    if len(predicted) != len(actual):
        raise ValueError(
            f"length mismatch: {len(predicted)} predictions vs {len(actual)} labels"
        )
    hit = float(np.mean(np.sign(predicted) == np.sign(actual)))
    mae = float(np.mean(np.abs(predicted - actual)))
    # MAPE on a relative return divides by |actual|; a near-zero actual makes
    # it explode, so clamp the denominator like every serious implementation.
    denominators = np.maximum(np.abs(actual), 1e-6)
    mape = float(np.mean(np.abs((predicted - actual) / denominators)))
    return Metrics(hit_rate=hit, mae=mae, mape=mape, rows=len(predicted))


def walk_forward(
    frame,  # history.SessionFrame
    policy: Policy,
    fit_window: int,
    score_window: int,
) -> Backtest:
    """Fit/score slide over the frame. Raises when the frame is too short."""
    rows_needed = fit_window + score_window
    usable = len(frame)
    if usable < rows_needed:
        raise ValueError(f"backtest needs {rows_needed} usable rows, frame has {usable}")
    predictions: list[float] = []
    labels: list[float] = []
    dates: list = []
    scored: list[Slice] = []
    start = 0
    while start + rows_needed <= usable:
        fit_end = start + fit_window
        score_end = fit_end + score_window
        policy_fit = type(policy)(**_reconstruct_args(policy))
        policy_fit.fit(
            frame.features[start:fit_end],
            frame.labels[start:fit_end],
        ) if hasattr(policy_fit, "fit") else None
        block_predictions = [
            policy_fit.predict(feature) for feature in frame.features[fit_end:score_end]
        ]
        scored.append(
            Slice(
                dates=tuple(frame.dates[fit_end:score_end]),
                predicted=tuple(block_predictions),
                actual=tuple(float(v) for v in frame.labels[fit_end:score_end]),
            )
        )
        predictions.extend(block_predictions)
        labels.extend(float(v) for v in frame.labels[fit_end:score_end])
        dates.extend(frame.dates[fit_end:score_end])
        start += score_window
    return Backtest(
        policy=policy.name,
        horizon=frame.horizon,
        metrics=metric_row(predictions, labels, dates),
        rows=scored,
    )


def _reconstruct_args(policy: Policy) -> dict:
    """Instance-recycling constructor args for a fresh same-class policy."""
    return {key: getattr(policy, key) for key in _init_keys(policy)}


def _init_keys(policy: Policy) -> list[str]:
    if hasattr(policy, "lags"):
        return ["lags", "alpha"]
    if hasattr(policy, "k"):
        return ["k"]
    return []
