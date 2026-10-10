from __future__ import annotations

import numpy as np
import pytest

from prog6.history import build_frame, forward_returns, lag_matrix, last_feature_vector, log_returns


def test_log_returns_of_monotone_growth():
    closes = [100.0, 110.0, 121.0]
    np.testing.assert_allclose(log_returns(closes), [np.log(1.1), np.log(1.1)])


def test_log_returns_reject_nonpositive():
    with pytest.raises(ValueError):
        log_returns([100.0, 0.0])


def test_lag_matrix_shape_and_alignment():
    returns = np.array([0.1, 0.2, 0.3, 0.4])
    matrix = lag_matrix(returns, lags=3)
    assert matrix.shape == (2, 3)
    np.testing.assert_allclose(matrix[0], [0.1, 0.2, 0.3])
    np.testing.assert_allclose(matrix[1], [0.2, 0.3, 0.4])


def test_forward_returns_sums_the_window_starting_at_each_position():
    returns = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    horizon_2 = forward_returns(returns, 2)
    # Position 0 sums r0+r1, position 1 sums r1+r2, position 2 sums r2+r3:
    np.testing.assert_allclose(horizon_2, [0.3, 0.5, 0.7])


def test_build_frame_row_alignment():
    # 12 closes, horizon 2, lags 3: returns has 11 entries, labels has 9,
    # pairs = 9 - 3 = 6.
    dates = [f"2026-01-{day:02d}" for day in range(1, 13)]
    closes = [100.0 + 5 * i for i in range(12)]
    frame = build_frame(dates, closes, horizon=2, lags=3)
    assert len(frame) == 6
    assert frame.features.shape == (6, 3)
    assert frame.labels.shape == (6,)
    # Pair 0: features from returns 0..2 (closes 0..3), label from close 3 two
    # sessions ahead, so the as-of date is dates[3] and labels[3] = log(c5/c3).
    import numpy as np
    expected_label = np.log(closes[5] / closes[3])
    np.testing.assert_allclose(frame.labels[0], expected_label)
    np.testing.assert_allclose(
        frame.features[0],
        [np.log(closes[1] / closes[0]), np.log(closes[2] / closes[1]), np.log(closes[3] / closes[2])],
    )
    assert frame.dates[0] == "2026-01-04"


def test_build_frame_rejects_insufficient_history():
    with pytest.raises(ValueError):
        build_frame(["a", "b"], [100.0, 101.0], horizon=5)


def test_last_feature_vector_is_the_newest_lags_returns():
    closes = [100.0, 105.0, 110.0]
    feature = last_feature_vector(closes, lags=2)
    np.testing.assert_allclose(feature, [np.log(105 / 100), np.log(110 / 105)])
