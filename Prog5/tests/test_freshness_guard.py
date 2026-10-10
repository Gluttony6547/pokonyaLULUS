from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_site_freshness.py"

sys.path.insert(0, str(SCRIPT.parent))

import check_site_freshness as guard  # noqa: E402


def test_every_ticker_missing_from_yahoo_is_not_fresh(capfd):
    stored = {symbol: date(2026, 10, 8) for symbol in ("ADRO", "TLKM")}
    latest: dict[str, date | None] = {"ADRO": None, "TLKM": None}
    verdict, exit_code = guard.evaluate(stored, latest)
    out = capfd.readouterr().out
    assert exit_code == 1
    assert verdict == "verdict=behind"

def test_a_ticker_only_yahoo_lost_is_behind_with_a_distinct_message(capfd):
    stored = {"ADRO": date(2026, 10, 8), "TLKM": date(2026, 10, 8)}
    latest = {"ADRO": date(2026, 10, 9), "TLKM": None}
    verdict, exit_code = guard.evaluate(stored, latest)
    out = capfd.readouterr().out
    assert exit_code == 1
    assert "no Yahoo rows: TLKM" in out

def test_fresh_when_every_ticker_matches(capfd):
    stored = {"ADRO": date(2026, 10, 9), "TLKM": date(2026, 10, 9)}
    latest = {"ADRO": date(2026, 10, 9), "TLKM": date(2026, 10, 9)}
    verdict, exit_code = guard.evaluate(stored, latest)
    out = capfd.readouterr().out
    assert exit_code == 0
    assert verdict == "verdict=fresh"
