"""Unattended refresh on top of the one existing refresh pipeline.

The scheduler adds no data path: it calls `prog5.refresh.refresh` exactly like
the CLI refresh command does. On top of that it provides

- a due-time check against the configured local times and weekdays,
- a retry policy for failed runs,
- and a loop that survives individual failures (a broken tick or a network
  outage is logged and the next tick continues).

Overlap and interruption safety live in `prog5.refresh`: the single-writer
lock fails a second refresh with `RefreshInProgress`, stale locks are replaced,
and stale `running` run rows are marked failed by `reconcile_interrupted_runs`.
"""

from __future__ import annotations

import logging
import time as time_module
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from . import config, db
from .models import RefreshRun
from .refresh import RefreshInProgress, RefreshReport, reconcile_interrupted_runs, refresh

logger = logging.getLogger(__name__)


@dataclass
class ScheduledOutcome:
    ran: bool
    reason: str
    attempts: int = 0
    report: RefreshReport | None = field(default=None, repr=False)

    def to_text(self) -> str:
        lines = [f"scheduled refresh: ran={self.ran} attempts={self.attempts} reason={self.reason}"]
        if self.report is not None:
            lines.append(self.report.to_text())
        return "\n".join(lines)

    def exit_code(self) -> int:
        """0 for not-due, locked, or completed; 1 when a run failed after retries."""
        if not self.ran and self.reason.startswith("refresh failed"):
            return 1
        return 0


def _slots_for_day(day: date, times: tuple[time, ...], days: frozenset[int]) -> list[datetime]:
    if day.weekday() not in days:
        return []
    return [datetime.combine(day, moment) for moment in times]


def due_slot(
    now_utc: datetime,
    last_finished_utc: datetime | None,
    times: tuple[time, ...] | None = None,
    days: frozenset[int] | None = None,
) -> datetime | None:
    """Return the newest scheduled slot (local naive) that still needs a run.

    `now_utc` and `last_finished_utc` are naive UTC, matching the timestamps
    stored in SQLite. Slots are local wall-clock times from config. Yesterday is
    included so a machine that was off through one evening still catches up;
    once a successful run is newer than a slot, that slot is satisfied.
    """
    schedule_times = times if times is not None else config.schedule_times()
    schedule_days = days if days is not None else config.schedule_days()
    local_now = now_utc.replace(tzinfo=timezone.utc).astimezone()
    candidates: list[tuple[datetime, datetime]] = []
    for offset in (0, -1):
        day = (local_now + timedelta(days=offset)).date()
        for slot_local in _slots_for_day(day, schedule_times, schedule_days):
            slot_utc = slot_local.astimezone(timezone.utc).replace(tzinfo=None)
            if slot_utc <= now_utc:
                candidates.append((slot_utc, slot_local))
    if not candidates:
        return None
    slot_utc, slot_local = max(candidates)
    if last_finished_utc is not None and last_finished_utc >= slot_utc:
        return None
    return slot_local


def last_successful_finished() -> datetime | None:
    """Finished timestamp (naive UTC) of the newest completed run, if any."""
    with db.session() as session:
        row = session.scalars(
            select(RefreshRun)
            .where(RefreshRun.status == "completed", RefreshRun.finished_at.is_not(None))
            .order_by(RefreshRun.finished_at.desc())
            .limit(1)
        ).first()
    return row.finished_at if row else None


def _execute(symbols: tuple[str, ...], attempts: int, delay_seconds: int) -> ScheduledOutcome:
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            report = refresh(symbols, horizons=config.HORIZONS, kind="scheduled")
        except RefreshInProgress as error:
            return ScheduledOutcome(False, f"locked: {error}", attempts=attempt - 1)
        except Exception as error:  # a bad tick never kills the loop
            last_error = f"{type(error).__name__}: {error}"
            logger.exception("Scheduled refresh attempt %s/%s crashed", attempt, attempts)
        else:
            if report.status == "completed":
                return ScheduledOutcome(
                    True,
                    f"refresh run #{report.run_id} completed "
                    f"({len(report.predictions)} predictions)",
                    attempts=attempt,
                    report=report,
                )
            detail = "; ".join(report.warnings) or "no details"
            last_error = f"run #{report.run_id} ended {report.status}: {detail}"
            logger.warning("Scheduled refresh attempt %s/%s did not complete: %s", attempt, attempts, last_error)
        if attempt < attempts:
            logger.info("Retrying scheduled refresh in %ss", delay_seconds)
            time_module.sleep(delay_seconds)
    return ScheduledOutcome(False, f"refresh failed after {attempts} attempt(s): {last_error}", attempts=attempts)


def run_scheduled(now_utc: datetime | None = None, force: bool = False) -> ScheduledOutcome:
    """Run one due-check and, when due, one refresh with the retry policy.

    `force=True` skips the due check and is meant for manual repair, not for the
    loop. Interrupted runs are reconciled on every call so a crashed process is
    reflected in the UI even when nothing is due.
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc).replace(tzinfo=None)
    # Create or migrate the tables before the first query: a fresh or pre-rename
    # database would otherwise fail the due check and never schedule a run.
    db.init_db()
    for run_id in reconcile_interrupted_runs():
        logger.warning("Marked interrupted refresh run #%s as failed", run_id)
    if not force:
        slot = due_slot(now, last_successful_finished())
        if slot is None:
            return ScheduledOutcome(False, "not due")
        logger.info("Scheduled slot %s is due", slot.strftime("%Y-%m-%d %H:%M"))
    attempts = 1 + config.schedule_retry_attempts()
    return _execute(config.schedule_symbols(), attempts, config.schedule_retry_delay_seconds())


def run_forever(poll_seconds: int | None = None) -> None:
    """Poll the clock and run the refresh whenever a slot is due."""
    poll = poll_seconds if poll_seconds is not None else config.schedule_poll_seconds()
    schedule_times = ", ".join(moment.strftime("%H:%M") for moment in config.schedule_times())
    logger.info(
        "Scheduler started: times=[%s] symbols=%s attempts=%s poll=%ss",
        schedule_times,
        ",".join(config.schedule_symbols()),
        1 + config.schedule_retry_attempts(),
        poll,
    )
    try:
        while True:
            try:
                outcome = run_scheduled()
                if outcome.ran or not outcome.reason.startswith("not due"):
                    logger.info("%s", outcome.to_text())
            except Exception:  # never let one tick stop the loop
                logger.exception("Scheduler tick failed; continuing")
            time_module.sleep(poll)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
