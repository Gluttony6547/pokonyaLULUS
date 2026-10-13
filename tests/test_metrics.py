"""Scores come from the committed holdout, and the scorer itself is checked by hand."""

from __future__ import annotations

import pytest

from idx_signal import config
from idx_signal.metrics import CLASSES, MetricsUnavailable, evaluate, score_classes


def test_perfect_predictions_score_one():
    labels = ["BUY", "HOLD", "SELL"] * 4
    result = score_classes(labels, list(labels))
    assert result["accuracy"] == 1.0
    assert result["precision"] == result["recall"] == result["f1"] == 1.0


def test_confusion_matrix_is_counted_correctly():
    actual = ["BUY", "BUY", "SELL", "HOLD"]
    predicted = ["BUY", "HOLD", "SELL", "HOLD"]
    result = score_classes(actual, predicted)
    assert result["confusion"]["BUY"] == {"SELL": 0, "HOLD": 1, "BUY": 1}
    assert result["accuracy"] == 0.75
    assert result["per_class"]["HOLD"]["support"] == 1


def test_a_class_that_never_appears_scores_zero_rather_than_erroring():
    result = score_classes(["BUY", "HOLD"], ["BUY", "HOLD"])
    assert result["per_class"]["SELL"] == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "support": 0,
    }


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        score_classes(["BUY"], ["BUY", "HOLD"])


def test_holdout_metrics_come_from_the_committed_research_output(reference_assets):
    result = evaluate("ADRO", 1)

    assert result["source"] == "reference holdout (test split)"
    assert result["rows"] > 0
    assert 0.0 <= result["accuracy"] <= 1.0
    assert set(result["per_class"]) == set(CLASSES)
    assert sum(result["per_class"][label]["support"] for label in CLASSES) == result["rows"]
    assert sum(
        sum(confusion.values()) for confusion in result["confusion"].values()
    ) == result["rows"]


def test_missing_research_output_is_reported(reference_assets, monkeypatch):
    monkeypatch.setattr(
        config, "result_file", lambda symbol, horizon: config.PROJECT_DIR / "tidak-ada.csv"
    )
    with pytest.raises(FileNotFoundError):
        evaluate("ADRO", 1)
