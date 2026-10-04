from __future__ import annotations

from sqlalchemy import MetaData, create_engine, inspect, select

from prog5 import db
from prog5.models import Base, RefreshRun, Stock
from prog5.snapshot import import_snapshot


def test_snapshot_import_is_idempotent(temp_db, tmp_path):
    source_path = tmp_path / "snapshot.sqlite3"
    source = create_engine(f"sqlite+pysqlite:///{source_path}", future=True)
    Base.metadata.create_all(source)
    with source.begin() as connection:
        connection.execute(Stock.__table__.insert().values(symbol="ADRO", is_research_ticker=True))
        connection.execute(
            RefreshRun.__table__.insert().values(
                kind="scheduled", status="completed", requested_symbols="ADRO", horizons="1,5"
            )
        )

    assert import_snapshot(source_path) == {
        "prog5_stocks": 1,
        "prog5_stock_prices": 0,
        "prog5_technical_indicators": 0,
        "prog5_refresh_runs": 1,
        "prog5_predictions": 0,
    }
    import_snapshot(source_path)

    with temp_db.session() as session:
        assert session.scalar(select(Stock.symbol)) == "ADRO"
        assert session.query(RefreshRun).count() == 1
    source.dispose()


def test_existing_sqlite_tables_are_moved_out_of_legacy_names(monkeypatch, tmp_path):
    legacy_path = tmp_path / "legacy.sqlite3"
    legacy_engine = create_engine(f"sqlite+pysqlite:///{legacy_path}", future=True)
    legacy_metadata = MetaData()
    Stock.__table__.to_metadata(legacy_metadata, name="stocks")
    legacy_metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            legacy_metadata.tables["stocks"].insert().values(
                symbol="ADRO", is_research_ticker=True
            )
        )
    legacy_engine.dispose()

    monkeypatch.setenv("PROG5_DB_PATH", str(legacy_path))
    db.clear_caches()
    migrated = db.init_db()

    names = set(inspect(migrated).get_table_names())
    assert "prog5_stocks" in names
    assert "stocks" not in names
    with db.session() as session:
        assert session.get(Stock, "ADRO") is not None
    db.clear_caches()
