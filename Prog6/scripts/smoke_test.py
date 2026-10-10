"""Headless smoke test: seed a throwaway SQLite, run the Prog6 pipeline over it.

Never touches the configured DATABASE_URL: the .env fallback is disarmed by
pointing PROG5_ENV_FILE at a missing path, and PROG5_DB_PATH points at a
temp file deleted at the end.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Prog5"))

# Disarm the .env fallback BEFORE importing prog5.config: one exists in Prog5/
os.environ["PROG5_ENV_FILE"] = str(Path(tempfile.gettempdir()) / "nonexistent-prog6-smoke.env")
os.environ["PROG5_DATABASE_URL"] = ""

import numpy as np  # noqa: E402

DB_PATH = Path(tempfile.gettempdir()) / "prog6-smoke.sqlite3"
os.environ["PROG5_DB_PATH"] = str(DB_PATH)

from prog5 import db  # noqa: E402
from prog5.models import Stock, StockPrice  # noqa: E402
from sqlalchemy import select  # noqa: E402

db.clear_caches()
if DB_PATH.exists():
    DB_PATH.unlink()

db.init_db()

with db.session() as session:
    session.add(Stock(symbol="ADRO"))
    rng = np.random.default_rng(3)
    closes = list(2500 * np.exp(np.cumsum(0.001 + rng.normal(0, 0.01, 260))))
    day = date(2026, 10, 9) - timedelta(days=260)
    for i, close in enumerate(closes):
        if day.weekday() < 5:
            session.add(
                StockPrice(
                    symbol="ADRO",
                    price_date=day,
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    volume=1000,
                    source="yahoo_finance",
                )
            )
        day += timedelta(days=1)

from prog6.refresh import refresh  # noqa: E402

reports = refresh(("ADRO",), (1, 5))
ok = True
for report in reports:
    print(f"{report.symbol}: predictions={report.predictions} errors={report.errors}")
    for backtest in report.backtests:
        print(f"  T{backtest.horizon} {backtest.policy} {backtest.metrics.to_text()}")
    if report.errors:
        ok = False

with db.session() as session:
    from prog6.storage import PolicyResult, Prediction
    from sqlalchemy import func

    stored = session.scalar(select(func.count()).select_from(Prediction)) or 0
    policies = session.scalar(select(func.count()).select_from(PolicyResult)) or 0
print(f"stored predictions={stored} policy rows={policies}")

idempotent = refresh(("ADRO",), (1,))
print("second run predictions:", sum(r.predictions for r in idempotent))

# The pooled engine holds the SQLite file open; dispose every engine before unlinking.
from prog5 import db as _db
_db.clear_caches()
_db._engine_for.cache_clear()
_db._session_factory.cache_clear()
try:
    DB_PATH.unlink(missing_ok=True)
except PermissionError:
    print("note: sqlite temp file still locked by the pool; leaving it")
print("smoke OK" if ok and stored == 2 and policies == 6 else "smoke FAILED")
raise SystemExit(0 if ok else 1)
