"""Signals recomputed at a reference date chosen by the reader.

The stored signals are written by `refresh` and only ever describe the newest
session. This module answers the other question a thesis reader asks: what did
the saved models say on a date I pick? It reads the closes up to that session
and predicts in memory, so nothing here can overwrite or impersonate an
operational signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import fmean

from sqlalchemy.orm import Session

from . import config
from .market_data import window_has_corporate_action
from .model_registry import (
    ModelUnavailable,
    Scalers,
    artifact_filename,
    predict_price,
    reference_artifact,
    scalers_from_research,
)
from .signals import classify_return, is_out_of_distribution, out_of_distribution_z
from .storage import (
    active_model_version,
    close_on_or_after,
    first_price_date_on_or_after,
    nth_price_date,
    price_date_range,
    price_frame_between,
    price_frame_until,
)
from .trading_calendar import crosses_unknown_year, load_holidays, target_date

MAX_REFERENCE_AGE_YEARS = 10
OUTCOME_LOOKUP_DAYS = 7
MONTHS_ID = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def format_date_id(day: date) -> str:
    """A date as the interface writes it, so errors do not leak ISO strings."""
    return f"{day.day} {MONTHS_ID[day.month - 1]} {day.year}"


class HistoricalDateError(ValueError):
    """A reference date that cannot produce a historical signal."""


@dataclass(frozen=True)
class HorizonSignal:
    symbol: str
    horizon_days: int
    data_as_of: date
    target_date: date
    reference_close: float
    predicted_price: float
    return_pct: float
    threshold_pct: float
    signal: str
    ood_z: float
    ood_flag: bool
    warnings: str | None
    model_artifact: str | None
    model_version_id: int | None
    actual_close: float | None = None
    actual_date: date | None = None
    actual_return_pct: float | None = None
    actual_signal: str | None = None
    prediction_error_pct: float | None = None
    direction_correct: bool | None = None
    outcome_status: str = "pending"
    outcome_approximate: bool = False


@dataclass(frozen=True)
class Scorecard:
    realized: int
    pending: int
    no_price: int
    corporate_action: int
    direction_correct: int
    direction_total: int
    mean_abs_error_pct: float | None


@dataclass(frozen=True)
class HistoricalSignals:
    symbol: str
    reference_date: date
    reference_close: float
    first_price_date: date
    last_price_date: date
    earliest_reference_date: date
    first_usable_reference_date: date | None
    scorecard: Scorecard
    signals: list[HorizonSignal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February in a year that has none
        return day.replace(year=day.year - years, day=28)


def reference_bounds(first_price_date: date, last_price_date: date) -> tuple[date, date]:
    """Oldest and newest reference dates: stored history, capped at ten years back."""
    oldest = max(
        first_price_date, _years_before(last_price_date, MAX_REFERENCE_AGE_YEARS)
    )
    return oldest, last_price_date


def first_usable_reference_date(
    session: Session, symbol: str, bounds: tuple[date, date] | None = None
) -> date | None:
    """The first stored session that can fill the longest model window.

    `earliest_reference_date` answers how far back the data goes. This is the
    stricter date the picker can actually offer: a session, and one with enough
    closes behind it for every horizon.
    """
    if bounds is None:
        first_price_date, last_price_date = price_date_range(session, symbol)
    else:
        first_price_date, last_price_date = bounds
    if first_price_date is None or last_price_date is None:
        return None

    earliest, _ = reference_bounds(first_price_date, last_price_date)
    window_start = nth_price_date(session, symbol, max(config.HORIZONS))
    if window_start is None:
        return None
    return first_price_date_on_or_after(session, symbol, max(earliest, window_start))


def _calendar_note(known_years: frozenset[int]) -> str:
    covered = ", ".join(str(year) for year in sorted(known_years))
    return (
        f"Tanggal target di luar tahun {covered} masih perkiraan: kalender libur "
        "bursa baru mencakup tahun tersebut."
    )


def _model_for(session: Session, symbol: str, horizon_days: int) -> tuple[str, Scalers, int | None]:
    """The active model version, or the saved reference artifact when none is registered."""
    version = active_model_version(session, symbol, horizon_days)
    if version is not None:
        try:
            return version.artifact_path, Scalers.from_config(version.config), version.id
        except ModelUnavailable:
            # A version without stored scalers cannot predict; the reference pair can.
            pass
    return (
        reference_artifact(symbol, horizon_days)["path"],
        scalers_from_research(symbol, horizon_days),
        None,
    )


def signals_for_date(
    session: Session,
    symbol: str,
    reference_date: date,
    horizons: tuple[int, ...] = config.HORIZONS,
) -> HistoricalSignals:
    """Recompute every horizon from the closes available on `reference_date`."""
    horizon_list = tuple(sorted(int(horizon) for horizon in horizons))
    if not horizon_list:
        raise ValueError("at least one horizon is required")

    first_price_date, last_price_date = price_date_range(session, symbol)
    if first_price_date is None or last_price_date is None:
        raise HistoricalDateError(
            f"Belum ada harga tersimpan untuk {symbol}. Perbarui harga lebih dulu."
        )

    earliest, latest = reference_bounds(first_price_date, last_price_date)
    usable = first_usable_reference_date(
        session, symbol, (first_price_date, last_price_date)
    )
    lower = usable or earliest
    if reference_date > latest:
        raise HistoricalDateError(
            f"Tanggal {format_date_id(reference_date)} melewati harga terbaru "
            f"{format_date_id(latest)}. Pilih tanggal antara {format_date_id(lower)} "
            f"dan {format_date_id(latest)}."
        )
    if reference_date < earliest:
        raise HistoricalDateError(
            f"Tanggal {format_date_id(reference_date)} di luar rentang data. "
            f"Pilih tanggal antara {format_date_id(lower)} dan {format_date_id(latest)}."
        )

    needed = max(horizon_list)
    frame = price_frame_until(session, symbol, reference_date, limit=needed)
    if frame.empty or frame.iloc[-1]["date"] != reference_date:
        previous = None if frame.empty else frame.iloc[-1]["date"]
        hint = (
            f" Sesi terakhir sebelumnya adalah {format_date_id(previous)}."
            if previous
            else ""
        )
        raise HistoricalDateError(
            f"Tidak ada harga penutupan pada {format_date_id(reference_date)}.{hint} "
            "Pilih tanggal sesi bursa yang punya harga."
        )
    if len(frame) < needed:
        first_fit = nth_price_date(session, symbol, needed)
        hint = (
            f" Tanggal acuan paling awal yang cukup adalah {format_date_id(first_fit)}."
            if first_fit
            else ""
        )
        raise HistoricalDateError(
            f"Sampai {format_date_id(reference_date)} hanya ada {len(frame)} sesi harga, "
            f"model butuh {needed} sesi masukan.{hint}"
        )

    holidays, known_years = load_holidays(session)
    reference_close = float(frame.iloc[-1]["close"])
    projected_dates = {
        horizon: target_date(reference_date, horizon, holidays)
        for horizon in horizon_list
    }
    rows: list[HorizonSignal] = []
    warnings: list[str] = []

    # The holiday table covers a few years; a historical date usually does not.
    # Said once for the lookup instead of once per row.
    if any(
        crosses_unknown_year(reference_date, horizon, known_years)
        for horizon in horizon_list
    ):
        warnings.append(_calendar_note(known_years))

    for horizon in horizon_list:
        if window_has_corporate_action(frame, horizon):
            warnings.append(
                f"T{horizon}: ada aksi korporasi di dalam jendela masukan, "
                "prediksi dilewati"
            )
            continue

        artifact_path, scalers, version_id = _model_for(session, symbol, horizon)
        predicted = float(
            predict_price(artifact_path, horizon, frame["close"], scalers)
        )
        signal, change_pct = classify_return(predicted, reference_close, horizon)
        z = out_of_distribution_z(reference_close, scalers.input_mean, scalers.input_scale)
        ood = is_out_of_distribution(z)
        projected = projected_dates[horizon]

        actual_close: float | None = None
        actual_date: date | None = None
        actual_return_pct: float | None = None
        actual_signal: str | None = None
        prediction_error_pct: float | None = None
        direction_correct: bool | None = None
        outcome_status = "pending"
        outcome_approximate = False

        if projected <= last_price_date:
            outcome = close_on_or_after(
                session, symbol, projected, OUTCOME_LOOKUP_DAYS
            )
            if outcome is None:
                outcome_status = "no_price"
            else:
                actual_date, actual_close = outcome
                outcome_approximate = actual_date != projected
                outcome_frame = price_frame_between(
                    session, symbol, reference_date, actual_date
                )
                if len(outcome_frame) >= 2 and window_has_corporate_action(
                    outcome_frame, len(outcome_frame)
                ):
                    outcome_status = "corporate_action"
                else:
                    outcome_status = "realized"
                actual_signal, actual_return = classify_return(
                    actual_close, reference_close, horizon
                )
                actual_return_pct = float(actual_return)
                if predicted:
                    prediction_error_pct = (actual_close - predicted) / predicted * 100.0
                if outcome_status == "realized":
                    direction_correct = actual_signal == signal

        row_warnings: list[str] = []
        if ood:
            row_warnings.append(
                f"harga acuan {z:.2f} simpangan baku dari rata-rata data latih, "
                "di luar sebaran yang dikenal model"
            )

        rows.append(
            HorizonSignal(
                symbol=symbol,
                horizon_days=horizon,
                data_as_of=reference_date,
                target_date=projected,
                reference_close=reference_close,
                predicted_price=predicted,
                return_pct=float(change_pct),
                threshold_pct=config.RETURN_THRESHOLDS[horizon] * 100.0,
                signal=signal,
                ood_z=float(z),
                ood_flag=bool(ood),
                warnings="; ".join(row_warnings) or None,
                model_artifact=artifact_filename(artifact_path),
                model_version_id=version_id,
                actual_close=actual_close,
                actual_date=actual_date,
                actual_return_pct=actual_return_pct,
                actual_signal=actual_signal,
                prediction_error_pct=prediction_error_pct,
                direction_correct=direction_correct,
                outcome_status=outcome_status,
                outcome_approximate=outcome_approximate,
            )
        )

    if not rows:
        raise HistoricalDateError(
            f"Tidak ada horizon yang bisa dihitung pada {format_date_id(reference_date)}."
        )

    realized_rows = [row for row in rows if row.outcome_status == "realized"]
    errors = [
        abs(row.prediction_error_pct)
        for row in realized_rows
        if row.prediction_error_pct is not None
    ]
    scorecard = Scorecard(
        realized=len(realized_rows),
        pending=sum(1 for row in rows if row.outcome_status == "pending"),
        no_price=sum(1 for row in rows if row.outcome_status == "no_price"),
        corporate_action=sum(
            1 for row in rows if row.outcome_status == "corporate_action"
        ),
        direction_correct=sum(
            1 for row in realized_rows if row.direction_correct is True
        ),
        direction_total=len(realized_rows),
        mean_abs_error_pct=fmean(errors) if errors else None,
    )

    return HistoricalSignals(
        symbol=symbol,
        reference_date=reference_date,
        reference_close=reference_close,
        first_price_date=first_price_date,
        last_price_date=last_price_date,
        earliest_reference_date=earliest,
        first_usable_reference_date=usable,
        scorecard=scorecard,
        signals=rows,
        warnings=warnings,
    )
