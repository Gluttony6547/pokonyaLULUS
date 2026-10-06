from __future__ import annotations

from datetime import time

from prog5 import config, db

POSTGRES_URL = "postgresql://owner:secret@example.neon.tech/neondb?sslmode=require"


def write_env_file(tmp_path, monkeypatch, body: str):
    """Point the loader at a throwaway .env and return its path."""
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("PROG5_ENV_FILE", str(path))
    return path


def test_database_url_comes_from_the_environment_file(tmp_path, monkeypatch):
    write_env_file(tmp_path, monkeypatch, f"# local override\nPROG5_DATABASE_URL={POSTGRES_URL}\n")

    assert config.database_url() == POSTGRES_URL
    # The engine layer rewrites the driver but must keep the same database.
    db.clear_caches()
    try:
        assert db.engine().dialect.name == "postgresql"
    finally:
        db.clear_caches()


def test_real_environment_variables_win_over_the_file(tmp_path, monkeypatch):
    write_env_file(tmp_path, monkeypatch, f"PROG5_DATABASE_URL={POSTGRES_URL}\n")
    exported = "postgresql://exported:pw@other.example.tech/db"
    monkeypatch.setenv("PROG5_DATABASE_URL", exported)

    assert config.database_url() == exported


def test_an_empty_variable_falls_back_to_the_file(tmp_path, monkeypatch):
    write_env_file(tmp_path, monkeypatch, f"PROG5_DATABASE_URL={POSTGRES_URL}\n")
    monkeypatch.setenv("PROG5_DATABASE_URL", "   ")

    assert config.database_url() == POSTGRES_URL


def test_a_missing_environment_file_keeps_the_old_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PROG5_ENV_FILE", str(tmp_path / "nothing-here.env"))

    assert config.env_file_path().name == "nothing-here.env"
    assert config.database_url() is None
    assert config.db_path() == config.PROJECT_DIR / "data" / "prog5.sqlite3"
    assert config.schedule_times() == (time(17, 30), time(21, 0))


def test_the_default_location_is_the_project_directory(monkeypatch):
    monkeypatch.delenv("PROG5_ENV_FILE", raising=False)

    assert config.env_file_path() == config.PROJECT_DIR / ".env"


def test_the_file_tolerates_comments_quotes_and_export_lines(tmp_path, monkeypatch):
    write_env_file(
        tmp_path,
        monkeypatch,
        "\n".join(
            [
                "",
                "# a comment",
                "not a setting",
                f'export PROG5_DATABASE_URL="{POSTGRES_URL}"',
                "PROG5_SCHEDULE_TIMES=07:15, 17:30",
                "PROG5_SCHEDULE_DAYS='mon,wed,fri'",
                "PROG5_SCHEDULE_RETRY_ATTEMPTS=0",
            ]
        )
        + "\n",
    )

    assert config.database_url() == POSTGRES_URL
    assert config.schedule_times() == (time(7, 15), time(17, 30))
    assert config.schedule_days() == frozenset({0, 2, 4})
    assert config.schedule_retry_attempts() == 0


def test_postgres_prefixed_names_are_recognised_in_the_file(tmp_path, monkeypatch):
    shared = "postgresql://shared:pw@example.neon.tech/neondb"
    write_env_file(
        tmp_path,
        monkeypatch,
        f"DATABASE_URL_UNPOOLED=postgres://direct:pw@example.neon.tech/neondb\n"
        f"DATABASE_URL={shared}\n",
    )

    # The pooled/direct names are only consulted when PROG5_DATABASE_URL is unset.
    assert config.database_url() == "postgres://direct:pw@example.neon.tech/neondb"


def test_sqlite_values_are_not_mistaken_for_postgres(tmp_path, monkeypatch):
    write_env_file(tmp_path, monkeypatch, "PROG5_DATABASE_URL=sqlite:///tmp/other.sqlite3\n")

    assert config.database_url() is None
