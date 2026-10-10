"""The one writer in Prog6: fit, backtest, and store relative predictions.

No network: closes come from Prog5's already-refreshed Neon tables, and the
forming-bar guard there already trimmed intraday rows, so the newest close in
this module is always a completed session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import numpy as np

from . import history, policies as pol, storage
from .backtest import Backtest, walk_forward
from .calendar import target_date

logger = logging.getLogger(__name__)

FIT_WINDOW = 120
SCORE_WINDOW = 20
LAGS = 5
# The ten tickers Prog5 already prices; Prog6 reads them, it does not fetch.
SYMBOLS = tuple(
    part.strip().upper() for part in "ADRO,ANTM,BMRI,BNGA,EXCL,INCO,INKP,MEDC,PGAS,TLKM".split(",")
)


@dataclass
class SymbolReport:
    symbol: str
    predictions: int = 0
    backtests: list[Backtest] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def fit_and_predict(
    closes: list[float],
    horizon: int,
    fit_window: int = FIT_WINDOW,
    score_window: int = SCORE_WINDOW,
    lags: int = LAGS,
) -> tuple[dict[str, float], dict[str, "Backtest"]]:
    """Fit every policy, pick the best by hit rate, predict the next session.

    Returns (predictions_by_policy, backtests_by_policy): predictions keyed by
    policy name, backtests keyed by the same.
    """
    frame = history.build_frame(
        dates=[None] * len(closes),
        closes=closes,
        horizon=horizon,
        lags=lags,
    )
    backtests: dict[str, Backtest] = {}
    predictions: dict[str, float] = {}
    last_feature = history.last_feature_vector(closes, lags=lags)
    for template in pol.policies_for((horizon,), lags=lags)[horizon]:
        backtest = walk_forward(
            frame, template, fit_window=fit_window, score_window=score_window
        )
        backtests[template.name] = backtest
        fitted = type(template)(**_args(template))
        fitted.fit(frame.features, frame.labels)
        predictions[template.name] = fitted.predict(last_feature)
    return predictions, backtests


def _args(template) -> dict:
    if hasattr(template, "lags"):
        return {"lags": template.lags, "alpha": template.alpha}
    if hasattr(template, "k"):
        return {"k": template.k}
    return {}


def refresh(symbols: tuple[str, ...], horizons: tuple[int, ...]) -> list[SymbolReport]:
    """Run the full Prog6 pipeline against the configured database and write rows."""
    storage.ensure_tables()
    reports: list[SymbolReport] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with storage.session() as session:
        for symbol in symbols:
            report = SymbolReport(symbol=symbol)
            dates, closes = storage.load_closes(symbol, session)
            if len(closes) < LAGS + max(horizons) + 1:
                report.errors.append(
                    f"{symbol}: not enough stored closes ({len(closes)}) for horizons {horizons}"
                )
                reports.append(report)
                continue
            data_as_of = dates[-1]

            for horizon in horizons:
                try:
                    policy_predictions, backtests = fit_and_predict(closes, horizon)
                except ValueError as error:
                    report.errors.append(f"{symbol} T{horizon}: {error}")
                    continue

                # Best policy: highest hit rate, tie broken by lower MAE.
                best_name = max(
                    backtests,
                    key=lambda name: (
                        backtests[name].metrics.hit_rate,
                        -backtests[name].metrics.mae,
                    ),
                )
                best_backtest = backtests[best_name]
                report.backtests.append(best_backtest)

                for name, backtest in backtests.items():
                    upsert_policy_result(session, symbol, horizon, name, backtest, now)

                relative_return = policy_predictions[best_name]
                last_close = closes[-1]
                expected_close = last_close * float(np.exp(relative_return))
                lstm_price, lstm_sha = storage.latest_lstm_prediction(symbol, horizon, session)
                lstm_delta = (
                    (expected_close - lstm_price) / lstm_price if lstm_price else None
                )
                upsert_prediction(
                    session,
                    symbol=symbol,
                    horizon=horizon,
                    data_as_of=data_as_of,
                    relative_return=relative_return,
                    expected_close=expected_close,
                    last_close=last_close,
                    best_policy=best_name,
                    lstm_predicted_price=lstm_price,
                    lstm_delta_pct=lstm_delta,
                    model_sha256=lstm_sha,
                    now=now,
                )
                report.predictions += 1
            reports.append(report)
    return reports


def upsert_policy_result(session, symbol, horizon, name, backtest: Backtest, now) -> None:
    from .storage import PolicyResult
    from sqlalchemy import delete

    session.execute(
        delete(PolicyResult).where(
            PolicyResult.symbol == symbol,
            PolicyResult.horizon_days == horizon,
            PolicyResult.policy == name,
        )
    )
    session.add(
        PolicyResult(
            symbol=symbol,
            horizon_days=horizon,
            policy=name,
            hit_rate=backtest.metrics.hit_rate,
            mae=backtest.metrics.mae,
            mape=backtest.metrics.mape,
            backtest_rows=backtest.metrics.rows,
            fit_window=FIT_WINDOW,
            score_window=SCORE_WINDOW,
            computed_at=now,
        )
    )


def upsert_prediction(
    session,
    symbol: str,
    horizon: int,
    data_as_of: date,
    relative_return: float,
    expected_close: float,
    last_close: float,
    best_policy: str,
    lstm_predicted_price: float | None,
    lstm_delta_pct: float | None,
    model_sha256: str | None,
    now,
) -> None:
    from .storage import Prediction
    from sqlalchemy import delete

    session.execute(
        delete(Prediction).where(
            Prediction.symbol == symbol,
            Prediction.horizon_days == horizon,
            Prediction.data_as_of == data_as_of,
        )
    )
    session.add(
        Prediction(
            symbol=symbol,
            horizon_days=horizon,
            data_as_of=data_as_of,
            target_date=target_date(data_as_of, horizon),
            predicted_relative_return=relative_return,
            expected_close=expected_close,
            last_close=last_close,
            best_policy=best_policy,
            lstm_predicted_price=lstm_predicted_price,
            lstm_delta_pct=lstm_delta_pct,
            model_sha256=model_sha256,
            computed_at=now,
        )
    )
