from __future__ import annotations

import pytest

from prog5 import config
from prog5.signals import (
    classify_return,
    is_out_of_distribution,
    out_of_distribution_z,
    signal_label,
)


def test_buy_at_exact_threshold():
    signal, change = classify_return(2030.0, 2000.0, 1)
    assert signal == 1
    assert change == pytest.approx(1.5)


def test_sell_at_exact_threshold():
    signal, change = classify_return(1970.0, 2000.0, 1)
    assert signal == -1
    assert change == pytest.approx(-1.5)


def test_hold_inside_threshold():
    signal, change = classify_return(2010.0, 2000.0, 1)
    assert signal == 0
    assert change == pytest.approx(0.5)


def test_hold_when_direction_matches_but_change_is_below_threshold():
    # The notebook compares direction first, then the threshold, so a small
    # move in the right direction is still a hold.
    signal, _ = classify_return(2020.0, 2000.0, 50)
    assert signal == 0


def test_buy_at_fifty_day_threshold():
    signal, change = classify_return(2220.0, 2000.0, 50)
    assert signal == 1
    assert change == pytest.approx(11.0)


def test_hold_when_price_is_unchanged():
    signal, change = classify_return(2000.0, 2000.0, 10)
    assert signal == 0
    assert change == 0.0


def test_all_horizons_have_thresholds():
    assert set(config.RETURN_THRESHOLDS) == set(config.HORIZONS)


def test_unknown_horizon_is_rejected():
    with pytest.raises(ValueError):
        classify_return(2000.0, 2000.0, 7)


def test_non_positive_current_price_is_rejected():
    with pytest.raises(ValueError):
        classify_return(2000.0, 0.0, 1)


def test_signal_labels():
    assert [signal_label(signal) for signal in (-1, 0, 1)] == ["sell", "hold", "buy"]


def test_out_of_distribution_flag_uses_two_sigma():
    assert out_of_distribution_z(2500.0, 1889.948717948718, 884.8597730052891) == pytest.approx(
        0.6896, abs=1e-3
    )
    assert not is_out_of_distribution(0.6896)
    assert is_out_of_distribution(2.13)
    assert not is_out_of_distribution(2.0)


def test_out_of_distribution_rejects_zero_scale():
    with pytest.raises(ValueError):
        out_of_distribution_z(100.0, 100.0, 0.0)
