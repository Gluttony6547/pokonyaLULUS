"""Prove the registry reproduces the committed research predictions.

Rebuilds the sliding windows exactly as pipeline_process.ipynb did, runs them
through the same scalers the registry uses, and compares against
CODE/Result Price Prediction/{SYMBOL}/LSTM_{SYMBOL}_Target_{H}.csv mapped
through the notebook's own train/test split.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from . import config
from .model_registry import input_scaler, load_model, target_scaler

TOLERANCE_IDR = 0.01


def notebook_windows(closes: np.ndarray, horizon: int) -> np.ndarray:
    """Windows exactly as pipeline_process.ipynb builds them."""
    raw = np.array([closes[i : i + horizon] for i in range(len(closes) - horizon + 1)])
    return raw[50 + 1 - horizon :]


def verify(symbol: str, horizons: tuple[int, ...] = config.HORIZONS, batch_size: int = 256) -> list[dict]:
    close = pd.read_csv(config.fusion_file(symbol), usecols=["close"])["close"].dropna().to_numpy(float)
    scaler_in = input_scaler(symbol)
    results: list[dict] = []

    for horizon in horizons:
        result_path = config.result_file(symbol, horizon)
        research = pd.read_csv(result_path)
        windows = notebook_windows(close, horizon)
        scaled = np.stack([scaler_in.transform(window.reshape(-1, 1)).ravel() for window in windows])
        model = load_model(symbol, horizon)
        predicted_scaled = np.asarray(
            model.predict(scaled, verbose=0, batch_size=batch_size)
        ).ravel()
        predicted = (
            target_scaler(symbol, horizon)
            .inverse_transform(predicted_scaled.reshape(-1, 1))
            .ravel()
        )

        index = np.arange(len(windows)).reshape(-1, 1)
        train_index, test_index = train_test_split(index, test_size=0.2, random_state=0)
        train_index, test_index = train_index.ravel(), test_index.ravel()
        reference_train = research.loc[research["type"] == "train", "close_prediction"].to_numpy()
        reference_test = research.loc[research["type"] == "test", "close_prediction"].to_numpy()

        diff_train = float(np.abs(reference_train - predicted[train_index]).max())
        diff_test = float(np.abs(reference_test - predicted[test_index]).max())
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
                "result_csv": str(result_path),
            }
        )
    return results
