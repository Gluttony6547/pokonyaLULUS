from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import train_test_split

from prog5 import config
from prog5.model_registry import artifact_inventory, input_scaler, predict_price, target_scaler

from .conftest import requires_artifacts, requires_research

# Verified against the committed research CSVs (see Prog5/NOTE.md).
ADRO_INPUT_MEAN = 1889.948717948718
ADRO_INPUT_SCALE = 884.8597730052891
ADRO_T50_TARGET_MEAN = 1926.548717948718
ADRO_T50_TARGET_SCALE = 893.3022065583102
ADRO_T50_LAST_WINDOW_PREDICTION = 2502.67


@requires_research
def test_research_split_has_the_notebook_shape():
    closes = np.asarray(
        pd.read_csv(config.fusion_file("ADRO"), usecols=["close"])["close"].dropna(), dtype=float
    )[50:]
    train, test = train_test_split(closes, test_size=0.2, random_state=0)
    assert (len(train), len(test)) == (975, 244)


@requires_research
def test_input_scaler_matches_the_verified_reconstruction():
    scaler = input_scaler("ADRO")
    assert scaler.n_features_in_ == 1
    assert float(scaler.mean_[0]) == pytest.approx(ADRO_INPUT_MEAN, rel=1e-12)
    assert float(scaler.scale_[0]) == pytest.approx(ADRO_INPUT_SCALE, rel=1e-12)


@requires_research
def test_target_scaler_matches_the_verified_reconstruction():
    scaler = target_scaler("ADRO", 50)
    assert scaler.n_features_in_ == 1
    assert float(scaler.mean_[0]) == pytest.approx(ADRO_T50_TARGET_MEAN, rel=1e-12)
    assert float(scaler.scale_[0]) == pytest.approx(ADRO_T50_TARGET_SCALE, rel=1e-12)


@requires_artifacts
def test_inventory_covers_every_ticker_and_horizon():
    inventory = artifact_inventory()
    assert set(inventory) == set(config.SUPPORTED_SYMBOLS)
    assert all(count == len(config.HORIZONS) for count in inventory.values())


@requires_artifacts
def test_predict_price_reproduces_the_last_research_window():
    closes = pd.read_csv(config.fusion_file("ADRO"), usecols=["close"])["close"].to_numpy(float)
    predicted = predict_price("ADRO", 50, closes)
    assert predicted == pytest.approx(ADRO_T50_LAST_WINDOW_PREDICTION, abs=0.5)


@requires_artifacts
def test_predict_price_rejects_short_input():
    from prog5.model_registry import ModelUnavailable

    with pytest.raises(ModelUnavailable):
        predict_price("ADRO", 50, [2500.0, 2510.0])
