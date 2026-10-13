"""Holdout metrics for a model, from the committed research output.

`CODE/Result Price Prediction/{SYMBOL}/LSTM_{SYMBOL}_Target_{H}.csv` holds the
reference run's own predictions for every window, split into train and test by
the notebook's train_test_split. Scoring the test rows against their labels
gives the accuracy, precision, recall, and F1 the dashboard reports per model
version, without inventing numbers. `replication.py` is what ties those rows to
the artifact that is actually serving predictions.
"""

from __future__ import annotations

import pandas as pd

from . import config

CLASSES = ("SELL", "HOLD", "BUY")


class MetricsUnavailable(RuntimeError):
    """The research output needed for scoring is missing or malformed."""


def score_classes(actual: list[str], predicted: list[str]) -> dict:
    """Confusion matrix plus macro precision, recall, and F1 over three classes."""
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted must have the same length")
    if not actual:
        raise ValueError("nothing to score")

    confusion = {truth: {guess: 0 for guess in CLASSES} for truth in CLASSES}
    for truth, guess in zip(actual, predicted):
        confusion[truth][guess] += 1

    total = len(actual)
    correct = sum(confusion[label][label] for label in CLASSES)
    per_class: dict[str, dict[str, float | int]] = {}
    macro_precision = macro_recall = macro_f1 = 0.0
    for label in CLASSES:
        true_positive = confusion[label][label]
        predicted_positive = sum(confusion[truth][label] for truth in CLASSES)
        actual_positive = sum(confusion[label].values())
        precision = true_positive / predicted_positive if predicted_positive else 0.0
        recall = true_positive / actual_positive if actual_positive else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": actual_positive,
        }
        macro_precision += precision / len(CLASSES)
        macro_recall += recall / len(CLASSES)
        macro_f1 += f1 / len(CLASSES)

    return {
        "rows": total,
        "accuracy": round(correct / total, 4),
        "precision": round(macro_precision, 4),
        "recall": round(macro_recall, 4),
        "f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion": confusion,
    }


def evaluate(symbol: str, horizon_days: int) -> dict:
    """Scores for the reference model's holdout rows."""
    frame = pd.read_csv(config.result_file(symbol, horizon_days))
    required = {"type", "ground_truth", "prediction"}
    missing = required - set(frame.columns)
    if missing:
        raise MetricsUnavailable(
            f"Research output for {symbol} T{horizon_days} lacks {sorted(missing)}"
        )

    holdout = frame[frame["type"].astype(str).str.strip().str.lower() == "test"]
    if holdout.empty:
        raise MetricsUnavailable(f"Research output for {symbol} T{horizon_days} has no test rows.")

    actual = [config.SIGNAL_FOR_RESEARCH_CLASS.get(int(value)) for value in holdout["ground_truth"]]
    predicted = [config.SIGNAL_FOR_RESEARCH_CLASS.get(int(value)) for value in holdout["prediction"]]
    if any(label is None for label in (*actual, *predicted)):
        raise MetricsUnavailable(
            f"Research output for {symbol} T{horizon_days} has classes outside SELL/HOLD/BUY."
        )

    result = score_classes(actual, predicted)
    result["source"] = "reference holdout (test split)"
    return result
