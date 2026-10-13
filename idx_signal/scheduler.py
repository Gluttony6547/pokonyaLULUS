"""Unattended refresh, on top of the one refresh pipeline.

The scheduler adds no second data path: it calls `refresh.refresh` exactly like
the manual update does, and only decides *whether* a run is due. Slots are
wall-clock WIB on the configured weekdays, so a UTC host cannot drift the
schedule, and a missed slot is picked up on the next tick within a five-day
window so a long weekend does not leave a permanent gap.
"""

from __future__ import annotations

import logging
import time as time_module
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import config, db
from .refresh import RefreshInProgress, RefreshReport, refresh
from .storage import clear_stale_training_jobs, last_successful_update

logger = logging.getLogger(__name__)

# A four-day weekend plus a provider outage is the worst realistic gap; beyond
# that the dashboard shows stale data rather than silently backfilling.
CATCH_UP_DAYS = 5


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
        return 1 if not self.ran and self.reason.startswith("refresh failed") else 0


def due_slot(
    now_utc: datetime,
    last_success_utc: datetime | None,
    times: tuple | None = None,
    days: frozenset[int] | None = None,
) -> datetime | None:
    """The newest scheduled slot in WIB that still needs a run, if any."""
    schedule_times = times if times is not None else config.schedule_times()
    schedule_days = days if days is not None else config.schedule_days()
    local_now = now_utc.astimezone(config.WIB)
    candidates: list[tuple[datetime, datetime]] = []
    for offset in range(0, -CATCH_UP_DAYS - 1, -1):
        day: date = (local_now + timedelta(days=offset)).date()
        if day.weekday() not in schedule_days:
            continue
        for moment in schedule_times:
            slot_local = datetime.combine(day, moment, tzinfo=config.WIB)
            if slot_local <= local_now:
                candidates.append((slot_local.astimezone(timezone.utc), slot_local))
    if not candidates:
        return None
    slot_utc, slot_local = max(candidates)
    if last_success_utc is not None and last_success_utc >= slot_utc:
        return None
    return slot_local


def last_success_utc() -> datetime | None:
    with db.session() as session:
        entry = last_successful_update(session)
    if entry is None or entry.run_at is None:
        return None
    moment = entry.run_at
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _execute(symbols: tuple[str, ...], attempts: int, delay_seconds: int) -> ScheduledOutcome:
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            report = refresh(symbols, horizons=config.HORIZONS, kind="scheduled")
        except RefreshInProgress as error:
            return ScheduledOutcome(False, f"locked: {error}", attempts=attempt - 1)
        except Exception as error:  # one bad tick never kills the loop
            last_error = f"{type(error).__name__}: {error}"
            logger.exception("Scheduled refresh attempt %s/%s crashed", attempt, attempts)
        else:
            if report.status in {"success", "partial"}:
                return ScheduledOutcome(
                    True,
                    f"update #{report.log_id} {report.status} "
                    f"({len(report.predictions)} predictions)",
                    attempts=attempt,
                    report=report,
                )
            if report.status == "skipped":
                return ScheduledOutcome(False, report.message or "not a trading session", attempts=attempt)
            last_error = f"update #{report.log_id} ended {report.status}"
        if attempt < attempts:
            time_module.sleep(delay_seconds)
    return ScheduledOutcome(False, f"refresh failed after {attempts} attempt(s): {last_error}", attempts)


def run_scheduled(now_utc: datetime | None = None, force: bool = False) -> ScheduledOutcome:
    """Run one due check and, when due, one refresh with the retry policy."""
    now = now_utc or datetime.now(timezone.utc)
    db.init_db()
    with db.session() as session:
        repaired = clear_stale_training_jobs(session, config.stale_run_seconds())
    for job_id in repaired:
        logger.warning("Marked interrupted training job #%s as failed", job_id)

    if not force:
        slot = due_slot(now, last_success_utc())
        if slot is None:
            return ScheduledOutcome(False, "not due")
        logger.info("Scheduled slot %s WIB is due", slot.strftime("%Y-%m-%d %H:%M"))

    attempts = 1 + config.schedule_retry_attempts()
    return _execute(config.schedule_symbols(), attempts, config.schedule_retry_delay_seconds())


def run_forever(poll_seconds: int | None = None) -> None:
    poll = poll_seconds if poll_seconds is not None else config.schedule_poll_seconds()
    logger.info(
        "Scheduler started: times=[%s] WIB days=%s symbols=%s poll=%ss",
        ", ".join(moment.strftime("%H:%M") for moment in config.schedule_times()),
        ",".join(sorted({str(day) for day in config.schedule_days()})),
        ",".join(config.schedule_symbols()),
        poll,
    )
    while True:
        try:
            outcome = run_scheduled()
            if outcome.ran or not outcome.reason.startswith("not due"):
                logger.info("%s", outcome.to_text())
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            return
        except Exception:
            logger.exception("Scheduler tick failed; continuing")
        time_module.sleep(poll)
