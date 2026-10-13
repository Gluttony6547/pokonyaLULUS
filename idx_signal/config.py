"""Settings resolved at call time so tests and deploys can redirect them.

Schedule times are wall-clock WIB (Asia/Jakarta), never the host's local time:
the service runs on a UTC host, and the market it follows does not.
"""

from __future__ import annotations

import os
import re
from datetime import time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Set before anything imports keras. The saved artifacts are Keras 3 files and
# torch is the only backend installed here.
os.environ.setdefault("KERAS_BACKEND", "torch")

from dotenv import load_dotenv  # noqa: E402 - must follow the backend selection

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

WIB = ZoneInfo("Asia/Jakarta")

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

# Thresholds from the reference research: a change smaller than this in either
# direction is HOLD.
RETURN_THRESHOLDS = {1: 0.015, 5: 0.03, 10: 0.06, 20: 0.09, 50: 0.11}
SIGNAL_FOR_CLASS = {-1: "SELL", 0: "HOLD", 1: "BUY"}
# The research CSVs encode the same three classes numerically.
SIGNAL_FOR_RESEARCH_CLASS = {0: "SELL", 1: "HOLD", 2: "BUY"}

# A close this many training standard deviations from the training mean marks
# the prediction as out of distribution.
OOD_Z_THRESHOLD = 2.0
# An overnight move larger than this is a corporate action, not a trend.
CORPORATE_ACTION_JUMP = 0.30
DEFAULT_HISTORY_PERIOD = "5y"

# IDX closes its second session at 16:00 WIB. The daily bar is treated as
# final once the close plus a short grace period has passed; before that Yahoo
# serves an intraday price that must not be stored as a closing price.
SESSION_CLOSE = time(16, 0)
BAR_FINAL_GRACE_MINUTES = 5

# Two slots per trading day. The first runs right after the close so the
# dashboard is current; the later one overwrites the same rows with the
# provider's settled EOD values, which is how a straggling feed self-heals.
DEFAULT_SCHEDULE_TIMES = "16:05,18:00"
DEFAULT_SCHEDULE_DAYS = "mon,tue,wed,thu,fri"

# Where the saved LSTM artifacts and the research series live. The research
# checkout is the natural source on a workstation; a deployment image ships
# only the artifacts.
ARTIFACT_DIR_ENV = "IDX_ARTIFACT_DIR"
RESEARCH_DIR_ENV = "IDX_RESEARCH_DATA_DIR"


class ConfigurationError(RuntimeError):
    """A required path or setting is missing."""


def _load_env_file() -> None:
    """Read the gitignored .env beside the project, without overriding the shell."""
    load_dotenv(PROJECT_DIR / ".env", override=False)


_load_env_file()


def env_value(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    if raw is not None and raw.strip():
        return raw.strip()
    return default


def database_url() -> str | None:
    """The Postgres URL, if this process has one. SQLite is the local fallback."""
    for name in ("IDX_DATABASE_URL", "DATABASE_URL", "DATABASE_URL_UNPOOLED"):
        value = env_value(name) or ""
        if value.startswith(("postgres://", "postgresql://", "postgresql+")):
            return value
    return None


def database_schema() -> str | None:
    """Optional Postgres schema for the application's tables.

    Empty by default, which means the connection's default schema, so a fresh
    database gets the Physical Data Model's table names directly. Set it when
    the database is shared with other work: the tables then live in their own
    namespace and still carry the PDM names. Ignored on SQLite, which has no
    schemas.
    """
    raw = env_value("IDX_DATABASE_SCHEMA")
    if raw is None:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        raise ConfigurationError(
            f"IDX_DATABASE_SCHEMA must be a plain identifier, got {raw!r}"
        )
    return raw


def sqlite_path() -> Path:
    override = env_value("IDX_SQLITE_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_DIR / "data" / "sinyal.sqlite3"


def _holds_artifacts(candidate: Path) -> bool:
    """True when a directory actually contains saved LSTM files.

    Existence alone is not enough: a directory can exist for another reason and
    then shadow the real artifact tree, which is how a training run once broke
    the prediction path.
    """
    if not candidate.is_dir():
        return False
    if any(candidate.glob("LSTM_*_Target_*.h5")):
        return True
    return any(candidate.glob("*/LSTM_*_Target_*.h5"))


def artifact_dir() -> Path:
    override = env_value(ARTIFACT_DIR_ENV)
    if override:
        path = Path(override).expanduser().resolve()
        if not path.exists():
            raise ConfigurationError(f"{ARTIFACT_DIR_ENV} points at a missing directory: {path}")
        return path
    candidates = [
        PROJECT_DIR / "models",
        PROJECT_DIR / "data" / "models",
        PROJECT_DIR / "CODE" / "Price Prediction Model",
    ]
    for candidate in candidates:
        if _holds_artifacts(candidate):
            return candidate.resolve()
    listed = "\n  ".join(str(candidate) for candidate in candidates)
    raise ConfigurationError(
        "No model artifact directory found. Set "
        f"{ARTIFACT_DIR_ENV} or provide one of:\n  {listed}"
    )


def artifact_file(symbol: str, horizon_days: int) -> Path:
    """Locate one artifact, accepting the research layout or a flat layout."""
    directory = artifact_dir()
    name = f"LSTM_{symbol}_Target_{horizon_days}.h5"
    for candidate in (directory / symbol / name, directory / name):
        if candidate.is_file():
            return candidate
    raise ConfigurationError(
        f"Artifact {name} not found under {directory}. Per-ticker sub-directories "
        "are expected, as in CODE/Price Prediction Model."
    )


def _holds_research(candidate: Path) -> bool:
    """True when a directory actually holds the reference series.

    Existence alone is not enough here either: an unrelated directory in one of
    the candidate slots would otherwise win the lookup and then fail on the
    first missing file.
    """
    if not candidate.is_dir():
        return False
    return bool(
        list(candidate.glob("Labelled Stock Data/Labelled_Stock_*.csv"))
        or list(candidate.glob("Labelled_Stock_*.csv"))
    )


def research_dir() -> Path:
    override = env_value(RESEARCH_DIR_ENV)
    if override:
        path = Path(override).expanduser().resolve()
        if not _holds_research(path):
            raise ConfigurationError(
                f"{RESEARCH_DIR_ENV} does not contain the reference series: {path}"
            )
        return path
    candidates = [PROJECT_DIR / "data" / "research", PROJECT_DIR / "CODE"]
    for candidate in candidates:
        if _holds_research(candidate):
            return candidate.resolve()
    listed = "\n  ".join(str(candidate) for candidate in candidates)
    raise ConfigurationError(
        f"No research data directory found. Set {RESEARCH_DIR_ENV} or provide one of:\n  {listed}"
    )


def _research_file(*parts: str) -> Path:
    """Find a reference file under the nested research layout or a flat copy."""
    directory = research_dir()
    candidates = [directory.joinpath(*parts)]
    if len(parts) > 1:
        candidates.append(directory.joinpath(parts[-1]))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    listed = "\n  ".join(str(candidate) for candidate in candidates)
    raise ConfigurationError(f"Research file missing:\n  {listed}")


def fusion_file(symbol: str) -> Path:
    """Historical closes fused with the news sentiment features."""
    return _research_file("Data Fusion of Historical and Sentiment", f"Fusion_Data_{symbol}.csv")


def labelled_file(symbol: str) -> Path:
    """Closes labelled with the buy/hold/sell target for each horizon."""
    return _research_file("Labelled Stock Data", f"Labelled_Stock_{symbol}.csv")


def result_file(symbol: str, horizon_days: int) -> Path:
    """The committed research prediction for one ticker and horizon."""
    return _research_file(
        "Result Price Prediction", symbol, f"LSTM_{symbol}_Target_{horizon_days}.csv"
    )


_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _env_int(name: str, default: int) -> int:
    raw = env_value(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from error


def schedule_times() -> tuple[time, ...]:
    raw = env_value("IDX_SCHEDULE_TIMES", DEFAULT_SCHEDULE_TIMES) or ""
    times: list[time] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hours, minutes = part.split(":")
            times.append(time(int(hours), int(minutes)))
        except ValueError as error:
            raise ConfigurationError(f"IDX_SCHEDULE_TIMES entry {part!r} is not HH:MM") from error
    if not times:
        raise ConfigurationError("IDX_SCHEDULE_TIMES has no usable entries")
    return tuple(sorted(set(times)))


def schedule_days() -> frozenset[int]:
    raw = env_value("IDX_SCHEDULE_DAYS", DEFAULT_SCHEDULE_DAYS) or ""
    days: set[int] = set()
    for part in raw.split(","):
        key = part.strip().lower()[:3]
        if not key:
            continue
        if key not in _DAY_NAMES:
            raise ConfigurationError(f"IDX_SCHEDULE_DAYS entry {part!r} is not a weekday name")
        days.add(_DAY_NAMES[key])
    if not days:
        raise ConfigurationError("IDX_SCHEDULE_DAYS has no usable entries")
    return frozenset(days)


def schedule_symbols() -> tuple[str, ...]:
    raw = env_value("IDX_SCHEDULE_SYMBOLS")
    if raw is None:
        return SUPPORTED_SYMBOLS
    symbols = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    unknown = [symbol for symbol in symbols if symbol not in SUPPORTED_SYMBOLS]
    if unknown:
        raise ConfigurationError(f"IDX_SCHEDULE_SYMBOLS has unsupported tickers: {unknown}")
    return symbols


def schedule_retry_attempts() -> int:
    return max(0, _env_int("IDX_SCHEDULE_RETRY_ATTEMPTS", 2))


def schedule_retry_delay_seconds() -> int:
    return max(0, _env_int("IDX_SCHEDULE_RETRY_DELAY_SECONDS", 300))


def schedule_poll_seconds() -> int:
    return max(1, _env_int("IDX_SCHEDULE_POLL_SECONDS", 60))


def stale_run_seconds() -> int:
    """Age at which a still-running job counts as interrupted rather than live."""
    return max(60, _env_int("IDX_STALE_RUN_SECONDS", 6 * 3600))


def cron_secret() -> str | None:
    """Bearer token the scheduled endpoint requires.

    No default: an unset secret makes the endpoint refuse to run rather than
    expose a public trigger that starts a full data fetch.
    """
    return env_value("CRON_SECRET")


def training_epochs() -> int:
    return max(1, _env_int("IDX_TRAINING_EPOCHS", 10))


def training_dir() -> Path:
    """Where retrained artifacts are written."""
    override = env_value("IDX_TRAINING_DIR")
    path = Path(override).expanduser().resolve() if override else PROJECT_DIR / "data" / "trained"
    path.mkdir(parents=True, exist_ok=True)
    return path


def training_inline() -> bool:
    """Whether the API should run a queued job in a background thread.

    Convenient on a workstation. A long-running deployment should instead run
    `idx_signal.cli train-worker`, which survives the API request that queued it.
    """
    raw = (env_value("IDX_TRAINING_INLINE", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def trading_day_close_utc(day) -> "datetime":  # noqa: F821 - datetime imported lazily below
    """UTC moment the dated session's bar becomes final."""
    from datetime import datetime

    moment = datetime(
        day.year,
        day.month,
        day.day,
        SESSION_CLOSE.hour,
        SESSION_CLOSE.minute,
        tzinfo=WIB,
    ) + timedelta(minutes=BAR_FINAL_GRACE_MINUTES)
    return moment.astimezone(ZoneInfo("UTC"))
