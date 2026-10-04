"""On-demand EOD refresh: the only writer in the service."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy import select

from . import config, db
from .indicators import compute_indicators
from .market_data import (
    SOURCE,
    MarketDataUnavailable,
    fetch_daily_ohlcv,
    validation_issues,
    window_has_corporate_action,
)
from .model_registry import (
    ModelUnavailable,
    input_scaler,
    model_identity,
    predict_price,
    target_scaler,
)
from .models import RefreshRun
from .signals import classify_return, is_out_of_distribution, out_of_distribution_z, signal_label
from .storage import ensure_stock, store_indicators, store_prices, store_prediction

logger = logging.getLogger(__name__)

STALE_AFTER_DAYS = 7


class RefreshInProgress(RuntimeError):
    """Another process already holds the single-writer refresh lock."""


def _lock_path() -> Path:
    return Path(f"{config.db_path()}.lock")


@contextmanager
def refresh_lock(stale_seconds: int | None = None) -> Iterator[None]:
    """Single-writer guard shared by the CLI and the scheduler.

    The lock is a file next to the database created with O_CREAT|O_EXCL, so two
    processes on this host cannot refresh at the same time. A lock older than
    the stale threshold is treated as abandoned and replaced once; anything
    newer means a real run is still writing, and the caller gets
    RefreshInProgress rather than a second writer.
    """
    path = _lock_path()
    stale = stale_seconds if stale_seconds is not None else config.schedule_stale_lock_seconds()
    for attempt in (1, 2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(
                handle,
                f"pid={os.getpid()} started={datetime.now(timezone.utc).isoformat()}\n".encode(),
            )
            os.close(handle)
            break
        except FileExistsError:
            age = time.time() - path.stat().st_mtime
            if attempt == 1 and age > stale:
                logger.warning("Breaking stale refresh lock %s (age %.0fs)", path, age)
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise RefreshInProgress(f"Another refresh is running (lock {path}).") from None
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def reconcile_interrupted_runs(stale_after_seconds: int | None = None) -> list[int]:
    """Mark runs left in 'running' by a dead process as failed.

    Returns the affected run ids so callers can log the repair. Only rows older
    than the stale threshold are touched, so a genuinely running refresh is
    never mislabelled.
    """
    stale = (
        stale_after_seconds
        if stale_after_seconds is not None
        else config.schedule_stale_run_seconds()
    )
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=stale)
    repaired: list[int] = []
    with db.session() as session:
        rows = session.scalars(
            select(RefreshRun).where(
                RefreshRun.status == "running", RefreshRun.started_at < cutoff
            )
        ).all()
        for run in rows:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            note = f"interrupted: still running after {stale}s, marked failed"
            run.summary = f"{run.summary} | {note}" if run.summary else note
            repaired.append(run.id)
    return repaired


@dataclass
class RefreshReport:
    run_id: int | None
    status: str
    symbols: tuple[str, ...]
    horizons: tuple[int, ...]
    predictions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prices_stored: int = 0
    indicators_stored: int = 0

    def to_text(self) -> str:
        lines = [
            f"refresh run #{self.run_id} status={self.status}",
            f"symbols={','.join(self.symbols)} horizons={','.join(map(str, self.horizons))}",
            f"prices stored={self.prices_stored} indicator rows stored={self.indicators_stored} "
            f"predictions={len(self.predictions)}",
        ]
        if self.predictions:
            header = (
                f"{'symbol':7s} {'T':>3s} {'as of':10s} {'close':>9s} {'predicted':>10s} "
                f"{'ret%':>7s} {'thr%':>5s} {'signal':6s} {'z':>6s} {'ood':3s} model"
            )
            lines.append(header)
            for row in self.predictions:
                lines.append(
                    f"{row['symbol']:7s} {row['horizon_days']:3d} {str(row['data_as_of']):10s} "
                    f"{row['last_close']:9.1f} {row['predicted_price']:10.1f} "
                    f"{row['return_pct']:7.2f} {row['threshold_pct']:5.1f} "
                    f"{row['signal_label']:6s} {row['ood_z']:6.2f} "
                    f"{'yes' if row['ood_flag'] else 'no':3s} {row['model_file']}"
                )
        for warning in self.warnings:
            lines.append(f"warning: {warning}")
        return "\n".join(lines)


def refresh(
    symbols: Iterable[str],
    horizons: Sequence[int] = config.HORIZONS,
    period: str = config.DEFAULT_HISTORY_PERIOD,
    kind: str = "on_demand",
) -> RefreshReport:
    symbol_list = tuple(symbol.strip().upper() for symbol in symbols)
    horizon_list = tuple(int(horizon) for horizon in horizons)
    invalid = [horizon for horizon in horizon_list if horizon not in config.HORIZONS]
    if invalid:
        raise ValueError(f"Unsupported horizons: {invalid}")
    unsupported = [symbol for symbol in symbol_list if symbol not in config.SUPPORTED_SYMBOLS]
    if unsupported:
        raise ValueError(f"Symbols without research artifacts: {unsupported}")

    with refresh_lock():
        db.init_db()
        for run_id in reconcile_interrupted_runs():
            logger.warning("Marked interrupted refresh run #%s as failed", run_id)
        return _refresh_locked(symbol_list, horizon_list, period, kind)


def _refresh_locked(
    symbol_list: tuple[str, ...], horizon_list: tuple[int, ...], period: str, kind: str
) -> RefreshReport:
    report = RefreshReport(run_id=None, status="running", symbols=symbol_list, horizons=horizon_list)

    with db.session() as session:
        run = RefreshRun(
            kind=kind,
            status="running",
            requested_symbols=",".join(symbol_list),
            horizons=",".join(map(str, horizon_list)),
        )
        session.add(run)
        session.flush()
        report.run_id = run.id

        for symbol in symbol_list:
            ensure_stock(session, symbol)
            try:
                frame = fetch_daily_ohlcv(symbol, period=period)
            except MarketDataUnavailable as error:
                message = f"{symbol}: {error}"
                logger.error(message)
                report.warnings.append(message)
                continue

            for issue in validation_issues(frame):
                report.warnings.append(f"{symbol}: {issue}")

            report.prices_stored += store_prices(session, symbol, frame, SOURCE)
            report.indicators_stored += store_indicators(session, symbol, compute_indicators(frame))

            last = frame.iloc[-1]
            data_as_of = last["date"]
            age_days = (datetime.now(timezone.utc).date() - data_as_of).days
            if age_days > STALE_AFTER_DAYS:
                report.warnings.append(
                    f"{symbol}: latest close is {data_as_of} ({age_days} days old)"
                )

            for horizon in horizon_list:
                if window_has_corporate_action(frame, horizon):
                    message = (
                        f"{symbol} T{horizon}: corporate action inside the input window, "
                        "prediction skipped"
                    )
                    logger.warning(message)
                    report.warnings.append(message)
                    continue
                try:
                    predicted = predict_price(symbol, horizon, frame["close"])
                except ModelUnavailable as error:
                    message = f"{symbol} T{horizon}: {error}"
                    logger.error(message)
                    report.warnings.append(message)
                    continue

                identity = model_identity(symbol, horizon)
                scaler_in = input_scaler(symbol)
                scaler_out = target_scaler(symbol, horizon)
                current = float(last["close"])
                signal, change_pct = classify_return(predicted, current, horizon)
                z = out_of_distribution_z(current, float(scaler_in.mean_[0]), float(scaler_in.scale_[0]))
                ood = is_out_of_distribution(z)
                row_warnings: list[str] = []
                if ood:
                    row_warnings.append(
                        f"close is {z:.2f} sigma from the training mean; prediction unreliable"
                    )

                record = {
                    "run_id": run.id,
                    "symbol": symbol,
                    "horizon_days": horizon,
                    "data_as_of": data_as_of,
                    "window_start_date": frame["date"].iloc[-horizon],
                    "window_size": horizon,
                    "last_close": current,
                    "predicted_price": float(predicted),
                    "return_pct": float(change_pct),
                    "threshold_pct": config.RETURN_THRESHOLDS[horizon] * 100.0,
                    "signal": signal,
                    "signal_label": signal_label(signal),
                    "ood_z": float(z),
                    "ood_flag": bool(ood),
                    "model_file": str(identity["file"]),
                    "model_sha256": str(identity["sha256"]),
                    "input_mean": float(scaler_in.mean_[0]),
                    "input_scale": float(scaler_in.scale_[0]),
                    "target_mean": float(scaler_out.mean_[0]),
                    "target_scale": float(scaler_out.scale_[0]),
                    "warnings": "; ".join(row_warnings) if row_warnings else None,
                }
                store_prediction(session, record)
                report.predictions.append(record)

        report.status = "completed" if report.predictions else "failed"
        run.status = report.status
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.summary = (
            f"prices={report.prices_stored} indicators={report.indicators_stored} "
            f"predictions={len(report.predictions)} warnings={len(report.warnings)}"
        )
    return report
