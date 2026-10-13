"""Retraining the reference architecture on the stored price history.

A job trains the same three-layer LSTM stack the reference used, on the closes
this service has stored, and records the result as a *candidate* model version.
Candidates never take over the dashboard on their own: the reference artifacts
stay active until someone activates a candidate, so a training run cannot
silently change the signals a user is reading.

The holdout is chronological rather than the reference's random split, because
a random split lets a window and its own target land on opposite sides of the
line. The metrics therefore describe forward performance, which is the question
a reader of the dashboard actually has.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, db
from .metrics import score_classes
from .model_registry import Scalers, artifact_sha256, build_model
from .models import ModelVersion, TrainingJob
from .signals import classify_return
from .storage import active_model_version, price_frame, register_model_version

logger = logging.getLogger(__name__)

MINIMUM_SAMPLES = 150


class TrainingUnavailable(RuntimeError):
    """Not enough stored history, or the framework refused the run."""


@dataclass(frozen=True)
class Sample:
    windows: np.ndarray
    targets: np.ndarray
    current: np.ndarray


def build_samples(closes: np.ndarray, horizon_days: int) -> Sample:
    """Sliding windows and the close H sessions after each window's end."""
    closes = np.asarray(closes, dtype=float)
    closes = closes[np.isfinite(closes)]
    usable = len(closes) - 2 * horizon_days + 1
    if usable < MINIMUM_SAMPLES:
        raise TrainingUnavailable(
            f"{len(closes)} harga penutup tersimpan hanya menghasilkan {max(usable, 0)} sampel "
            f"untuk T{horizon_days}, minimal {MINIMUM_SAMPLES}. Jalankan pembaruan data dulu."
        )
    windows = np.stack([closes[i : i + horizon_days] for i in range(usable)])
    targets = np.array([closes[i + 2 * horizon_days - 1] for i in range(usable)])
    return Sample(windows=windows, targets=targets, current=windows[:, -1])


def _retrain(symbol: str, horizon_days: int, epochs: int) -> tuple[dict, str, dict]:
    """Fit a candidate model, returning (metrics, artifact path, config)."""
    import keras

    with db.session() as session:
        frame = price_frame(session, symbol, limit=3000)
    if frame.empty:
        raise TrainingUnavailable(f"belum ada harga tersimpan untuk {symbol}")

    sample = build_samples(frame["close"].to_numpy(dtype=float), horizon_days)
    windows, targets = sample.windows, sample.targets

    # Chronological split: the last fifth of the history is the holdout.
    split = int(len(windows) * 0.8)
    train_x, test_x = windows[:split], windows[split:]
    train_y, test_y = targets[:split], targets[split:]

    input_mean = float(train_x.mean())
    input_scale = float(train_x.std())
    target_mean = float(train_y.mean())
    target_scale = float(train_y.std())
    if not input_scale or not target_scale:
        raise TrainingUnavailable("deret latih tidak punya keragaman untuk diskalakan")

    model = build_model(horizon_days)
    model.compile(optimizer="adam", loss="mean_squared_error")
    model.fit(
        ((train_x - input_mean) / input_scale).reshape(-1, horizon_days, 1),
        (train_y - target_mean) / target_scale,
        validation_data=(
            ((test_x - input_mean) / input_scale).reshape(-1, horizon_days, 1),
            (test_y - target_mean) / target_scale,
        ),
        epochs=epochs,
        batch_size=32,
        verbose=0,
        callbacks=[keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True)],
    )

    raw = np.asarray(
        model.predict(((test_x - input_mean) / input_scale).reshape(-1, horizon_days, 1), verbose=0)
    ).ravel()
    predicted = raw * target_scale + target_mean

    actual_classes: list[str] = []
    predicted_classes: list[str] = []
    for index, price in enumerate(predicted):
        current = float(test_x[index][-1])
        actual_classes.append(classify_return(float(test_y[index]), current, horizon_days)[0])
        predicted_classes.append(classify_return(float(price), current, horizon_days)[0])

    scores = score_classes(actual_classes, predicted_classes)
    scores["source"] = "retrained, chronological holdout"
    scores["epochs"] = epochs
    scores["train_samples"] = int(split)
    scores["test_samples"] = int(len(windows) - split)

    artifact_dir = config.training_dir() / symbol
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir / f"LSTM_{symbol}_Target_{horizon_days}_{stamp}.keras"
    model.save(str(artifact_path))

    scalers = Scalers(
        input_mean=input_mean,
        input_scale=input_scale,
        target_mean=target_mean,
        target_scale=target_scale,
    )
    config_payload = {
        "architecture": "3 x LSTM(96) + Dense(1)",
        "input": "close window, H sessions",
        "source": "retrained",
        "epochs": epochs,
        "data_until": str(frame["date"].iloc[-1]),
        **scalers.as_config(),
    }
    return scores, str(artifact_path), config_payload


def queue_training_job(
    session: Session, symbol: str, horizon_days: int, force: bool = False
) -> tuple[TrainingJob | None, ModelVersion | None]:
    """Queue a job, or hand back the version that already covers the combination."""
    existing = active_model_version(session, symbol, horizon_days)
    if existing is not None and not force:
        # Reference flow A1: the combination already has a model, so nothing is trained.
        return None, existing
    job = TrainingJob(symbol=symbol, horizon_days=horizon_days, status="queued")
    session.add(job)
    session.flush()
    return job, existing


def run_job(job_id: int) -> TrainingJob | None:
    """Execute one queued job, recording its outcome."""
    with db.session() as session:
        job = session.get(TrainingJob, job_id)
        if job is None or job.status not in {"queued", "running"}:
            return job
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        symbol, horizon_days = job.symbol, job.horizon_days

    try:
        scores, artifact_path, config_payload = _retrain(symbol, horizon_days, config.training_epochs())
    except Exception as error:  # a failed run must never look like a successful one
        logger.exception("Training job %s failed", job_id)
        with db.session() as session:
            job = session.get(TrainingJob, job_id)
            if job is not None:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.error_message = f"{type(error).__name__}: {error}"
                session.flush()
                return job
        return None

    with db.session() as session:
        job = session.get(TrainingJob, job_id)
        if job is None:
            return None
        frame = price_frame(session, symbol, limit=1)
        data_until = frame["date"].iloc[-1] if not frame.empty else datetime.now(timezone.utc).date()
        version = register_model_version(
            session,
            symbol=symbol,
            horizon_days=horizon_days,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256(artifact_path),
            data_until=data_until,
            metrics=scores,
            config_payload=config_payload,
        )
        # A candidate stays out of the serving path until it is activated.
        version.is_active = False
        job.status = "success"
        job.finished_at = datetime.now(timezone.utc)
        job.model_version_id = version.id
        session.flush()
        return job


def activate_version(session: Session, version_id: int) -> ModelVersion:
    """Make one version the serving model for its symbol and horizon."""
    version = session.get(ModelVersion, version_id)
    if version is None:
        raise TrainingUnavailable(f"versi model {version_id} tidak ada")
    for other in session.scalars(
        select(ModelVersion).where(
            ModelVersion.symbol == version.symbol,
            ModelVersion.horizon_days == version.horizon_days,
        )
    ):
        other.is_active = other.id == version.id
    session.flush()
    return version


def claim_next_job(session: Session) -> TrainingJob | None:
    """Take the oldest queued job. SKIP LOCKED keeps concurrent workers apart."""
    query = select(TrainingJob).where(TrainingJob.status == "queued").order_by(TrainingJob.id)
    if session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = session.scalars(query.limit(1)).first()
    if job is not None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
    return job


def run_queued_once() -> bool:
    """Claim and run one queued job. False when the queue was empty."""
    with db.session() as session:
        job = claim_next_job(session)
        job_id = job.id if job else None
    if job_id is None:
        return False
    run_job(job_id)
    return True


def start_background_worker() -> threading.Thread | None:
    """Run queued jobs in a daemon thread, for workstations and single instances."""
    if not config.training_inline():
        return None

    def loop() -> None:
        while True:
            try:
                if not run_queued_once():
                    return
            except Exception:  # one bad job must not strand the rest
                logger.exception("Training worker iteration failed")

    thread = threading.Thread(target=loop, name="idx-signal-training", daemon=True)
    thread.start()
    return thread


def run_worker_forever(poll_seconds: int | None = None) -> None:
    interval = poll_seconds if poll_seconds is not None else 15
    logger.info("Training worker started (poll=%ss)", interval)
    while True:
        try:
            if not run_queued_once():
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Training worker stopped by user")
            return
        except Exception:
            logger.exception("Training worker iteration failed")
            time.sleep(interval)
