"""Vercel cron jobs must land on the matching WIB schedule slot."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

from idx_signal import config, scheduler
from idx_signal.refresh import RefreshReport


def test_vercel_crons_map_to_the_configured_wib_slots():
    crons = json.loads(Path("vercel.json").read_text(encoding="utf-8"))["crons"]
    expected = (time(16, 5), time(18, 0))

    assert len(crons) == len(expected)
    for cron, slot_time in zip(crons, expected, strict=True):
        minute, hour, _, _, weekdays = cron["schedule"].split()
        assert weekdays == "1-5"
        now_utc = datetime(2026, 10, 14, int(hour), int(minute), tzinfo=timezone.utc)
        assert scheduler.due_slot(now_utc, None) == datetime.combine(
            date(2026, 10, 14), slot_time, tzinfo=config.WIB
        )


def test_scheduled_run_calls_the_shared_refresh_pipeline(monkeypatch):
    calls = []
    report = RefreshReport(
        trigger_type="scheduled",
        status="success",
        symbols=config.SUPPORTED_SYMBOLS,
        horizons=config.HORIZONS,
        predictions=[{}, {}],
        log_id=7,
    )

    def fake_refresh(symbols, horizons, kind):
        calls.append((symbols, horizons, kind))
        return report

    monkeypatch.setattr(scheduler, "refresh", fake_refresh)
    monkeypatch.setattr(scheduler, "last_success_utc", lambda: None)
    monkeypatch.setattr(config, "schedule_retry_attempts", lambda: 0)

    outcome = scheduler.run_scheduled(
        now_utc=datetime(2026, 10, 14, 10, 10, tzinfo=timezone.utc)
    )

    assert outcome.ran is True
    assert outcome.attempts == 1
    assert calls == [(config.SUPPORTED_SYMBOLS, config.HORIZONS, "scheduled")]
