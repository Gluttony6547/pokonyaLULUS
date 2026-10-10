# Prog6 — session-relative continuation desk

Recorded structure (see `PRD.md` for the design rationale):

```
Prog6/prog6/
  history.py    # closes -> lagged-return features + forward labels (pure)
  policies.py   # momentum_5, momentum_20, ridge_l5_a1 (pure)
  backtest.py   # walk-forward fit/score slide, hit/MAE/MAPE (pure)
  calendar.py   # imports Prog5's holiday-aware walk; one calendar, two packages
  storage.py    # prog6_policies + prog6_predictions on the Prog5 database
  refresh.py    # the only writer: fit, rank, predict, upsert
  api.py        # read-only FastAPI + static mount
  static/index.html
Prog6/tests/   # 16 engine tests, no network, no DB
Prog6/scripts/
  refresh_local.py  # manual refresh against the configured DATABASE_URL
  smoke_test.py     # throwaway-SQLite pipeline check; never touches Neon
```

Data flow: Prog5's refresh pipeline fills `prog5_stock_prices` ->
`refresh.py` reads those closes (no network) -> fits/ranks policies ->
writes `prog6_predictions` with the LSTM delta -> `api.py` serves them.

## Run

```bash
python scripts/refresh_local.py          # writes to the configured DATABASE_URL
uvicorn prog6.api:app --port 8001        # PYTHONPATH must include Prog5/ and Prog6/
python scripts/smoke_test.py             # offline check, never touches Neon
```

Tests: `python -m pytest tests/ -q` (16 passing).
