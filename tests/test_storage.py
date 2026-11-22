"""Writes have to be safe to repeat: a second run corrects, it never duplicates."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from idx_signal import db
from idx_signal.models import DailyPrice, ModelArtifact, ModelVersion, Prediction
from idx_signal.storage import (
    active_model_version,
    log_update,
    nth_price_date,
    price_date_range,
    price_frame_until,
    prune_model_versions,
    register_model_version,
    store_prices,
)


def count(model) -> int:
    with db.session() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_store_prices_inserts_then_updates_in_place(prices):
    with db.session() as session:
        assert store_prices(session, "ADRO", prices) == len(prices)
    assert count(DailyPrice) == len(prices)

    corrected = prices.copy()
    corrected.loc[corrected.index[-1], "close"] = 9999.0
    with db.session() as session:
        store_prices(session, "ADRO", corrected)
    assert count(DailyPrice) == len(prices)
    with db.session() as session:
        last = session.scalar(
            select(DailyPrice.close)
            .where(DailyPrice.symbol == "ADRO")
            .order_by(DailyPrice.trade_date.desc())
            .limit(1)
        )
    assert float(last) == 9999.0


def test_price_queries_stop_at_the_requested_date(prices):
    with db.session() as session:
        store_prices(session, "ADRO", prices)
    cutoff = prices.iloc[100]["date"]

    with db.session() as session:
        frame = price_frame_until(session, "ADRO", cutoff, limit=50)
        span = price_date_range(session, "ADRO")
        hundredth = nth_price_date(session, "ADRO", 101)

    assert len(frame) == 50
    assert frame.iloc[-1]["date"] == cutoff
    assert list(frame["date"]) == sorted(frame["date"])
    assert span == (prices.iloc[0]["date"], prices.iloc[-1]["date"])
    assert hundredth == cutoff


def test_registering_the_same_artifact_twice_keeps_one_version():
    payload = dict(
        symbol="ADRO",
        horizon_days=1,
        artifact_path="/tmp/LSTM_ADRO_Target_1.h5",
        artifact_sha256="a" * 64,
        data_until=date(2023, 12, 5),
        metrics={"accuracy": 0.5},
        config_payload={"input_mean": 1.0},
    )
    with db.session() as session:
        first = register_model_version(session, **payload)
        first_id = first.id
    with db.session() as session:
        second = register_model_version(session, **{**payload, "metrics": {"accuracy": 0.6}})
    assert second.id == first_id
    assert count(ModelVersion) == 1
    with db.session() as session:
        version = active_model_version(session, "ADRO", 1)
    assert version.metrics["accuracy"] == 0.6


def test_prune_keeps_the_active_version_and_one_reference():
    with db.session() as session:
        versions = [
            register_model_version(
                session,
                symbol="ADRO",
                horizon_days=1,
                artifact_path=f"ENSEMBLE_ADRO_Target_1_{index}.joblib",
                artifact_sha256=f"{index:064d}",
                data_until=date(2026, 11, 20),
                metrics={},
                config_payload={},
                artifact_bytes=b"model",
            )
            for index in range(1, 5)
        ]
        # The newest version serves; the older ones are history.
        for version in versions[:-1]:
            version.is_active = False
        session.add(
            Prediction(
                symbol="ADRO",
                horizon_days=1,
                model_version_id=versions[0].id,
                data_as_of=date(2026, 11, 18),
                signal="HOLD",
                last_close=2000.0,
                return_pct=0.4,
                threshold_pct=1.5,
            )
        )

    with db.session() as session:
        report = prune_model_versions(session, keep_references=1)

    assert report.removed == [versions[1].id]
    assert report.kept_for_history == [versions[0].id]
    assert report.removed_artifacts == [versions[1].id]
    assert report.artifact_bytes == len(b"model")

    with db.session() as session:
        remaining = set(session.scalars(select(ModelVersion.id)))
        artifacts = set(session.scalars(select(ModelArtifact.model_version_id)))
        recorded = session.scalars(select(Prediction.model_version_id)).all()
    assert remaining == {versions[0].id, versions[2].id, versions[3].id}
    assert artifacts == {versions[2].id, versions[3].id}
    assert recorded == [versions[0].id]


def test_update_log_records_the_run():
    with db.session() as session:
        entry = log_update(session, "manual", "partial", 42, "2 kegagalan")
    assert entry.id is not None
    assert entry.status == "partial"
    assert entry.rows_inserted == 42
