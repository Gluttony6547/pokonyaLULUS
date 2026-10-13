"""Engine and session helpers, resolved lazily so tests can repoint the URL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base


def storage_backend() -> str:
    return "postgresql" if config.database_url() else "sqlite"


def _locator() -> str:
    return config.database_url() or f"sqlite+pysqlite:///{config.sqlite_path()}"


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
            connect_args={
                "connect_timeout": 15,
                # Neon and Supabase both put a transaction-mode pooler in front
                # of Postgres, which cannot carry a session's prepared
                # statements across checkouts. Client-side preparation off.
                "prepare_threshold": None,
            },
        )
    path = Path(config.sqlite_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite+pysqlite:///{path}", future=True)


@lru_cache(maxsize=4)
def _session_factory(locator: str) -> sessionmaker[Session]:
    return sessionmaker(bind=_engine_for(locator), expire_on_commit=False, future=True)


def engine() -> Engine:
    return _engine_for(_locator())


def _ensure_schema(target: Engine) -> None:
    """Create the configured namespace before its tables, when one is set."""
    schema = config.database_schema()
    if not schema or target.dialect.name != "postgresql":
        return
    with target.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def init_db() -> Engine:
    """Create any missing tables. Additive only: nothing existing is altered."""
    created = engine()
    _ensure_schema(created)
    Base.metadata.create_all(created)
    return created


@contextmanager
def session() -> Iterator[Session]:
    handle = _session_factory(_locator())()
    try:
        yield handle
        handle.commit()
    except Exception:
        handle.rollback()
        raise
    finally:
        handle.close()


def clear_caches() -> None:
    """Drop cached engines so a new database URL takes effect (tests)."""
    _engine_for.cache_clear()
    _session_factory.cache_clear()
