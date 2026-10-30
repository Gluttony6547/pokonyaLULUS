# Sinyal IDX

Dashboard and API that turn the saved LSTM artifacts of the reference research
into buy, hold, and sell signals for ten IDX tickers at horizons of 1, 5, 10, 20,
and 50 trading sessions. Prices refresh automatically on IDX trading days after
the 16:00 WIB close. The service is decision support: it does not place orders
and its output is not investment advice.

Signals are computed from the 50 saved `LSTM_<SYMBOL>_Target_<H>.h5` artifacts,
the same files the research notebooks produced. Each signal records the data
date it was made from and the model version behind it, so any row on the
dashboard can be traced back to a file and a session. The input date records the
last complete price session; the target date is counted from the refresh date in
Asia/Jakarta, skipping weekends and recorded IDX holidays.

## What the dashboard offers

- Latest buy, hold, or sell label per horizon, with a threshold-based price
  zone derived from that signal's reference close, the threshold, the target
  date, and the model version. BUY and SELL show the inclusive outer bound;
  HOLD shows the two bounds as a price range. These zones explain the signal
  threshold, not model confidence or a guaranteed price.
- Intraday quote and timestamp for the selected stock during market hours. The
  quote is for monitoring; model signals continue to use completed daily closes.
- Out-of-distribution and corporate-action warnings attached to the signal that
  triggered them, plus a note when a target date crosses a calendar year the
  holiday table does not cover.
- Price chart, indicator context (SMA, RSI, MACD, Bollinger), signal history per
  horizon, data update log, and model versions with their holdout metrics.
- Retraining on the stored price history, queued as a job with visible status.
- Light and dark themes, keyboard navigation, and explicit empty, loading, and
  error states.

## Requirements

- Python 3.12 or newer.
- PostgreSQL 15 or newer for a shared deployment. Without a database URL the
  service falls back to a local SQLite file, which is what the tests use.
- The model artifacts and the reference series, both in this repository:
  `models/<SYMBOL>/` and `data/research/`.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-torch-cpu.txt
pip install -r requirements-dev.txt
python -m idx_signal.cli seed        # create tables and seed tickers and holidays
python -m idx_signal.cli serve --port 8000
```

Open `http://127.0.0.1:8000` for the dashboard, `/docs` for the API schema, and
`/api/v1/health` for the machine-readable status. Copy `.env.example` to `.env`
to point it at Postgres or to change the schedule; `.env` is gitignored.

Fill the database with prices and signals with a manual update, either from the
button on the dashboard or:

```bash
python -m idx_signal.cli refresh
```

## Postgres

Set `IDX_DATABASE_URL` (or `DATABASE_URL`) to any Postgres 15+ connection
string. Neon's pooled URL and Supabase's session pooler URL both work; the
driver is configured without client-side prepared statements, which is what
transaction-mode poolers need.

Tables are created additively at startup and nothing existing is altered, so a
fresh or empty database needs no setup: startup seeds the ten tickers and the
holiday calendar, and the first refresh registers one model version per ticker
and horizon and writes its signals, computing holdout metrics from
`data/research/Result Price Prediction/`.

One caveat, because it is easy to hit. The app uses the data model's plain table
names (`stocks`, `predictions`, and so on). If the database already contains a
table with one of those names but different columns, creation is skipped for
that table and the first query fails on the missing column. This is what
happens when an earlier version of the project used the same names. Point the
service at its own namespace instead of migrating the old data:

```bash
IDX_DATABASE_SCHEMA=sinyal python -m idx_signal.cli refresh
```

The tables then live at `sinyal.stocks`, `sinyal.predictions`, and so on, with
the same names the design document specifies, and no existing table is read or
changed. Leave `IDX_DATABASE_SCHEMA` unset on a dedicated database and the
tables go in the connection's default schema.

## Scheduled updates

The schedule is wall-clock WIB, never the host's local time, and it decides
*when a run is due*: the actual trigger is an external scheduler. Two slots per
trading day are configured by default, `16:05` and `18:00` WIB, so the second
run can overwrite a straggling feed with the provider's settled end-of-day
values. `IDX_SCHEDULE_TIMES`, `IDX_SCHEDULE_DAYS`, and `IDX_SCHEDULE_SYMBOLS`
adjust that.

On Vercel the trigger is the cron pair in `vercel.json`:

| vercel.json schedule | UTC | WIB | Serves the slot |
|----------------------|-----|-----|-----------------|
| `5 10 * * 1-5`       | 10:05 | 17:05 | 16:05 |
| `5 12 * * 1-5`       | 12:05 | 19:05 | 18:00 |

Vercel fires cron jobs within the scheduled hour rather than at the exact
minute on the Hobby plan, so both entries sit an hour after the slot they serve
and the due check still finds the slot. Vercel sends
`Authorization: Bearer $CRON_SECRET` when that environment variable exists;
without it the endpoint refuses to run, so a deployment cannot be triggered by
a stranger.

Anywhere else, run the same due check in a loop:

```bash
python -m idx_signal.cli schedule
```

Both paths call one refresh pipeline, so the automated and manual updates write
the same rows, and the update log records which of them ran.

## Deploy

### Vercel, as a container service

`Dockerfile.vercel` at the repository root is what Vercel's container runtime
auto-detects; the image installs CPU-only torch, the application, the 50
artifacts, and the reference series. Import the repository, keep the framework
preset on "Other", and set:

| Variable | Value |
|----------|-------|
| `IDX_DATABASE_URL` | your Postgres connection string |
| `IDX_DATABASE_SCHEMA` | a schema name, when that database already holds tables using the same names |
| `CRON_SECRET` | a long random string |

Then deploy. The cron entries in `vercel.json` start firing on the first
production deployment. Container instances scale down after a few idle minutes,
which is why the schedule is driven by cron and not by the in-process loop; the
dashboard's own polling keeps an instance warm while somebody is looking at it.

Retraining writes its artifact to the container filesystem, which is ephemeral
on this platform. A retrained version therefore lives as long as the instance
that trained it, and a candidate is never served until somebody activates it.
On a host with a persistent volume (`IDX_TRAINING_DIR`) retrained artifacts
survive.

### Any Docker host

```bash
docker build -t idx-signal .
docker run --rm -p 8000:80 -e IDX_DATABASE_URL=... -e CRON_SECRET=... idx-signal
```

The image listens on `PORT` (default 80), ships `models/` and `data/research/`
at the paths `IDX_ARTIFACT_DIR` and `IDX_RESEARCH_DATA_DIR` point to, and needs
no volume for the reference path.

## Verification

```bash
python -m pytest -q                     # unit and integration tests
python -m idx_signal.cli inventory      # artifacts resolvable per ticker
python -m idx_signal.cli verify         # serving path vs the committed research output
```

`verify` is the important one: it rebuilds the research notebook's sliding
windows, runs them through the same scalers and artifacts the service serves,
and compares the result with the committed predictions. `REPORT.md` holds the
recorded output and the click-through of the dashboard.

## Layout

| Path | Contents |
|------|----------|
| `idx_signal/` | application package: config, storage, prediction, refresh, scheduler, training, API |
| `idx_signal/static/` | dashboard: one HTML page, one stylesheet, one script, no build step |
| `models/<SYMBOL>/` | the 50 saved LSTM artifacts |
| `data/research/` | fusion series, labelled series, and the committed research predictions |
| `tests/` | pytest suite, network calls replaced by fixtures |
| `CODE/` | the research checkout the artifacts came from (not part of the image) |
| `DESIGN.md` | the visual direction the dashboard follows |
| `PRD_UCD_PDM_Prediksi_Sinyal_Saham_IDX.md` | product, use case, and data model design |

## Provenance and limits

The artifacts were trained on data ending in 2023, and the repository's `verify`
command is what ties them to the published research output. Out-of-distribution
and corporate-action checks are warnings: they do not correct regime drift, and
a signal computed from a stale input window is still displayed as a signal.
Predictions are only ever made from data available on or before the recorded
data date.

The research also trained on 19 features including news sentiment. This service
uses the closing-price window the artifacts expect and recomputes the indicators
for context only, so it is the price path of the research, not the sentiment
path. Holdout metrics shown per model version come from the research test split
(`source: reference holdout`) or from a retraining run's chronological holdout
(`source: retrained, chronological holdout`), whichever produced that version.
