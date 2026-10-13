"""Shared fixtures.

Every test runs against a throwaway SQLite file, never the configured Postgres
database and never the network: anything that fetches is monkeypatched.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from idx_signal import config, db
from idx_signal.storage import ensure_reference_data


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("IDX_SQLITE_PATH", str(tmp_path / "test.sqlite3"))
    for name in ("IDX_DATABASE_URL", "DATABASE_URL", "DATABASE_URL_UNPOOLED"):
        monkeypatch.delenv(name, raising=False)
    db.clear_caches()
    db.init_db()
    with db.session() as session:
        ensure_reference_data(session)
    yield
    db.clear_caches()


def make_prices(rows: int = 420, start: date = date(2024, 1, 2), seed: int = 7) -> pd.DataFrame:
    """A deterministic weekday OHLCV series for one symbol."""
    rng = np.random.default_rng(seed)
    records: list[dict] = []
    day = start
    price = 2000.0
    while len(records) < rows:
        if day.weekday() < 5:
            price = max(50.0, price * float(1 + rng.normal(0.0005, 0.012)))
            records.append(
                {
                    "date": day,
                    "open": round(price * 0.995, 2),
                    "high": round(price * 1.012, 2),
                    "low": round(price * 0.988, 2),
                    "close": round(price, 2),
                    "volume": 1_000_000 + len(records) * 1000,
                }
            )
        day += timedelta(days=1)
    return pd.DataFrame(records)


@pytest.fixture
def prices() -> pd.DataFrame:
    return make_prices()


@pytest.fixture
def offline_fetch(monkeypatch, prices):
    """Replace the provider with the synthetic series."""
    calls = {"count": 0}

    def fake_fetch(symbol, period=None, attempts=2):
        calls["count"] += 1
        return prices.copy()

    monkeypatch.setattr("idx_signal.refresh.fetch_daily_ohlcv", fake_fetch)
    monkeypatch.setattr("idx_signal.api.fetch_daily_ohlcv", fake_fetch, raising=False)
    return calls


@pytest.fixture
def reference_assets():
    """Skip a test that needs the saved artifacts and the research series."""
    try:
        config.artifact_file("ADRO", 1)
        config.fusion_file("ADRO")
        config.labelled_file("ADRO")
        config.result_file("ADRO", 1)
    except config.ConfigurationError as error:
        pytest.skip(f"reference assets unavailable: {error}")
    return True
