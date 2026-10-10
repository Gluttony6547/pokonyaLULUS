# Prog6 — Session-Relative Continuation Research (PRD)

**Status:** implemented in this directory.
**Commit discipline:** all Prog6 code lives under `Prog6/` on `pokonya-main`,
pushed with the same `pokonya` remote as Prog5; no pull request opens.

## Problem

Prog5's deployed dashboard serves the lecturer's fixed LSTM artifacts. Those
models were trained on a 2018 to 2023 window and can never be retrained by the
pipeline, so they are structurally out-of-distribution for 2026 prices: every
prediction carries an "unreliable, out of range" warning, and the warning is
about the model, not about the market.

## Thesis

The price level drifts, but session-to-session continuation structure is much
more stable. So predict relative moves, not absolute prices:

    r_t+H = (close at T+H / close today) - 1

Fit simple baselines (ridge on lagged returns, and a 5/20-day momentum mean)
on those relative returns from the last rolling window of sessions, re-fitting
on every refresh. That turns an out-of-distribution 5000-Idr close into an
in-distribution 1.04 percent continuation, which is exactly the kind of input
a model can extrapolate from safely. No retraining infrastructure is required,
because the fit happens inside each refresh and is never persisted.

## Deliverable

`prog6` — a self-contained FastAPI package with:

1. **Engine library** (pure, network-free, deterministic):
   - `calendar.py` — re-exports Prog5's IDX trading-day walk (2026/2027
     holiday tables), duplicated only in import wiring, not in rules.
   - `history.py` — closes -> a per-session lagged-return feature matrix,
     plus H-day-ahead relative returns as labels.
   - `policies.py` — the fit/predict pairs: `momentum-policy` (5-day and
     20-day mean continuation) and `ridge-policy` (ridge on the lag matrix).
   - `backtest.py` — walk-forward backtest: fit on window W, score next K,
     slide, aggregate hit rate, MAE, and MAPE by horizon.
2. **`refresh` path** — pulls closes from the Prog5-priced Neon tables
   directly using the `DATABASE_URL` and writes two tables:
   - `prog6_policies` — one fitted policy per (symbol, horizon) with its
     backtest metrics.
   - `prog6_predictions` — one row per (symbol, horizon, session): relative
     predicted return, expected price, and the delta versus Prog5's LSTM
     prediction on the same session (so the two dashboards can be checked
     against each other).
3. **Read-only API** — mirrors Prog5's shape: `/health`, `/stocks`,
   `/policies/{symbol}`, `/predictions/latest/{symbol}`. Served by the same
   uvicorn launcher style as Prog5's `prog5 serve`, same static mount.
4. **Static dashboard** — a single `index.html` mounted at `/` that reads only
   the endpoints above. It shows predicted relative return per horizon and
   the delta against the LSTM dashboard. No new data path.
5. **Tests** — pure unit tests on the engine: policy fit, calendar walk,
   backtest aggregation. No network, no database. The Neon path is exercised
   only by the CLI itself, not by tests.

## Architecture

```
Prog6/
  prog6/                # the package
    __init__.py
    calendar.py         # re-exports prog5.trading_calendar helpers
    history.py          # session-relative features and labels
    policies.py         # momentum + ridge policy objects
    backtest.py         # walk-forward evaluation
    storage.py          # table definitions (prog6_policies, prog6_predictions)
    refresh.py          # read closes, fit, score, write results
    api.py              # FastAPI read-only app + static mount
    static/index.html   # the dashboard
  tests/                # engine unit tests (pytest)
  scripts/refresh_local.py  # manual trigger against the configured DATABASE_URL
  PRD.md                # this document
```

## Out of scope for v1

- Session-relative LSTM (ridge/momentum are the v1 baselines) — deferred until
  the baselines prove distribution-stable in the backtest.
- Any retraining pathway for Prog5's LSTM artifacts — that is Prog5-scope work.
- Any new visual language for the static page — it reuses Prog5's existing
  layout, palette, and terminology instead of inventing a new one.
- The `(approx.)` target-date label on the Prog5 dashboard — separate slice,
  belongs to Prog5.

## Success criteria

- Engine backtest on synthetic trending data recovers the trend direction with
  hit rate > 50 percent and MAE < 2 percent for H=1 (sanity floor).
- All engine tests pass with no network and no database writes.
- `refresh_local.py` writes rows for all ten Prog5 symbols and all five
  horizons when a `DATABASE_URL` is configured.
