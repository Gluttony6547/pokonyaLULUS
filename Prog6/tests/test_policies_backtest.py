from __future__ import annotations

import numpy as np
import pytest

from prog6.backtest import metric_row, walk_forward
from prog6.history import build_frame
from prog6.policies import MomentumPolicy, RidgePolicy, policies_for


def constant_frame(rows: int = 200, drift: float = 0.002) -> np.ndarray:
    """A frame whose labels follow a constant drift, learnable by ridge."""
    closes = list(100.0 * np.exp(drift * np.arange(rows + 10)))
    return build_frame([f"d{i}" for i in range(len(closes))], closes, horizon=1, lags=5)


def test_momentum_policy_continues_a_steady_trend():
    drift = 0.002
    return_row = np.full(5, drift)
    policy = MomentumPolicy(k=5)
    policy.fit(np.empty((5, 5)), np.ones(5))
    assert policy.predict(return_row) == pytest.approx(drift)


def test_ridge_policy_recovers_constant_drift_from_synthetic_data():
    drift = 0.002
    rng = np.random.default_rng(7)
    features = np.full((60, 5), drift)
    labels = np.full(60, drift) + rng.normal(0, 1e-5, 60)
    policy = RidgePolicy(lags=5, alpha=0.1)
    policy.fit(features, labels)
    assert policy.predict(np.full(5, drift)) == pytest.approx(drift, abs=1e-4)


def test_ridge_policy_raises_before_fit():
    policy = RidgePolicy()
    with pytest.raises(RuntimeError):
        policy.predict(np.zeros(5))


def test_policy_set_covers_requested_horizons():
    set_for = policies_for((1, 5, 10))
    assert sorted(set_for) == [1, 5, 10]
    assert all(len(value) == 3 for value in set_for.values())


def test_metric_row_matches_for_clean_hits():
    metrics = metric_row([0.01, -0.01], [0.02, -0.02], ["d1", "d2"])
    assert metrics.hit_rate == 1.0
    assert metrics.rows == 2


def test_metric_row_rejects_length_mismatch():
    with pytest.raises(ValueError):
        metric_row([0.01], [0.01, 0.02], ["d1", "d2"])


def test_walk_forward_scores_every_row_exactly_once():
    frame = constant_frame(rows=200)
    backtest = walk_forward(frame=frame, policy=MomentumPolicy(k=5), fit_window=120, score_window=20)
    # 200 usable rows: first 120 fit, remaining 80 scored. Score window 20
    # means 4 blocks, starting at offsets 120, 140, 160, 180.
    assert backtest.metrics.rows == 80
    assert len(backtest.rows) == 4


def test_walk_forward_rejects_short_frame():
    closes = list(100.0 * np.exp(0.001 * np.arange(50)))
    frame = build_frame([f"d{i}" for i in range(50)], closes, horizon=1, lags=5)
    with pytest.raises(ValueError):
        walk_forward(frame, MomentumPolicy(), fit_window=120, score_window=20)


def test_walk_forward_respects_fit_score_disjointness():
    drift = 0.02
    closes = list(100.0 * np.exp(drift * np.arange(300)))
    frame = build_frame([f"d{i}" for i in range(300)], closes, horizon=1, lags=5)
    backtest = walk_forward(frame, MomentumPolicy(k=5), fit_window=100, score_window=50)
    # On a constant-drift series the momentum policy nails every sign.
    assert backtest.metrics.hit_rate > 0.95
    assert backtest.metrics.mae < 0.005
