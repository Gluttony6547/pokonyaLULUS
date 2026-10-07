# Prog5 PRD: IDX stock signal desk

Status: implemented, verified locally, and prepared for production deployment, 2026-10-04. Companion documents:
[NOTE.md](NOTE.md) records the engineering decisions, [REPORT.md](REPORT.md)
records only what was run and what broke.

## Problem

The lecturer's research artifact is a set of 150 Keras price models plus
replication CSVs under `CODE/`. Prog5 already turns those into a stored,
read-only prediction service (SQLite plus a FastAPI API), but the only way to
see a prediction was to read JSON in `/docs` or curl. A reviewer could not
answer the product's first question in a browser: what does the model say about
this ticker, how fresh is it, and how much should I trust it?

## Users

- The lecturer or research reviewer checking one ticker and one horizon on a
  laptop or a phone.
- A future demo audience that knows nothing about the internals.

Single user, end-of-day data. Not a trading system, and the UI says so in the
footer.

## Goal

A first-time visitor opens `/app/`, picks a member of the ten research tickers
and one of the five horizons, and sees the latest stored prediction with the
context needed to judge it, honest states for everything that is missing, and
a working light/dark theme, without any new backend behavior.

## Requirements (acceptance criteria)

| # | Requirement | Verified |
| --- | --- | --- |
| R1 | Served by the same FastAPI process at `/` and `/app`, no separate server, no new endpoint | Local smoke check confirms both paths serve the same UI; the UI fetches only existing read endpoints |
| R2 | Latest prediction shows predicted price, last close, return %, signal, threshold %, `data_as_of`, model file, SHA-256, OOD z and flag | Seen on all ten tickers at T+1 plus spot checks at T+50; matches API payloads (REPORT.md section 10) |
| R3 | A freshness badge derived from `data_as_of` (Fresh <= 3 days, Older <= 10, Stale beyond) | Fresh on live data; Older and Stale exercised on a temp DB copy |
| R4 | OOD warning block when `ood_flag` is true, text explains it is a warning, not a fix | Live on ANTM, BNGA, MEDC, TLKM in the 2026-10-04 refresh; also exercised on a temp DB copy |
| R5 | Enough history to be useful: price chart (180 stored sessions), indicator chips, prediction-history table, refresh-run list | Seen on first load and after selection changes |
| R6 | Honest empty state for a research ticker with no stored rows, naming the exact refresh command | Verified on TLKM before it was populated (REPORT.md section 4) |
| R7 | Loading, empty, and error states everywhere data appears, and a retry that works | Error state raised by an empty DB (API 500) while static files served; retry recovered after restoring the DB |
| R8 | Selection is shareable: ticker and horizon in the URL | `?symbol=BMRI&horizon=50` loads that view directly |
| R9 | Light and dark themes, both WCAG AA, toggle persists | Toggle both ways; 23 contrast pairs pass AA in both themes |
| R10 | Phone layout at ~375px: no horizontal overflow, no clipped text, 44px tap targets | Measured: no overflow, all controls 44px, tables scroll inside their panel |
| R11 | Keyboard reachable and operable with a visible focus ring | Tab walks every control; Enter activates; skip link jumps to #main |
| R12 | No fabricated numbers, testimonials, or claims; every displayed number comes from the DB or the artifacts | All figures trace to `/api/v1` payloads; footer states the source and the not-advice caveat |
| R13 | Unattended refresh on a configurable schedule, safe against overlapping and interrupted runs, with configurable retries, runnable on Windows without Docker | Implemented; live trigger produced run #6 `kind=scheduled` with unchanged row counts, lock refused a second writer, and tests cover due time, retries, lock, and interruption (REPORT.md section 11) |
| R14 | PostgreSQL/Neon persistence for deployment; keep local SQLite for development | SQLAlchemy selects Neon from `DATABASE_URL`; Prog5 tables use a `prog5_` prefix to coexist with the existing application; snapshot import is idempotent |
| R15 | Deployment image includes only the 50 LSTM models and research data required to reproduce the advertised model outputs | All 50 LSTM SHA-256 digests match the CODE source; GRU/RNN models, training workbooks, notebooks, and raw data are not runtime dependencies |
| R16 | The deployed database keeps receiving new closes on IDX trading days without a manual CLI run | Both writers are live: the Actions schedule completed a scheduled run on 2026-10-06 with the `DATABASE_URL` secret present, and the operator host's Task Scheduler tasks catch up any slot the runner misses (REPORT.md sections 13 and 16) |

## Data contract (existing endpoints only)

`/api/v1/health`, `/api/v1/stocks`, `/api/v1/runs`, `/api/v1/prices/{symbol}`,
`/api/v1/predictions/latest/{symbol}`,
`/api/v1/predictions/{symbol}?horizon_days=&limit=`. The UI writes nothing and
there is no second data path.

## Non-goals

- No refresh trigger, editor, or login in the browser. Writes stay in
  `python -m prog5.cli refresh`.
- No intraday data, sentiment, or live streaming.
- No Docker; the scheduler runs as a Windows console process or a Task Scheduler task (NOTE.md).
- No prediction confidence score; the artifacts do not contain one.

## Constraints carried from the research artifacts

- Only the price-regression models exist as artifacts, so the paper's ensemble
  accuracy cannot be served.
- Models are anchored to 2018-2023 data; the OOD flag is a warning, not a fix.
- Yahoo returns raw prices, so a horizon whose window contains a corporate
  action is skipped rather than predicted.

## Open follow-ups

- Coverage is complete as of 2026-10-04: all ten tickers and all five horizons are stored (REPORT.md section 10).
- Add browser-level tests (currently one static-serving pytest, the rest are
  manual browser checks recorded in REPORT.md).
- Scheduler is implemented, installed as "Prog5 daily refresh" (weekdays 17:35 and 21:05, REPORT.md section 13), and proven; the Actions `DATABASE_URL` secret and the operator host's `PROG5_DATABASE_URL` are both in place, so the freshness badge tracks real closes.
- Production deployment must have the Neon `DATABASE_URL` set and the initial Prog5 snapshot imported; new Vercel instances cannot rely on local disk persistence.
- `GET /api/v1/health` reports `last_successful_refresh`, the newest window that finished storing predictions. It answers "when was the data last refreshed", which a run's `started_at` cannot: a run can start and then fail.
