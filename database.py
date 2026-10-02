import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


DATA_DIRECTORY = Path(__file__).resolve().parent / "data"
DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
load_dotenv(Path(__file__).resolve().parent / ".env")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    database_url = URL.create(
        "sqlite",
        database=str(DATA_DIRECTORY / "stock_signal.db"),
    ).render_as_string(hide_password=False)
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

engine_options = {"pool_pre_ping": True}
if database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        engine_options["poolclass"] = StaticPool

engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
