"""Registry for the saved LSTM artifacts.

The reference notebooks never persisted their StandardScalers, so they are
rebuilt here from the committed research series using the split the training
script used: train_test_split(..., test_size=0.2, random_state=0). A
StandardScaler over one feature is fully described by its mean and scale, so
those two numbers are stored per model version and inference no longer needs
the research CSVs at runtime. `replication.py` proves the rebuilt path still
reproduces the committed research predictions.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from . import config

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """An artifact or an input the prediction path cannot work with."""


@dataclass(frozen=True)
class Scalers:
    """The two one-feature StandardScalers a saved model needs."""

    input_mean: float
    input_scale: float
    target_mean: float
    target_scale: float

    def as_config(self) -> dict[str, float]:
        return {
            "input_mean": self.input_mean,
            "input_scale": self.input_scale,
            "target_mean": self.target_mean,
            "target_scale": self.target_scale,
        }

    @classmethod
    def from_config(cls, payload: dict) -> "Scalers":
        try:
            return cls(
                input_mean=float(payload["input_mean"]),
                input_scale=float(payload["input_scale"]),
                target_mean=float(payload["target_mean"]),
                target_scale=float(payload["target_scale"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ModelUnavailable(
                "versi model ini belum menyimpan skalernya, jalankan ulang perintah register"
            ) from error


@lru_cache(maxsize=8)
def _fusion_closes(symbol: str) -> tuple[float, ...]:
    frame = pd.read_csv(config.fusion_file(symbol), usecols=["close"])
    return tuple(frame["close"].dropna().astype(float).tolist())


@lru_cache(maxsize=8)
def _labelled_closes(symbol: str) -> tuple[float, ...]:
    frame = pd.read_csv(config.labelled_file(symbol), usecols=["close"])
    return tuple(frame["close"].dropna().astype(float).tolist())


@lru_cache(maxsize=16)
def _train_indices(length: int) -> np.ndarray:
    """The train half of the notebook's shuffle, which depends only on length."""
    train, _ = train_test_split(np.arange(length).reshape(-1, 1), test_size=0.2, random_state=0)
    return train.ravel()


def scalers_from_research(symbol: str, horizon_days: int) -> Scalers:
    """Rebuild the input and target scalers the training notebook used."""
    closes = np.asarray(_fusion_closes(symbol), dtype=float)
    if closes.size <= 50:
        raise ModelUnavailable(f"deret penutup riset {symbol} terlalu pendek")
    inputs = closes[50:]
    input_scaler = StandardScaler().fit(inputs[_train_indices(inputs.size)].reshape(-1, 1))

    # The target series is the close shifted back by the horizon: what the
    # price becomes H sessions later.
    targets = pd.Series(_labelled_closes(symbol), dtype=float).shift(-horizon_days).iloc[50:-50]
    target_values = targets.dropna().to_numpy(dtype=float)
    if target_values.size < 50:
        raise ModelUnavailable(f"deret target {symbol} T{horizon_days} terlalu pendek")
    target_scaler = StandardScaler().fit(
        target_values[_train_indices(target_values.size)].reshape(-1, 1)
    )

    return Scalers(
        input_mean=float(input_scaler.mean_[0]),
        input_scale=float(input_scaler.scale_[0]),
        target_mean=float(target_scaler.mean_[0]),
        target_scale=float(target_scaler.scale_[0]),
    )


@lru_cache(maxsize=4)
def artifact_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=64)
def load_model(artifact_path: str, horizon_days: int):
    path = Path(artifact_path)
    try:
        import keras
    except ImportError as error:  # pragma: no cover - environment dependent
        raise ModelUnavailable(f"Keras tidak bisa diimpor: {error}") from error
    try:
        model = keras.models.load_model(str(path), compile=False)
    except Exception as error:
        raise ModelUnavailable(f"berkas {path.name} gagal dimuat: {error}") from error

    expected = (horizon_days, 1)
    if tuple(model.input_shape[-2:]) != expected:
        raise ModelUnavailable(
            f"{path.name} mengharapkan masukan {tuple(model.input_shape)}, bukan {expected}"
        )
    return model


def reference_artifact(symbol: str, horizon_days: int) -> dict[str, str]:
    """Path and digest of the saved reference artifact for one ticker and horizon."""
    path: Path = config.artifact_file(symbol, horizon_days)
    return {"file": path.name, "path": str(path), "sha256": artifact_sha256(str(path))}


def build_model(horizon_days: int, units: int = 96, dropout: float = 0.2):
    """The reference architecture: three stacked LSTMs and a scalar output."""
    import keras

    return keras.Sequential(
        [
            keras.layers.Input(shape=(horizon_days, 1)),
            keras.layers.LSTM(units, return_sequences=True),
            keras.layers.Dropout(dropout),
            keras.layers.LSTM(units, return_sequences=True),
            keras.layers.Dropout(dropout),
            keras.layers.LSTM(units),
            keras.layers.Dropout(dropout),
            keras.layers.Dense(1),
        ]
    )


def predict_price(
    artifact_path: str,
    horizon_days: int,
    closes: pd.Series | np.ndarray,
    scalers: Scalers,
) -> float:
    """Predict the close `horizon_days` sessions ahead from the last H closes."""
    values = np.asarray(closes, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < horizon_days:
        raise ModelUnavailable(
            f"T{horizon_days} butuh minimal {horizon_days} harga penutup, hanya ada {values.size}"
        )
    window = values[-horizon_days:]
    if window[-1] <= 0:
        raise ModelUnavailable("harga penutup terakhir tidak bisa dipakai untuk prediksi")

    # Both scalers cover a single feature, so their stored mean and scale
    # reproduce sklearn's transform exactly.
    scaled = (window - scalers.input_mean) / scalers.input_scale
    model = load_model(artifact_path, horizon_days)
    predicted_scaled = np.asarray(
        model.predict(scaled.reshape(1, horizon_days, 1), verbose=0)
    ).reshape(-1)[0]
    predicted = float(predicted_scaled) * scalers.target_scale + scalers.target_mean
    if not np.isfinite(predicted) or predicted <= 0:
        raise ModelUnavailable("model menghasilkan harga yang tidak bisa dipakai")
    return predicted


def artifact_filename(path: str) -> str:
    """Model filename from a path persisted on any operating system."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


@lru_cache(maxsize=4)
def artifact_inventory(symbols: tuple[str, ...] = config.SUPPORTED_SYMBOLS) -> dict[str, int]:
    """How many artifacts resolve per ticker (5 when the set is complete)."""
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
    """Drop cached models and scalers (tests that repoint the artifact dir)."""
    _fusion_closes.cache_clear()
    _labelled_closes.cache_clear()
    _train_indices.cache_clear()
    artifact_sha256.cache_clear()
    load_model.cache_clear()
    artifact_inventory.cache_clear()
