"""Engine and session helpers. Lazy so tests can point PROG5_DB_PATH first."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base


def database_url() -> str | None:
    """Return the configured Postgres URL, if this process has one."""
    return config.database_url()


@lru_cache(maxsize=4)
def _engine_for(locator: str) -> Engine:
    if locator.startswith(("postgres://", "postgresql://", "postgresql+")):
        url = locator
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgres://")
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
        return create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
            pool_recycle=300,
            connect_args={"connect_timeout": 10},
        )
    path = Path(locator)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite+pysqlite:///{path}", future=True)


@lru_cache(maxsize=4)
def _session_factory(path: str) -> sessionmaker[Session]:
    return sessionmaker(bind=_engine_for(path), expire_on_commit=False, future=True)


def engine() -> Engine:
    return _engine_for(database_url() or str(config.db_path()))


def init_db() -> Engine:
    created = engine()
    _migrate_legacy_sqlite_tables(created)
    Base.metadata.create_all(created)
    return created


def _migrate_legacy_sqlite_tables(created: Engine) -> None:
    if created.dialect.name != "sqlite":
        return
    legacy = {
        "stocks": "prog5_stocks",
        "stock_prices": "prog5_stock_prices",
        "technical_indicators": "prog5_technical_indicators",
        "refresh_runs": "prog5_refresh_runs",
        "predictions": "prog5_predictions",
    }
    tables = set(inspect(created).get_table_names())
    with created.begin() as connection:
        for old, new in legacy.items():
            if old in tables and new not in tables:
                connection.execute(text(f'ALTER TABLE "{old}" RENAME TO "{new}"'))
                tables.remove(old)
                tables.add(new)


@contextmanager
def session() -> Iterator[Session]:
    factory = _session_factory(database_url() or str(config.db_path()))
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clear_caches() -> None:
    """Drop cached engines so a new PROG5_DB_PATH takes effect (tests)."""
    _engine_for.cache_clear()
    _session_factory.cache_clear()
