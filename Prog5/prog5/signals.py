"""Signal thresholds and out-of-distribution scoring, following the notebooks."""

from __future__ import annotations

from . import config


def classify_return(predicted_price: float, current_price: float, horizon_days: int) -> tuple[int, float]:
    """Return (signal, return percent) using the pipeline's buy/sell/hold rule.

    The notebooks branch on direction first and compare the absolute change
    against the threshold, so exactly-at-threshold counts as buy or sell.
    """
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if horizon_days not in config.RETURN_THRESHOLDS:
        raise ValueError(f"Unsupported horizon: {horizon_days}")

    threshold_pct = config.RETURN_THRESHOLDS[horizon_days] * 100.0
    change_pct = (predicted_price - current_price) / current_price * 100.0

    if predicted_price > current_price and change_pct >= threshold_pct:
        signal = 1
    elif predicted_price < current_price and abs(change_pct) >= threshold_pct:
        signal = -1
    else:
        signal = 0
    return signal, change_pct


def signal_label(signal: int) -> str:
    return config.SIGNAL_LABELS[signal]


def out_of_distribution_z(last_close: float, mean: float, scale: float) -> float:
    if scale <= 0:
        raise ValueError("scaler scale must be positive")
    return (last_close - mean) / scale


def is_out_of_distribution(z: float) -> bool:
    return abs(z) > config.OOD_Z_THRESHOLD
