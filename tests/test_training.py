"""Retraining produces a candidate, and a candidate never serves by accident."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select

from idx_signal import db
from idx_signal.historical import signals_for_date
from idx_signal.models import ModelArtifact, ModelVersion, TrainingJob
from idx_signal.storage import active_model_version, store_prices
from idx_signal.training import (
    TrainingUnavailable,
    activate_version,
    build_samples,
    queue_training_job,
    run_job,
)


def test_samples_pair_each_window_with_the_close_after_it():
    closes = np.arange(1, 401, dtype=float)
    horizon = 3
    sample = build_samples(closes, horizon)

    # A window covers `horizon` closes and its target sits `horizon` further on,
    # so the usable count is len - 2 * horizon + 1.
    assert sample.windows.shape == (400 - 2 * horizon + 1, horizon)
    assert sample.windows[0].tolist() == [1.0, 2.0, 3.0]
    assert sample.current[0] == 3.0  # last close of the first window
    assert sample.targets[0] == 6.0  # close three sessions after that
    assert sample.targets[-1] == closes[-1]


def test_too_little_history_is_reported():
    with pytest.raises(TrainingUnavailable):
        build_samples(np.arange(1, 40, dtype=float), 5)


def test_queueing_reports_the_existing_model(reference_assets):
    from idx_signal.refresh import ensure_model_versions

    with db.session() as session:
        ensure_model_versions(session, ["ADRO"], [1])
        job, existing = queue_training_job(session, "ADRO", 1)
    assert job is None
    assert existing is not None


def test_force_queues_even_when_a_model_exists(reference_assets):
    from idx_signal.refresh import ensure_model_versions

    with db.session() as session:
        ensure_model_versions(session, ["ADRO"], [1])
        job, _ = queue_training_job(session, "ADRO", 1, force=True)
    assert job is not None
    assert job.status == "queued"


def test_a_run_registers_an_inactive_candidate(prices):
    with db.session() as session:
        store_prices(session, "ADRO", prices)
        job, _ = queue_training_job(session, "ADRO", 1, force=True)
        job_id = job.id

    finished = run_job(job_id)

    assert finished is not None
    assert finished.status == "success", finished.error_message
    assert finished.finished_at is not None

    with db.session() as session:
        version = session.get(ModelVersion, finished.model_version_id)
        assert version is not None
        assert version.is_active is False
        assert version.config["source"] == "retrained"
        assert version.metrics["source"] == "retrained ensemble, chronological holdout"
        assert version.metrics["rows"] > 0
        assert 0.0 <= version.metrics["accuracy"] <= 1.0
        # The candidate stays out of the serving path until it is activated.
        assert active_model_version(session, "ADRO", 1) is None
        stored = session.get(ModelArtifact, version.id)
        assert stored is not None and stored.content


def test_activating_a_candidate_makes_it_the_serving_version(prices):
    with db.session() as session:
        store_prices(session, "ADRO", prices)
        job, _ = queue_training_job(session, "ADRO", 1, force=True)
        job_id = job.id
    finished = run_job(job_id)

    with db.session() as session:
        version = activate_version(session, finished.model_version_id)
        assert version.is_active is True
        active = active_model_version(session, "ADRO", 1)
        assert active.id == version.id


def test_a_failed_run_is_recorded_as_failed():
    # No stored prices for this ticker, so training cannot produce samples.
    with db.session() as session:
        job, _ = queue_training_job(session, "TLKM", 5, force=True)
        job_id = job.id

    finished = run_job(job_id)

    assert finished.status == "failed"
    assert "TrainingUnavailable" in finished.error_message
    with db.session() as session:
        assert session.scalar(select(ModelVersion).where(ModelVersion.symbol == "TLKM")) is None
        row = session.get(TrainingJob, job_id)
        assert row.status == "failed"


def test_a_trained_artifact_is_stored_in_the_database(prices):
    with db.session() as session:
        store_prices(session, "ADRO", prices)
        job, _ = queue_training_job(session, "ADRO", 1, force=True)
        job_id = job.id
    finished = run_job(job_id)

    assert finished.status == "success", finished.error_message
    with db.session() as session:
        version = session.get(ModelVersion, finished.model_version_id)
        stored = session.get(ModelArtifact, version.id)
    assert stored is not None and stored.content
    assert version.artifact_sha256 == hashlib.sha256(stored.content).hexdigest()


def test_an_activated_database_artifact_recomputes_signals(prices):
    with db.session() as session:
        store_prices(session, "ADRO", prices)
        job, _ = queue_training_job(session, "ADRO", 1, force=True)
        job_id = job.id
    finished = run_job(job_id)

    with db.session() as session:
        version = session.get(ModelVersion, finished.model_version_id)
        # Nothing on disk may be needed once the version serves predictions.
        assert not Path(version.artifact_path).exists()
        activate_version(session, version.id)
    reference = prices.iloc[-1]["date"]
    with db.session() as session:
        result = signals_for_date(session, "ADRO", reference, horizons=(1,))

    row = result.signals[0]
    assert row.model_version_id == version.id
    assert row.predicted_price > 0
