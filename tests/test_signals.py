"""The buy/hold/sell rule has to agree with the reference notebooks exactly."""

from __future__ import annotations

import pytest

from idx_signal.signals import (
    SignalError,
    classify_return,
    is_out_of_distribution,
    out_of_distribution_z,
)


def test_threshold_is_inclusive():
    # T+1 uses 1.5 percent. The notebooks branch on direction first and then
    # compare the absolute change, so exactly at the threshold is a signal.
    assert classify_return(1015.0, 1000.0, 1) == ("BUY", 1.5)
    assert classify_return(985.0, 1000.0, 1) == ("SELL", -1.5)


def test_change_inside_the_threshold_is_hold():
    assert classify_return(1014.0, 1000.0, 1)[0] == "HOLD"
    assert classify_return(986.5, 1000.0, 1)[0] == "HOLD"
    assert classify_return(1000.0, 1000.0, 1)[0] == "HOLD"


def test_each_horizon_uses_its_own_threshold():
    predicted = 1000.0 * 1.04
    assert classify_return(predicted, 1000.0, 1)[0] == "BUY"
    assert classify_return(predicted, 1000.0, 5)[0] == "BUY"
    assert classify_return(predicted, 1000.0, 10)[0] == "HOLD"


def test_return_percent_is_signed_and_exact():
    signal, change = classify_return(1100.0, 1000.0, 5)
    assert signal == "BUY"
    assert change == pytest.approx(10.0)


@pytest.mark.parametrize("bad_price", [0, -5, float("nan")])
def test_unusable_reference_price_is_rejected(bad_price):
    with pytest.raises(SignalError):
        classify_return(1010.0, bad_price, 1)


def test_unknown_horizon_is_rejected():
    with pytest.raises(SignalError):
        classify_return(1010.0, 1000.0, 7)


def test_out_of_distribution_boundary():
    assert out_of_distribution_z(1050.0, 1000.0, 25.0) == pytest.approx(2.0)
    assert is_out_of_distribution(2.0) is False
    assert is_out_of_distribution(2.0001) is True
    assert is_out_of_distribution(-2.5) is True


def test_zero_scale_is_rejected():
    with pytest.raises(SignalError):
        out_of_distribution_z(1000.0, 1000.0, 0.0)
