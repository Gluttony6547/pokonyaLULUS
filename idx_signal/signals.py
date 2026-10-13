"""Buy/hold/sell classification, following the reference notebooks.

The notebooks branch on direction first and compare the absolute change against
the horizon threshold, so a change exactly at the threshold counts as buy or
sell rather than hold.
"""

from __future__ import annotations

import math

from . import config


class SignalError(ValueError):
    """A value that cannot produce a signal."""


def classify_return(
    predicted_price: float, current_price: float, horizon_days: int
) -> tuple[str, float]:
    """Return (signal, signed return percent) for one model output."""
    if not math.isfinite(current_price) or current_price <= 0:
        raise SignalError("current_price must be a positive, finite number")
    if horizon_days not in config.RETURN_THRESHOLDS:
        raise SignalError(f"Unsupported horizon: {horizon_days}")

    threshold_pct = config.RETURN_THRESHOLDS[horizon_days] * 100.0
    change_pct = (predicted_price - current_price) / current_price * 100.0

    if predicted_price > current_price and change_pct >= threshold_pct:
        signal = 1
    elif predicted_price < current_price and abs(change_pct) >= threshold_pct:
        signal = -1
    else:
        signal = 0
    return config.SIGNAL_FOR_CLASS[signal], change_pct


def out_of_distribution_z(last_close: float, mean: float, scale: float) -> float:
    if not math.isfinite(scale) or scale <= 0:
        raise SignalError("scaler scale must be a positive, finite number")
    return (last_close - mean) / scale


def is_out_of_distribution(z: float) -> bool:
    """True when the input window sits far outside what the model was trained on."""
    return abs(z) > config.OOD_Z_THRESHOLD
