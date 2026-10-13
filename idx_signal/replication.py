"""Prove that the serving path reproduces the committed research predictions.

Rebuilds the sliding windows exactly as the training notebook did, runs them
through the same scalers and artifacts the service uses, and compares the
result with CODE/Result Price Prediction/{SYMBOL}/LSTM_{SYMBOL}_Target_{H}.csv
after applying the notebook's own train/test split. This is the evidence behind
the accuracy figures the dashboard shows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from . import config
from .model_registry import load_model, reference_artifact, scalers_from_research

TOLERANCE_IDR = 0.01


def notebook_windows(closes: np.ndarray, horizon: int) -> np.ndarray:
    """Sliding windows exactly as the training notebook builds them."""
    raw = np.array([closes[i : i + horizon] for i in range(len(closes) - horizon + 1)])
    return raw[50 + 1 - horizon :]


def verify(
    symbol: str, horizons: tuple[int, ...] = config.HORIZONS, batch_size: int = 256
) -> list[dict]:
    closes = (
        pd.read_csv(config.fusion_file(symbol), usecols=["close"])["close"].dropna().to_numpy(float)
    )
    results: list[dict] = []

    for horizon in horizons:
        research = pd.read_csv(config.result_file(symbol, horizon))
        windows = notebook_windows(closes, horizon)
        scalers = scalers_from_research(symbol, horizon)
        scaled = np.stack(
            [(window - scalers.input_mean) / scalers.input_scale for window in windows]
        )
        model = load_model(reference_artifact(symbol, horizon)["path"], horizon)
        predicted_scaled = np.asarray(model.predict(scaled, verbose=0, batch_size=batch_size)).ravel()
        predicted = predicted_scaled * scalers.target_scale + scalers.target_mean

        index = np.arange(len(windows)).reshape(-1, 1)
        train_index, test_index = train_test_split(index, test_size=0.2, random_state=0)
        reference_train = research.loc[research["type"] == "train", "close_prediction"].to_numpy()
        reference_test = research.loc[research["type"] == "test", "close_prediction"].to_numpy()

        diff_train = float(np.abs(reference_train - predicted[train_index.ravel()]).max())
        diff_test = float(np.abs(reference_test - predicted[test_index.ravel()]).max())
        max_diff = max(diff_train, diff_test)
        results.append(
            {
                "symbol": symbol,
                "horizon_days": horizon,
                "rows": int(len(research)),
                "max_abs_diff": max_diff,
                "max_abs_diff_train": diff_train,
                "max_abs_diff_test": diff_test,
                "verdict": "reproduced" if max_diff < TOLERANCE_IDR else "mismatch",
            }
        )
    return results
