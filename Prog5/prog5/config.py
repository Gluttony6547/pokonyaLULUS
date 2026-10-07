"""Settings resolved at call time so tests can redirect paths via environment."""

from __future__ import annotations

import os
from datetime import time
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
REPOSITORY_DIR = PROJECT_DIR.parent

SUPPORTED_SYMBOLS = (
    "ADRO",
    "ANTM",
    "BMRI",
    "BNGA",
    "EXCL",
    "INCO",
    "INKP",
    "MEDC",
    "PGAS",
    "TLKM",
)
HORIZONS = (1, 5, 10, 20, 50)
RETURN_THRESHOLDS = {1: 0.015, 5: 0.03, 10: 0.06, 20: 0.09, 50: 0.11}
SIGNAL_LABELS = {-1: "sell", 0: "hold", 1: "buy"}

# A close more than this many training standard deviations from the training
# mean flags the prediction as out of distribution.
OOD_Z_THRESHOLD = 2.0
# Overnight move larger than this is treated as a corporate action, not a trend.
CORPORATE_ACTION_JUMP = 0.30
# Yahoo Finance is the daily source; five years covers the 50-day windows plus
# the indicator warm-up with room to spare.
DEFAULT_HISTORY_PERIOD = "5y"
RESEARCH_START_DATE = "2018-09-25"
RESEARCH_END_DATE = "2023-09-25"


class ConfigurationError(RuntimeError):
    """A required path or setting is missing."""


def _resolve(env_name: str, candidates: list[Path], description: str) -> Path:
    override = os.environ.get(env_name)
    if override:
        path = Path(override).expanduser().resolve()
        if not path.exists():
            raise ConfigurationError(f"{env_name} points at a missing {description}: {path}")
        return path
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    listed = "\n  ".join(str(candidate) for candidate in candidates)
    raise ConfigurationError(
        f"No {description} found. Set {env_name} or provide one of:\n  {listed}"
    )


# ---------- Optional local environment file ----------
# A gitignored .env beside this package points a workstation at Postgres
# without exporting variables in every new shell. Real environment variables
# always win, an empty value counts as unset, and a missing file is not an
# error, so a clean checkout behaves exactly as before. PROG5_ENV_FILE sends
# the lookup somewhere else, which is how the tests stay off a live database.

ENV_FILE_NAME = ".env"


def env_file_path() -> Path:
    """Location of the optional environment file."""
    override = os.environ.get("PROG5_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_DIR / ENV_FILE_NAME


def _env_file_values(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, skipping blanks, comments and quoted values."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.startswith("export "):
            name = name.removeprefix("export ")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name.strip():
            values[name.strip()] = value
    return values


def env_value(name: str, default: str | None = None) -> str | None:
    """Resolve a setting from the environment, then from the optional .env."""
    raw = os.environ.get(name)
    if raw is not None and raw.strip():
        return raw
    value = _env_file_values(env_file_path()).get(name)
    if value is not None and value.strip():
        return value
    return default


def db_path() -> Path:
    override = env_value("PROG5_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_DIR / "data" / "prog5.sqlite3"


def database_url() -> str | None:
    """Postgres is used when configured; otherwise keep local SQLite behavior."""
    for name in (
        "PROG5_DATABASE_URL",
        "DATABASE_URL_POOLED",
        "DATABASE_URL_UNPOOLED",
        "DATABASE_URL",
    ):
        value = env_value(name) or ""
        if value.startswith(("postgres://", "postgresql://", "postgresql+")):
            return value
    return None


def artifact_dir() -> Path:
    """Directory holding the lecturer's saved models."""
    return _resolve(
        "PROG5_ARTIFACT_DIR",
        [
            REPOSITORY_DIR / "models",
            PROJECT_DIR / "models",
            REPOSITORY_DIR / "CODE" / "Price Prediction Model",
        ],
        "model artifact directory",
    )


def artifact_file(symbol: str, horizon: int) -> Path:
    """Locate one artifact, accepting the research layout or a flat layout."""
    directory = artifact_dir()
    name = f"LSTM_{symbol}_Target_{horizon}.h5"
    candidates = (directory / symbol / name, directory / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ConfigurationError(
        f"Artifact {name} not found under {directory}. "
        "Sub-directories are expected per ticker, as in CODE/Price Prediction Model."
    )


def research_data_dir() -> Path:
    """Directory holding Fusion_Data_*.csv and Labelled_Stock_*.csv."""
    return _resolve(
        "PROG5_RESEARCH_DATA_DIR",
        [
            PROJECT_DIR / "data" / "research",
            REPOSITORY_DIR / "CODE",
        ],
        "research data directory",
    )


def fusion_file(symbol: str) -> Path:
    path = research_data_dir() / "Data Fusion of Historical and Sentiment" / f"Fusion_Data_{symbol}.csv"
    if path.is_file():
        return path
    flat = research_data_dir() / f"Fusion_Data_{symbol}.csv"
    if flat.is_file():
        return flat
    raise ConfigurationError(f"Fusion_Data_{symbol}.csv not found under {research_data_dir()}")


def labelled_file(symbol: str) -> Path:
    path = research_data_dir() / "Labelled Stock Data" / f"Labelled_Stock_{symbol}.csv"
    if path.is_file():
        return path
    flat = research_data_dir() / f"Labelled_Stock_{symbol}.csv"
    if flat.is_file():
        return flat
    raise ConfigurationError(f"Labelled_Stock_{symbol}.csv not found under {research_data_dir()}")


def raw_stock_file(symbol: str) -> Path:
    """Committed raw OHLCV, used by the indicator parity test."""
    path = research_data_dir() / "Raw Stock Data" / symbol / f"Stock_{symbol}.csv"
    if path.is_file():
        return path
    raise ConfigurationError(f"Raw stock data missing: {path}")


def result_file(symbol: str, horizon: int) -> Path:
    """Committed research prediction CSV, used by the replication check."""
    directory = research_data_dir() / "Result Price Prediction" / symbol
    path = directory / f"LSTM_{symbol}_Target_{horizon}.csv"
    if path.is_file():
        return path
    raise ConfigurationError(f"Research result CSV missing: {path}")


# ---------- Unattended refresh ----------
# Every setting is read from the environment at call time, next to the other
# overrides, so a scheduled process can be configured without touching code.

_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _env_int(name: str, default: int) -> int:
    raw = env_value(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from error


def schedule_times() -> tuple[time, ...]:
    """Local times of day the refresh should run, from PROG5_SCHEDULE_TIMES."""
    # Two slots per trading day: Yahoo's EOD update for IDX names usually
    # lands by 17:30 WIB but sometimes drifts later, so the evening slot
    # catches stragglers and self-heals any missed afternoon run.
    raw = env_value("PROG5_SCHEDULE_TIMES", "17:30,21:00") or ""
    times: list[time] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hours, minutes = part.split(":")
            times.append(time(int(hours), int(minutes)))
        except ValueError as error:
            raise ConfigurationError(
                f"PROG5_SCHEDULE_TIMES entry {part!r} is not HH:MM"
            ) from error
    if not times:
        raise ConfigurationError("PROG5_SCHEDULE_TIMES has no usable entries")
    return tuple(sorted(set(times)))


def schedule_days() -> frozenset[int]:
    """Weekdays the schedule applies to, from PROG5_SCHEDULE_DAYS."""
    raw = env_value("PROG5_SCHEDULE_DAYS", "mon,tue,wed,thu,fri") or ""
    days: set[int] = set()
    for part in raw.split(","):
        key = part.strip().lower()[:3]
        if not key:
            continue
        if key not in _DAY_NAMES:
            raise ConfigurationError(
                f"PROG5_SCHEDULE_DAYS entry {part!r} is not a weekday name"
            )
        days.add(_DAY_NAMES[key])
    if not days:
        raise ConfigurationError("PROG5_SCHEDULE_DAYS has no usable entries")
    return frozenset(days)


def schedule_symbols() -> tuple[str, ...]:
    """Tickers a scheduled run refreshes, from PROG5_SCHEDULE_SYMBOLS."""
    raw = env_value("PROG5_SCHEDULE_SYMBOLS")
    if raw is None or not raw.strip():
        return SUPPORTED_SYMBOLS
    symbols = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    unknown = [symbol for symbol in symbols if symbol not in SUPPORTED_SYMBOLS]
    if unknown:
        raise ConfigurationError(f"PROG5_SCHEDULE_SYMBOLS has unsupported tickers: {unknown}")
    return symbols


def schedule_retry_attempts() -> int:
    """Extra attempts after a failed run, from PROG5_SCHEDULE_RETRY_ATTEMPTS."""
    return max(0, _env_int("PROG5_SCHEDULE_RETRY_ATTEMPTS", 2))


def schedule_retry_delay_seconds() -> int:
    """Seconds between failed attempts, from PROG5_SCHEDULE_RETRY_DELAY_SECONDS."""
    return max(0, _env_int("PROG5_SCHEDULE_RETRY_DELAY_SECONDS", 300))


def schedule_poll_seconds() -> int:
    """How often the loop checks the clock, from PROG5_SCHEDULE_POLL_SECONDS."""
    return max(1, _env_int("PROG5_SCHEDULE_POLL_SECONDS", 30))


def schedule_stale_lock_seconds() -> int:
    """Age at which an abandoned lock file may be broken."""
    return max(60, _env_int("PROG5_SCHEDULE_STALE_LOCK_SECONDS", 6 * 3600))


def schedule_stale_run_seconds() -> int:
    """Age at which a still-running run row counts as interrupted."""
    return max(60, _env_int("PROG5_SCHEDULE_STALE_RUN_SECONDS", 6 * 3600))
