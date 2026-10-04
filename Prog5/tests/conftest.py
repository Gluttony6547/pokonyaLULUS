from __future__ import annotations

import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from prog5 import config, db, model_registry  # noqa: E402


def _research_available() -> bool:
    try:
        config.research_data_dir()
        return True
    except config.ConfigurationError:
        return False


def _artifacts_available() -> bool:
    try:
        config.artifact_dir()
        return True
    except config.ConfigurationError:
        return False


requires_research = pytest.mark.skipif(
    not _research_available(), reason="CODE research data not available"
)
requires_artifacts = pytest.mark.skipif(
    not (_research_available() and _artifacts_available()),
    reason="H5 artifacts or research data not available",
)


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PROG5_DB_PATH", str(tmp_path / "test.sqlite3"))
    db.clear_caches()
    model_registry.clear_caches()
    db.init_db()
    yield db
    db.clear_caches()
