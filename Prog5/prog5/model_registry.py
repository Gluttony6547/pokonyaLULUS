"""Registry for the lecturer's saved LSTM artifacts.

The notebooks never persisted their StandardScalers, so they are rebuilt here
from the committed research data with the exact same split the training script
used: train_test_split(..., test_size=0.2, random_state=0). `replication.py`
checks the rebuilt path against the committed research result CSVs.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from . import config

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=8)
def _fusion_closes(symbol: str) -> tuple[float, ...]:
    path = config.fusion_file(symbol)
    frame = pd.read_csv(path, usecols=["close"])
    return tuple(frame["close"].dropna().astype(float).tolist())


@lru_cache(maxsize=8)
def _labelled_closes(symbol: str) -> tuple[float, ...]:
    path = config.labelled_file(symbol)
    frame = pd.read_csv(path, usecols=["close"])
    return tuple(frame["close"].dropna().astype(float).tolist())


@lru_cache(maxsize=16)
def input_scaler(symbol: str) -> StandardScaler:
    """Scaler fitted on the training split of the research close series."""
    closes = np.asarray(_fusion_closes(symbol), dtype=float)
    if closes.size <= 50:
        raise ModelUnavailable(f"Research closes for {symbol} are too short.")
    values = closes[50:]
    train, _ = train_test_split(values, test_size=0.2, random_state=0)
    return StandardScaler().fit(train.reshape(-1, 1))


@lru_cache(maxsize=64)
def target_scaler(symbol: str, horizon_days: int) -> StandardScaler:
    """Scaler fitted on the training split of closes shifted by the horizon."""
    closes = pd.Series(_labelled_closes(symbol), dtype=float)
    targets = closes.shift(-horizon_days).iloc[50:-50]
    values = targets.dropna().to_numpy(dtype=float)
    if values.size < 50:
        raise ModelUnavailable(f"Target series for {symbol} T{horizon_days} is too short.")
    train, _ = train_test_split(values, test_size=0.2, random_state=0)
    return StandardScaler().fit(train.reshape(-1, 1))


@lru_cache(maxsize=4)
def artifact_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=64)
def load_model(symbol: str, horizon_days: int):
    path = config.artifact_file(symbol, horizon_days)
    try:
        import keras
    except ImportError as error:  # pragma: no cover - environment dependent
        raise ModelUnavailable(f"Keras is not importable: {error}") from error

    try:
        model = keras.models.load_model(str(path), compile=False)
    except Exception as error:
        raise ModelUnavailable(f"Could not load {path.name}: {error}") from error

    expected = (horizon_days, 1)
    if model.input_shape[-2:] != expected:
        raise ModelUnavailable(
            f"{path.name} expects input {model.input_shape}, not {expected}."
        )
    return model


def model_identity(symbol: str, horizon_days: int) -> dict[str, object]:
    path = config.artifact_file(symbol, horizon_days)
    return {
        "file": path.name,
        "path": str(path),
        "sha256": artifact_sha256(str(path)),
    }


def predict_price(symbol: str, horizon_days: int, closes: pd.Series | np.ndarray) -> float:
    values = np.asarray(closes, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < horizon_days:
        raise ModelUnavailable(
            f"{symbol} T{horizon_days} needs at least {horizon_days} closes, got {values.size}."
        )
    window = values[-horizon_days:]
    if window[-1] <= 0:
        raise ModelUnavailable("Last close is not usable for prediction.")

    model = load_model(symbol, horizon_days)
    scaler_in = input_scaler(symbol)
    scaler_out = target_scaler(symbol, horizon_days)
    scaled = scaler_in.transform(window.reshape(-1, 1))
    predicted_scaled = np.asarray(
        model.predict(scaled.reshape(1, horizon_days, 1), verbose=0)
    ).reshape(-1)[0]
    predicted = float(scaler_out.inverse_transform([[predicted_scaled]])[0, 0])
    if not np.isfinite(predicted) or predicted <= 0:
        raise ModelUnavailable("Model produced an unusable price.")
    return predicted


def artifact_inventory(symbols: tuple[str, ...] = config.SUPPORTED_SYMBOLS) -> dict[str, int]:
    """How many artifacts are resolvable per ticker (expected 5 each)."""
    inventory: dict[str, int] = {}
    for symbol in symbols:
        found = 0
        for horizon in config.HORIZONS:
            try:
                config.artifact_file(symbol, horizon)
                found += 1
            except config.ConfigurationError:
                continue
        inventory[symbol] = found
    return inventory


def clear_caches() -> None:
    """Drop cached models/scalers (tests that repoint PROG5_ARTIFACT_DIR)."""
    _fusion_closes.cache_clear()
    _labelled_closes.cache_clear()
    input_scaler.cache_clear()
    target_scaler.cache_clear()
    artifact_sha256.cache_clear()
    load_model.cache_clear()
