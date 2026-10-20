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
    nth_price_date,
    price_date_range,
    price_frame_until,
)
from .trading_calendar import crosses_unknown_year, load_holidays, target_date

MAX_REFERENCE_AGE_YEARS = 10


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


@dataclass(frozen=True)
class HistoricalSignals:
    symbol: str
    reference_date: date
    reference_close: float
    first_price_date: date
    last_price_date: date
    earliest_reference_date: date
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
    if reference_date > latest:
        raise HistoricalDateError(
            f"Tanggal {reference_date} melewati harga terbaru {latest}. "
            f"Pilih tanggal antara {earliest} dan {latest}."
        )
    if reference_date < earliest:
        raise HistoricalDateError(
            f"Tanggal {reference_date} di luar rentang data. "
            f"Pilih tanggal antara {earliest} dan {latest}."
        )

    needed = max(horizon_list)
    frame = price_frame_until(session, symbol, reference_date, limit=needed)
    if frame.empty or frame.iloc[-1]["date"] != reference_date:
        previous = None if frame.empty else frame.iloc[-1]["date"]
        hint = f" Sesi terakhir sebelumnya adalah {previous}." if previous else ""
        raise HistoricalDateError(
            f"Tidak ada harga penutupan pada {reference_date}.{hint} "
            "Pilih tanggal sesi bursa yang punya harga."
        )
    if len(frame) < needed:
        first_fit = nth_price_date(session, symbol, needed)
        hint = f" Tanggal acuan paling awal yang cukup adalah {first_fit}." if first_fit else ""
        raise HistoricalDateError(
            f"Sampai {reference_date} hanya ada {len(frame)} sesi harga, "
            f"model butuh {needed} sesi masukan.{hint}"
        )

    holidays, known_years = load_holidays(session)
    reference_close = float(frame.iloc[-1]["close"])
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
        predicted = predict_price(artifact_path, horizon, frame["close"], scalers)
        signal, change_pct = classify_return(predicted, reference_close, horizon)
        z = out_of_distribution_z(reference_close, scalers.input_mean, scalers.input_scale)
        ood = is_out_of_distribution(z)
        projected = target_date(reference_date, horizon, holidays)

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
                predicted_price=float(predicted),
                return_pct=float(change_pct),
                threshold_pct=config.RETURN_THRESHOLDS[horizon] * 100.0,
                signal=signal,
                ood_z=float(z),
                ood_flag=bool(ood),
                warnings="; ".join(row_warnings) or None,
                model_artifact=artifact_filename(artifact_path),
                model_version_id=version_id,
            )
        )

    if not rows:
        raise HistoricalDateError(
            f"Tidak ada horizon yang bisa dihitung pada {reference_date}."
        )

    return HistoricalSignals(
        symbol=symbol,
        reference_date=reference_date,
        reference_close=reference_close,
        first_price_date=first_price_date,
        last_price_date=last_price_date,
        earliest_reference_date=earliest,
        signals=rows,
        warnings=warnings,
    )
