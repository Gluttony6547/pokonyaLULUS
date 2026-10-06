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


@pytest.fixture(autouse=True)
def no_local_environment_file(tmp_path_factory, monkeypatch):
    """Keep a developer's real .env and shell Postgres URL out of the suite.

    Without this, tests would inherit the live Neon database from the
    untracked .env and write to production instead of a temporary SQLite file.
    """
    absent = tmp_path_factory.mktemp("env") / "absent.env"
    monkeypatch.setenv("PROG5_ENV_FILE", str(absent))
    for name in (
        "PROG5_DATABASE_URL",
        "DATABASE_URL_POOLED",
        "DATABASE_URL_UNPOOLED",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PROG5_DB_PATH", str(tmp_path / "test.sqlite3"))
    assert config.database_url() is None, "tests must not reach a Postgres database"
    db.clear_caches()
    model_registry.clear_caches()
    db.init_db()
    yield db
    db.clear_caches()
