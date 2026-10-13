"""The only writer in the service: fetch EOD data and store predictions.

Everything the dashboard shows comes from here. A run is idempotent, so the
second scheduled slot of a trading day overwrites the same rows with the
provider's settled values, and a prediction is keyed on the session it was made
from rather than on when it was made.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import config, db, metrics as metrics_module
from .market_data import (
    MarketDataUnavailable,
    drop_forming_bar,
    fetch_daily_ohlcv,
    validation_issues,
    window_has_corporate_action,
)
from .model_registry import (
    ModelUnavailable,
    Scalers,
    predict_price,
    reference_artifact,
    scalers_from_research,
)
from .models import ModelVersion
from .signals import classify_return, is_out_of_distribution, out_of_distribution_z
from .storage import (
    active_model_version,
    ensure_reference_data,
    log_update,
    register_model_version,
    store_prediction,
    store_prices,
)
from .trading_calendar import crosses_unknown_year, is_trading_day, load_holidays, target_date

logger = logging.getLogger(__name__)

# Postgres advisory lock key: two containers must not both be writing.
REFRESH_LOCK_KEY = 20261013


class RefreshInProgress(RuntimeError):
    """Another refresh already holds the writer lock."""


@contextmanager
def refresh_guard(session: Session) -> Iterator[None]:
    """Single-writer guard, per database dialect.

    Postgres uses a transaction-scoped advisory lock rather than a session one,
    because a transaction pooler can hand a connection to someone else between
    statements and a session lock would then outlive its owner. A whole refresh
    runs inside one transaction, so the lock covers exactly the run and is
    released by the database even if the process dies. SQLite is single-host,
    so a lock file beside it is enough.
    """
    if session.get_bind().dialect.name == "postgresql":
        acquired = session.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": REFRESH_LOCK_KEY}
        ).scalar()
        if not acquired:
            raise RefreshInProgress("Pembaruan data lain sedang berjalan.")
        yield
        return

    from pathlib import Path

    lock_path = Path(f"{config.sqlite_path()}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock_path.open("x")
    except FileExistsError as error:
        raise RefreshInProgress(f"Pembaruan data lain sedang berjalan ({lock_path}).") from error
    try:
        handle.write(f"pid={os.getpid()} at={datetime.now(timezone.utc).isoformat()}\n")
        handle.close()
        yield
    finally:
        lock_path.unlink(missing_ok=True)


@dataclass
class RefreshReport:
    trigger_type: str
    status: str
    symbols: tuple[str, ...]
    horizons: tuple[int, ...]
    rows_inserted: int = 0
    predictions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_id: int | None = None
    message: str | None = None

    def to_text(self) -> str:
        lines = [
            f"update log #{self.log_id} status={self.status} trigger={self.trigger_type}",
            f"symbols={','.join(self.symbols)} horizons={','.join(map(str, self.horizons))}",
            f"price rows written={self.rows_inserted} predictions={len(self.predictions)}",
        ]
        if self.message:
            lines.append(f"message: {self.message}")
        if self.predictions:
            lines.append(
                f"{'symbol':7s} {'T':>3s} {'as of':10s} {'target':10s} {'close':>9s} "
                f"{'predicted':>10s} {'ret%':>7s} {'thr%':>5s} {'signal':5s} {'z':>6s} ood"
            )
            for row in self.predictions:
                lines.append(
                    f"{row['symbol']:7s} {row['horizon_days']:3d} {str(row['data_as_of']):10s} "
                    f"{str(row['target_date']):10s} {row['last_close']:9.1f} "
                    f"{row['predicted_price']:10.1f} {row['return_pct']:7.2f} "
                    f"{row['threshold_pct']:5.1f} {row['signal']:5s} {row['ood_z']:6.2f} "
                    f"{'yes' if row['ood_flag'] else 'no'}"
                )
        for warning in self.warnings:
            lines.append(f"warning: {warning}")
        return "\n".join(lines)


def _research_data_until(symbol: str) -> date:
    """Last session the reference training set covers."""
    frame = pd.read_csv(config.labelled_file(symbol), usecols=["datetime"])
    return pd.to_datetime(frame["datetime"].iloc[-1]).date()


def ensure_model_versions(
    session: Session, symbols: Sequence[str], horizons: Sequence[int], refresh_metrics: bool = False
) -> dict[tuple[str, int], ModelVersion]:
    """Register any saved artifact that has no active version yet."""
    versions: dict[tuple[str, int], ModelVersion] = {}
    for symbol in symbols:
        for horizon in horizons:
            existing = active_model_version(session, symbol, horizon)
            identity_row = reference_artifact(symbol, horizon)
            if existing is not None and existing.artifact_sha256 == identity_row["sha256"]:
                if refresh_metrics and not existing.metrics:
                    try:
                        existing.metrics = metrics_module.evaluate(symbol, horizon)
                    except metrics_module.MetricsUnavailable as error:
                        logger.warning("Metrics unavailable for %s T%s: %s", symbol, horizon, error)
                versions[(symbol, horizon)] = existing
                continue

            try:
                scalers = scalers_from_research(symbol, horizon)
            except ModelUnavailable as error:
                raise ModelUnavailable(
                    f"{symbol} T{horizon} belum bisa didaftarkan: {error}. Deret riset "
                    "(Data Fusion of Historical and Sentiment dan Labelled Stock Data) harus "
                    "ada, atau arahkan IDX_RESEARCH_DATA_DIR ke tempatnya."
                ) from error

            try:
                scores = metrics_module.evaluate(symbol, horizon)
            except metrics_module.MetricsUnavailable as error:
                logger.warning("Metrics unavailable for %s T%s: %s", symbol, horizon, error)
                scores = {}

            versions[(symbol, horizon)] = register_model_version(
                session,
                symbol=symbol,
                horizon_days=horizon,
                artifact_path=identity_row["path"],
                artifact_sha256=identity_row["sha256"],
                data_until=_research_data_until(symbol),
                metrics=scores,
                config_payload={
                    "architecture": "3 x LSTM(96) + Dense(1)",
                    "input": "close window, H sessions",
                    "source": "reference artifact",
                    **scalers.as_config(),
                },
            )
    session.flush()
    return versions


def refresh(
    symbols: Sequence[str] | None = None,
    horizons: Sequence[int] = config.HORIZONS,
    kind: str = "manual",
    period: str = config.DEFAULT_HISTORY_PERIOD,
    today: date | None = None,
) -> RefreshReport:
    """Fetch EOD data for the requested tickers and store their signals.

    `today` exists so the exchange-calendar branch can be exercised for any
    date without waiting for one.
    """
    symbol_list = tuple(symbols) if symbols else config.SUPPORTED_SYMBOLS
    horizon_list = tuple(int(horizon) for horizon in horizons)
    invalid = [horizon for horizon in horizon_list if horizon not in config.HORIZONS]
    if invalid:
        raise ValueError(f"Unsupported horizons: {invalid}")
    unsupported = [symbol for symbol in symbol_list if symbol not in config.SUPPORTED_SYMBOLS]
    if unsupported:
        raise ValueError(f"Symbols without reference artifacts: {unsupported}")

    report = RefreshReport(
        trigger_type="scheduled" if kind == "scheduled" else "manual",
        status="failed",
        symbols=symbol_list,
        horizons=horizon_list,
    )

    db.init_db()
    with db.session() as session:
        ensure_reference_data(session)

        holidays, known_years = load_holidays(session)
        session_date = today or datetime.now(config.WIB).date()
        if kind == "scheduled" and not is_trading_day(session_date, holidays):
            report.status = "skipped"
            report.message = f"{session_date} bukan hari bursa IDX, pembaruan dilewati."
            report.log_id = log_update(
                session, report.trigger_type, "skipped", 0, report.message
            ).id
            return report

        with refresh_guard(session):
            versions = ensure_model_versions(session, symbol_list, horizon_list)
            attempted = 0
            failed = 0

            for symbol in symbol_list:
                attempted += 1
                try:
                    frame = fetch_daily_ohlcv(symbol, period=period)
                except MarketDataUnavailable as error:
                    failed += 1
                    report.warnings.append(f"{symbol}: {error}")
                    continue

                frame, forming_notes = drop_forming_bar(frame, datetime.now(timezone.utc))
                report.warnings.extend(f"{symbol}: {note}" for note in forming_notes)
                if frame.empty:
                    failed += 1
                    report.warnings.append(
                        f"{symbol}: tidak ada sesi yang sudah selesai pada data penyedia"
                    )
                    continue
                report.warnings.extend(f"{symbol}: {issue}" for issue in validation_issues(frame))

                try:
                    # A savepoint keeps one ticker's bad row from discarding the run.
                    with session.begin_nested():
                        report.rows_inserted += store_prices(session, symbol, frame)
                except Exception as error:
                    failed += 1
                    report.warnings.append(f"{symbol}: penulisan harga gagal ({error})")
                    continue

                last = frame.iloc[-1]
                data_as_of = last["date"]
                closes = frame["close"]

                for horizon in horizon_list:
                    version = versions[(symbol, horizon)]
                    if window_has_corporate_action(frame, horizon):
                        report.warnings.append(
                            f"{symbol} T{horizon}: ada aksi korporasi di dalam jendela masukan, "
                            "prediksi dilewati"
                        )
                        continue
                    try:
                        scalers = Scalers.from_config(version.config)
                        predicted = predict_price(
                            version.artifact_path, horizon, closes, scalers
                        )
                    except ModelUnavailable as error:
                        failed += 1
                        report.warnings.append(f"{symbol} T{horizon}: {error}")
                        continue

                    current = float(last["close"])
                    signal, change_pct = classify_return(predicted, current, horizon)
                    z = out_of_distribution_z(current, scalers.input_mean, scalers.input_scale)
                    ood = is_out_of_distribution(z)
                    projected = target_date(data_as_of, horizon, holidays)
                    row_warnings: list[str] = []
                    if ood:
                        row_warnings.append(
                            f"harga acuan {z:.2f} simpangan baku dari rata-rata data latih, "
                            "di luar sebaran yang dikenal model"
                        )
                    if crosses_unknown_year(data_as_of, horizon, known_years):
                        row_warnings.append(
                            "tanggal target masih perkiraan, kalender libur bursa belum "
                            "mencakup tahun tersebut"
                        )

                    record = {
                        "symbol": symbol,
                        "horizon_days": horizon,
                        "model_version_id": version.id,
                        "data_as_of": data_as_of,
                        "target_date": projected,
                        "signal": signal,
                        "predicted_price": float(predicted),
                        "last_close": current,
                        "return_pct": float(change_pct),
                        "threshold_pct": config.RETURN_THRESHOLDS[horizon] * 100.0,
                        "ood_z": float(z),
                        "ood_flag": bool(ood),
                        "warnings": "; ".join(row_warnings) or None,
                    }
                    try:
                        with session.begin_nested():
                            store_prediction(session, record)
                    except Exception as error:
                        failed += 1
                        report.warnings.append(
                            f"{symbol} T{horizon}: penulisan prediksi gagal ({error})"
                        )
                        continue
                    report.predictions.append(record)

            if not report.predictions:
                report.status = "failed"
            elif failed:
                report.status = "partial"
            else:
                report.status = "success"
            report.message = (
                f"{len(report.predictions)} sinyal dari {attempted} emiten, "
                f"{failed} kegagalan emiten/horizon"
            )
            report.log_id = log_update(
                session,
                report.trigger_type,
                report.status,
                report.rows_inserted,
                report.message + (f" | {len(report.warnings)} peringatan" if report.warnings else ""),
            ).id
    return report


def active_versions(session: Session, symbol: str) -> list[ModelVersion]:
    return list(
        session.scalars(
            select(ModelVersion)
            .where(ModelVersion.symbol == symbol, ModelVersion.is_active.is_(True))
            .order_by(ModelVersion.horizon_days)
        )
    )
