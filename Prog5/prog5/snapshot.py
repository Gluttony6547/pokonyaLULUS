"""Idempotently copy a local Prog5 SQLite snapshot into the configured store."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import db
from .models import Prediction, RefreshRun, Stock, StockPrice, TechnicalIndicator

_TABLES = (Stock, StockPrice, TechnicalIndicator, RefreshRun, Prediction)
_LEGACY_NAMES = {
    "prog5_stocks": "stocks",
    "prog5_stock_prices": "stock_prices",
    "prog5_technical_indicators": "technical_indicators",
    "prog5_refresh_runs": "refresh_runs",
    "prog5_predictions": "predictions",
}


def import_snapshot(source: str | Path) -> dict[str, int]:
    """Import a SQLite backup into the active database, preserving existing rows."""
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite snapshot not found: {path}")

    target = db.init_db()
    source_engine = create_engine(f"sqlite+pysqlite:///{path}", future=True)
    source_metadata = MetaData()
    source_metadata.reflect(source_engine)
    counts: dict[str, int] = {}
    try:
        with source_engine.connect() as source_connection, target.begin() as target_connection:
            available = set(inspect(source_engine).get_table_names())
            for model in _TABLES:
                target_table = model.__table__
                legacy_name = _LEGACY_NAMES[target_table.name]
                source_name = (
                    legacy_name
                    if legacy_name in available
                    else target_table.name if target_table.name in available else None
                )
                if source_name is None:
                    counts[target_table.name] = 0
                    continue
                source_table: Table = source_metadata.tables[source_name]
                columns = [column.name for column in target_table.columns if column.name in source_table.c]
                source_rows = source_connection.execute(source_table.select()).mappings()
                dialect = target_connection.dialect.name
                insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
                inserted = 0
                while rows := source_rows.fetchmany(1000):
                    payload = [{name: row[name] for name in columns} for row in rows]
                    statement = insert(target_table).values(payload).on_conflict_do_nothing()
                    target_connection.execute(statement)
                    inserted += len(payload)
                if dialect == "postgresql" and "id" in target_table.c:
                    target_connection.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {target_table.name}"
                        ),
                        {"table_name": target_table.name},
                    )
                counts[target_table.name] = inserted
    finally:
        source_engine.dispose()
    return counts
