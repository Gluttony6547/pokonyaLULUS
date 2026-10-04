from __future__ import annotations

import os
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from prog5 import cli, config, refresh as refresh_module, scheduler
from prog5.models import RefreshRun

from .conftest import requires_artifacts

WEEKDAYS = frozenset({0, 1, 2, 3, 4})
ALL_DAYS = frozenset(range(7))


def utc_naive(local: datetime) -> datetime:
    """Turn a local wall-clock datetime into the naive UTC form used in SQLite."""
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def local_at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, clock_time(hour, minute))


def synthetic_frame(rows: int = 260, last_close: float = 2500.0) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-10-02", periods=rows).date
    closes = [last_close - 0.5 * (rows - index) for index in range(rows)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [close - 2 for close in closes],
            "high": [close + 5 for close in closes],
            "low": [close - 5 for close in closes],
            "close": closes,
            "volume": [1_000_000] * rows,
        }
    )


def fake_report(run_id: int, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        status=status,
        predictions=[{"horizon_days": horizon} for horizon in config.HORIZONS],
        warnings=["synthetic warning"] if status != "completed" else [],
        to_text=lambda: f"fake run #{run_id} {status}",
    )


def test_due_slot_respects_time_and_weekday():
    times = (clock_time(17, 30),)
    monday = date(2026, 10, 5)
    before = utc_naive(local_at(monday, 16, 0))
    assert scheduler.due_slot(before, None, times, WEEKDAYS) is None

    after = utc_naive(local_at(monday, 18, 0))
    slot = scheduler.due_slot(after, None, times, WEEKDAYS)
    assert slot is not None
    assert (slot.date(), slot.strftime("%H:%M")) == (monday, "17:30")


def test_a_completed_run_satisfies_the_slot():
    times = (clock_time(17, 30),)
    monday = date(2026, 10, 5)
    after = utc_naive(local_at(monday, 18, 0))
    satisfied = utc_naive(local_at(monday, 17, 45))
    assert scheduler.due_slot(after, satisfied, times, WEEKDAYS) is None

    # A run from the morning does not satisfy the evening slot.
    earlier = utc_naive(local_at(monday, 9, 0))
    assert scheduler.due_slot(after, earlier, times, WEEKDAYS) is not None


def test_missed_slot_is_caught_up_and_weekend_needs_nothing_new():
    times = (clock_time(17, 30),)
    friday = date(2026, 10, 9)
    saturday = date(2026, 10, 10)
    saturday_noon = utc_naive(local_at(saturday, 12, 0))

    # Friday was missed: Saturday still sees Friday's slot and catches up.
    slot = scheduler.due_slot(saturday_noon, None, times, WEEKDAYS)
    assert slot is not None and slot.date() == friday

    # Once Friday's run happened, the weekend is quiet.
    friday_evening = utc_naive(local_at(friday, 18, 0))
    assert scheduler.due_slot(saturday_noon, friday_evening, times, WEEKDAYS) is None


def test_scheduled_run_fires_the_trigger(temp_db, monkeypatch):
    monkeypatch.setenv("PROG5_SCHEDULE_DAYS", "mon,tue,wed,thu,fri,sat,sun")
    monkeypatch.setenv(
        "PROG5_SCHEDULE_TIMES",
        (datetime.now() - timedelta(hours=2)).strftime("%H:%M"),
    )
    # If the fake ever fails, surface it immediately instead of sleeping.
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_DELAY_SECONDS", "0")
    calls: list[tuple] = []

    def fake_refresh(symbols, horizons=None, period=None, kind=None):
        calls.append((tuple(symbols), tuple(horizons)))
        return fake_report(101)

    monkeypatch.setattr(scheduler, "refresh", fake_refresh)

    outcome = scheduler.run_scheduled()

    assert outcome.ran is True
    assert outcome.exit_code() == 0
    assert len(calls) == 1
    assert calls[0][0] == config.SUPPORTED_SYMBOLS
    assert calls[0][1] == config.HORIZONS


def test_scheduled_run_does_nothing_when_not_due(temp_db, monkeypatch):
    monkeypatch.setenv("PROG5_SCHEDULE_DAYS", "mon,tue,wed,thu,fri,sat,sun")
    monkeypatch.setenv("PROG5_SCHEDULE_TIMES", "00:01")
    # A run that just finished satisfies every slot up to now, whenever the
    # test happens to run.
    just_finished = datetime.now(timezone.utc).replace(tzinfo=None)
    with temp_db.session() as session:
        session.add(
            RefreshRun(
                kind="scheduled",
                status="completed",
                requested_symbols="ADRO",
                horizons="1",
                started_at=just_finished,
                finished_at=just_finished,
            )
        )
    calls: list[tuple] = []
    monkeypatch.setattr(scheduler, "refresh", lambda *a, **k: calls.append((a, k)))

    outcome = scheduler.run_scheduled()

    assert outcome.ran is False
    assert outcome.reason == "not due"
    assert calls == []


def test_scheduled_run_retries_after_a_failed_run(temp_db, monkeypatch):
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_DELAY_SECONDS", "0")
    reports = [fake_report(201, status="failed"), fake_report(202)]
    monkeypatch.setattr(scheduler, "refresh", lambda *a, **k: reports.pop(0))

    outcome = scheduler.run_scheduled(force=True)

    assert outcome.ran is True
    assert outcome.attempts == 2
    assert outcome.report.run_id == 202


def test_retries_are_reported_when_every_attempt_fails(temp_db, monkeypatch):
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setattr(scheduler, "refresh", lambda *a, **k: fake_report(301, status="failed"))

    outcome = scheduler.run_scheduled(force=True)

    assert outcome.ran is False
    assert outcome.attempts == 2
    assert outcome.exit_code() == 1


def test_lock_blocks_a_second_refresh(temp_db):
    lock = Path(f"{config.db_path()}.lock")
    lock.write_text("held by another process")
    with pytest.raises(refresh_module.RefreshInProgress):
        refresh_module.refresh(["ADRO"])
    assert lock.exists()  # the blocked caller must not delete someone else's lock
    lock.unlink()


def test_scheduled_run_reports_locked_without_retrying(temp_db, monkeypatch):
    lock = Path(f"{config.db_path()}.lock")
    lock.write_text("held by another process")
    monkeypatch.setenv("PROG5_SCHEDULE_RETRY_ATTEMPTS", "3")

    outcome = scheduler.run_scheduled(force=True)

    assert outcome.ran is False
    assert outcome.reason.startswith("locked")
    assert outcome.exit_code() == 0
    lock.unlink()


def test_cli_schedule_once_exits_zero_when_not_due(temp_db, monkeypatch, capsys):
    monkeypatch.setenv("PROG5_SCHEDULE_DAYS", "mon,tue,wed,thu,fri,sat,sun")
    monkeypatch.setenv("PROG5_SCHEDULE_TIMES", "00:01")
    just_finished = datetime.now(timezone.utc).replace(tzinfo=None)
    with temp_db.session() as session:
        session.add(
            RefreshRun(
                kind="scheduled",
                status="completed",
                requested_symbols="ADRO",
                horizons="1",
                started_at=just_finished,
                finished_at=just_finished,
            )
        )
    assert cli.main(["schedule", "--once"]) == 0
    assert "not due" in capsys.readouterr().out


@requires_artifacts
def test_refresh_records_the_run_kind(temp_db, monkeypatch):
    frame = synthetic_frame()
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1]) * 1.5
    )

    report = refresh_module.refresh(["ADRO"], horizons=(1,), kind="scheduled")

    assert report.status == "completed"
    with temp_db.session() as session:
        run = session.query(RefreshRun).order_by(RefreshRun.id.desc()).first()
        assert run.kind == "scheduled"


@requires_artifacts
def test_stale_lock_is_broken_and_interrupted_run_is_reconciled(temp_db, monkeypatch):
    frame = synthetic_frame()
    monkeypatch.setattr(refresh_module, "fetch_daily_ohlcv", lambda symbol, period=None: frame.copy())
    monkeypatch.setattr(
        refresh_module, "predict_price", lambda symbol, horizon, closes: float(frame["close"].iloc[-1]) * 1.5
    )
    lock = Path(f"{config.db_path()}.lock")
    lock.write_text("crashed process")
    old = time.time() - 100_000
    os.utime(lock, (old, old))
    with temp_db.session() as session:
        session.add(
            RefreshRun(
                kind="scheduled",
                status="running",
                requested_symbols="ADRO",
                horizons="1",
                started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=8),
            )
        )

    report = refresh_module.refresh(["ADRO"], horizons=(1,))

    assert report.status == "completed"
    assert not lock.exists()
    with temp_db.session() as session:
        rows = session.query(RefreshRun).order_by(RefreshRun.id).all()
        interrupted = rows[0]
        assert interrupted.status == "failed"
        assert "interrupted" in (interrupted.summary or "")
        assert rows[1].status == "completed"
