# Prog5 build note

Read this before touching the package. It records what was decided, what was
verified by running, and what the lecturer's artifacts cannot do.

## Stack decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Language/runtime | Python 3.12+ (developed on 3.14) | The model artifacts are Keras 3 H5 files; Python is the only practical host. |
| Web framework | FastAPI + uvicorn | Typed response models, dependency injection for sessions, OpenAPI docs for free. |
| Persistence | PostgreSQL/Neon by default, reached either from the environment or from a gitignored `Prog5/.env`; SQLite only as a fallback and for tests | Data outlives any instance: the deployed container is read-only and every writer targets the same Postgres. Prog5 tables are prefixed to coexist with the earlier app. |
| Inference placement | Off the request path. `python -m prog5.cli refresh` writes rows; the API only reads them | The measured cold start of this model under torch is ~13 s (from the earlier Prog3 validation), which is unacceptable per-request. Predictions are EOD data anyway. |
| Keras backend | `torch`, set in `prog5/__init__.py` before keras imports | TensorFlow is not installed; the artifacts load and run under torch, verified below. |
| Market data | Yahoo Finance (`.JK` tickers), `auto_adjust=False`, 5-year window | Free, and it returned data through the last trading day (2026-10-02) during the build. |
| Indicators | Reimplemented in pandas to match TA-Lib | Avoids the native TA-Lib build; parity is asserted against the committed research columns. |
| Artifact access | Read directly from `CODE/Price Prediction Model` locally; use `PROG5_ARTIFACT_DIR` in deployment | The repository already contains the 50 LSTM artifacts byte-identical to CODE; deployment packages only those required by the service. |
| Browser UI | Plain HTML/CSS/JS in `prog5/static/`, served by the same FastAPI process at `/` and `/app` | No separate asset build or data path; the public root now opens the dashboard. |
| Scheduler | Local process or Windows Task Scheduler; no scheduler runs in Vercel | Vercel filesystems are ephemeral. A single writer runs on one maintained host; distributed locks remain out of scope. |
| Container | CPU-only PyTorch image starts `prog5.api:app` | Reuses the validated inference backend and includes only runtime code, models, and research inputs. |

## Model interface, as reproduced

For `LSTM_{SYM}_Target_{H}.h5` where H is one of 1, 5, 10, 20, 50:

- Architecture: Keras 3.4.1 `Sequential`, `Input(shape=(H, 1))`, three LSTM(96)
  layers with Dropout(0.2), then Dense(1); MSE loss, Adam(1e-3); 185,953 params.
- Input: one window of exactly `H` consecutive closes (a 1-day model takes a
  single close), each value scaled by the input `StandardScaler`.
- Scaler reconstruction (the notebooks never saved the scalers):
  - Input scaler: `StandardScaler` fitted on
    `train_test_split(fusion.close[50:], test_size=0.2, random_state=0)[0]`
    (975 rows of 1,219). ADRO: mean 1889.948717948718, scale 884.8597730052891.
  - Target scaler: fitted on the same split of `labelled.close.shift(-H).iloc[50:-50]`
    (975 rows of 1,219). ADRO T50: mean 1926.548717948718, scale 893.3022065583102.
- Output: a single scaled value; the price is `scaler_out.inverse_transform` of it.
- Signal rule (from the notebook, not the paper's neat equation): buy when
  `pred > close` and `return >= threshold`; sell when `pred < close` and
  `abs(return) >= threshold`; otherwise hold. Thresholds: 1.5% / 3% / 6% / 9% / 11%.
- OOD flag: `|z| > 2`, where `z = (last_close - input_scaler.mean) / scale`.
  The 2026-10-04 refresh flagged ANTM (+2.13), BNGA (+3.08), MEDC (+2.93), and
  TLKM (-3.30); ADRO, BMRI, EXCL, INCO, INKP, and PGAS sit inside range.

### What was verified by running

- `python -m prog5.cli verify --symbols ADRO --horizons 1,5,10,20,50`: all five
  horizons reproduce the committed `CODE/Result Price Prediction` CSVs to a
  maximum absolute difference of 0.0016 IDR (float noise across backends).
- `python -m prog5.cli refresh --symbols ADRO --horizons 1,5,10,20,50` and the
  same for BMRI: 1,203 / 1,204 price rows stored, 2,407 indicator rows, 10
  prediction rows keyed on `(symbol, horizon, data_as_of=2026-10-02)`.
- Indicators: SMA exact, EMA/RSI/Bollinger at float precision, MACD at float
  precision after its seed transient (the recursion is identical; only the
  initial seed differs from TA-Lib's, and the difference decays to zero within
  the first ~100 bars). Asserted in `tests/test_indicators.py`.
- The read-only API was run under uvicorn and exercised with curl: health,
  stocks, prices, latest predictions, filtered predictions, runs; unknown
  symbols return 404, unknown horizons return 422.
- Coverage: refresh run #3 stored the eight missing tickers and run #4 re-ran
  all ten in one pass, giving 12,038 price rows, 12,038 indicator rows, and 50
  predictions (ten tickers x five horizons) with 2026-10-02 closes. Stored row
  counts were identical before and after run #4, so the upserts are idempotent.
  No horizon was skipped or failed; the corporate-action skip branch did not
  trigger because no ticker has a >30% overnight move in its five-year window
  (the branch itself is covered by `tests/test_refresh_pipeline.py` and
  `tests/test_market_data.py`).

## Browser UI decisions (antislop)

antislop mode: `during` (session default). No saved preference exists at
`%APPDATA%\antislop\settings.json` and no explicit choice was given, so the
default was resolved by applying the rules while writing: this is a UI build
pass, and applying the filter during generation prevents slop instead of
auditing for it afterwards. The mode is announced in-session, not persisted.

Design Read (declared before building): reading this as a research data
dashboard for a single analyst, in a calm editorial instrument-panel style,
dial ENERGY 1 / RHYTHM 2 / MOTION 1. No `DESIGN.md` exists; the direction comes
from the brief itself (research output, honest warnings, dark mode asked for).

Every major decision, one line each:

| Decision | Reason |
| --- | --- |
| Neutral paper and surface, ink, one deep-teal accent | The accent marks the action color; status hues stay semantic instead of competing. |
| Green, rust, and slate used only on signals and deltas | Color carries meaning in a trading surface; using it elsewhere would dilute the signal. |
| System UI font, mono only for model files and hashes | Native feel for analysis chrome; mono marks machine-exact values. |
| One prediction card, the only element with a shadow | One focal point per screen; the card is the answer to the visitor's first question. |
| Light default plus a working dark toggle, both checked against WCAG AA | R-21: no forced dark default without a product reason; the toggle is real and persists in localStorage. |
| Chart is a hand-built SVG polyline, no library | No build step and no dependency for one sparkline-plus; it scales to its container and has an accessible name. |
| Wide tables scroll inside their panel on phones | R-03: the page body never overflows while the full table stays readable. |
| Empty states name the exact refresh command | Honest next step for an unrefreshed ticker, no fake filler. |

Verified by running (2026-10-04, uvicorn on 127.0.0.1:8123):

- First load as a visitor: defaulted to ADRO T+1 and rendered 2,536.85 IDR
  predicted, last close 2,500, hold, 1.5% threshold, data as of 02 Oct 2026
  ("2 days old", Fresh badge), model SHA-256 prefix, 180-session chart, seven
  indicator chips, one prediction-history row, and both refresh runs.
- BMRI T+50: buy, +24.71%, 11% threshold, 5,025.72 IDR; matches the API payload.
- TLKM: honest empty state naming `python -m prog5.cli refresh --symbols TLKM`.
- Freshness "Older" and "Stale" plus the OOD warning block were exercised on a
  temporary copy of the DB (flagged row: z 2.61, data as of 2026-09-15); live
  rows are all fresh and unflagged, so those paths are verified that way only.
- Keyboard: Tab order is skip link, theme toggle, ticker, five horizons, footer
  links; Enter activated T+20; Enter on the skip link jumped to #main; the
  focus ring is visible on every stop.
- 375px and 1280px both measure with no horizontal overflow, and every control
  is at least 44px tall.
- Error state: with the real DB swapped for an empty one, boot shows
  role=alert plus a 44px Try again; retrying after restoring the DB recovered
  the full dashboard. This found one real bug (retry called `load()` before a
  symbol existed) which now re-runs `boot()`.
- Both themes toggle and persist; 23 color pairs checked with antislop-human's
  `contrast-check.py` pass WCAG AA (ratios 5.94:1 to 16.57:1).

## Unattended refresh (scheduler)

The dashboard promise (data as of the last close) only holds if something
refreshes it. `prog5/scheduler.py` does that without a second data path: it
calls the same `refresh()` the CLI uses, so the safety rules below apply to
both entry points.

How it decides to run:

- Due when a configured local time has passed today (or yesterday, so a host
  that was off catches up) and no completed run finished at or after that slot.
- Days default to weekdays, so weekends stay quiet unless configured.
- One refresh covers all ten tickers and all five horizons.

Safety:

- Single writer: `refresh()` holds a lock file next to the database
  (`<db>.lock`, created with `O_CREAT|O_EXCL`). A second caller gets
  `RefreshInProgress` and exits without writing; the CLI prints
  `refresh skipped` and returns 2, the scheduler reports `locked` and keeps
  polling. A lock older than `PROG5_SCHEDULE_STALE_LOCK_SECONDS` is treated as
  abandoned and replaced once.
- Interrupted runs: every refresh start marks `running` rows older than
  `PROG5_SCHEDULE_STALE_RUN_SECONDS` as `failed` with an `interrupted` note, so
  a killed process cannot leave a phantom run in the UI.
- Retries: a failed attempt is retried `PROG5_SCHEDULE_RETRY_ATTEMPTS` times
  with `PROG5_SCHEDULE_RETRY_DELAY_SECONDS` between attempts; the daemon never
  dies on a bad tick (it logs and continues).
- Single-host guarantee: the lock is a file on this machine. Two hosts sharing
  a database folder would need an external lock; not supported.

The lock applies only to the local scheduled writer. The Vercel service is
read-only and stores no state on its container filesystem. Initial history is
copied into Neon with `python -m prog5.cli import-snapshot`; subsequent local
refreshes use the same `DATABASE_URL` and SQLAlchemy upserts. The importer is
idempotent and repairs PostgreSQL sequences after preserving source IDs.

Settings, all read from the environment at call time:

| Env var | Default | Meaning |
| --- | --- | --- |
| `PROG5_SCHEDULE_TIMES` | `17:30,21:00` | Local HH:MM list, comma separated. Both slots run per weekday: Yahoo's EOD update usually lands by 17:30 WIB but sometimes drifts later, so the evening slot re-runs the pipeline and fills any gap. |
| `PROG5_SCHEDULE_DAYS` | `mon,tue,wed,thu,fri` | Weekday names; weekends stay quiet because IDX does not trade. |
| `PROG5_SCHEDULE_SYMBOLS` | all ten | Tickers refreshed by a scheduled run. |
| `PROG5_SCHEDULE_RETRY_ATTEMPTS` | `2` | Extra attempts after a failed run. |
| `PROG5_SCHEDULE_RETRY_DELAY_SECONDS` | `300` | Pause between attempts. |
| `PROG5_SCHEDULE_POLL_SECONDS` | `30` | Clock check interval. |
| `PROG5_SCHEDULE_STALE_LOCK_SECONDS` | `21600` | Age at which a lock file is considered abandoned. |
| `PROG5_SCHEDULE_STALE_RUN_SECONDS` | `21600` | Age at which a `running` row is considered interrupted. |

Running it on this Windows host, no Docker:

1. Foreground console: `python -m prog5.cli schedule` (leave the window open).
2. Windows Task Scheduler: a task that runs `python -m prog5.cli schedule
   --once` every 10 minutes (or at the configured times). `--once` checks the
   clock, reconciles interrupted runs, refreshes when due, prints the outcome,
   and exits 0 for not-due/locked or 1 when a run failed after retries.
   `--force` runs immediately, for manual repair.
3. Detached process (no console window), from PowerShell:
   `Start-Process python -ArgumentList '-m','prog5.cli','schedule'`. Stop it
   with Task Manager or `taskkill`.
4. One command: `Prog5\scripts\install-windows-task.cmd` registers two
   weekday tasks, "Prog5 daily refresh" at 17:35 and "Prog5 daily refresh
   evening" at 21:05, each shortly after a pipeline slot so the due check
   cannot race the trigger. Both run
   `Prog5\scripts\run-scheduled-refresh.cmd`, which does the due check, appends
   to `Prog5\data\scheduler.log`, and accepts `--force` for manual repair. The
   runner re-reads `PROG5_DATABASE_URL` from the user registry every tick, so
   `setx` takes effect without a fresh logon. The tasks run as the signed-in
   user, so they only fire while that user is logged on; a missed evening is
   recovered by the next run because every refresh fetches the full five-year
   history.

## Trading-day target dates

The artifacts predict H trading sessions ahead, but a horizon alone does not
tell a reader when the prediction lands. `prog5/trading_calendar.py` projects
the calendar date: IDX trades Monday to Friday, so `target_date(data_as_of, H)`
walks H weekdays forward and never returns a Saturday or Sunday. 2026-10-06
(Tue) + 10 sessions is 2026-10-20 (Tue), with two weekends skipped; Friday + 1
is Monday; H=0 returns the start date. Exchange holidays are not modeled
because Yahoo returns no rows for them and the freshness label already absorbs
the gap.

- `Prediction.target_date` (nullable Date) stores the projection per row.
  `db.init_db()` adds the column to existing databases with an
  `ALTER TABLE ... ADD COLUMN` when missing; fresh databases get it from
  `create_all`. Rows predating the column keep NULL and render "n/a" in the UI
  until their (symbol, horizon, data_as_of) row is refreshed again.
- The refresh report and the API expose `target_date`. The dashboard's
  prediction card shows the interval as "Output window" ("06 Oct 2026 to
  20 Oct 2026, 10 sessions (weekends skipped)") and the prediction-history
  table gained a Target column.
- The prediction upsert keys on (symbol, horizon_days, data_as_of), so a
  re-run for the same session updates the same row instead of adding one.

## Keeping the deployed database current

The Vercel deployment reads Neon, and its container seeds an empty database
once from the bundled snapshot. Nothing in the container writes new rows, so
the deployed card froze at the snapshot's 2026-10-02 closes until a writer ran
against the same Neon database. Two writers cover that now:

- GitHub Actions: `.github/workflows/prog5-refresh.yml` runs
  `python -m prog5.cli refresh` for all ten tickers across a dense weekday
  window: every 30 minutes from 17:07 to 23:37 WIB, minutes offset from the
  hour because GitHub drops queued runs most at the start of one, plus an
  08:22 WIB repair pass for an evening that was missed entirely. Each attempt
  runs `scripts/check_site_freshness.py` first: it compares the deployed site
  with Yahoo's completed sessions (before 17:30 WIB the still-forming daily
  bar does not count) and skips the model install once they agree, so a quiet
  evening costs a handful of cheap checks instead of a dozen full refreshes.
  The last step runs the same script again and fails the run when the site
  still trails Yahoo, which turns a dropped schedule into a red badge. It
  refuses to refresh when the `DATABASE_URL` repository secret is missing, so
  a misconfigured run fails loudly instead of writing to the runner's
  throwaway SQLite file. The secret is added once under Settings, Secrets and
  variables, Actions.

Live proof (2026-10-06, GitHub runner, WIB):

- A manual `workflow_dispatch` of `.github/workflows/prog5-refresh.yml` on the
  deployment repo (run 37379910888, commit `36eb986`) succeeded in 2m39s. The
  guard step "Refuse to run without the Neon connection string" passed, so the
  `DATABASE_URL` repository secret exists.
- Its log shows `DATABASE_URL: ***` in the step environment, all ten tickers
  fetched from Yahoo Finance, then `refresh run #9 status=completed` and
  `prices stored=12038 indicator rows stored=12038 predictions=50` between
  22:04:26Z and 22:05:34Z.
- The log never names the dialect, so the conclusive check is on the database
  side: the same run #9 is in Neon (`started 2026-10-05 22:04:33.419344`,
  `finished 2026-10-05 22:05:15.215378`, all ten symbols,
  `prices=12038 indicators=12038 predictions=50 warnings=10`) and
  `https://pokonya-lulus.vercel.app/api/v1/health` serves that row with
  `"storage_backend":"postgresql"`. The runner can only have written it through
  the secret, so it did not touch its throwaway SQLite file.
- The operator host: set `PROG5_DATABASE_URL` in `Prog5/.env` (or in the
  environment) and the Windows task above writes to the same Neon database
  whenever this machine is on.

Both entry points call the same `refresh()` pipeline and the same upserts, so
running both is redundant but not corrupting; the only duplicate is a run row.

Live proof (2026-10-04, Windows, WIB):

- With a fresh lock file held, `schedule --once --force` printed
  `ran=False attempts=0 reason=locked` and left the lock alone.
- A detached daemon started at 20:20:35 with the slot set to 20:26 waited, then
  logged `Scheduled slot 2026-10-04 20:26 is due`, ran refresh run #6
  (`kind=scheduled`, status completed, all ten tickers, 50 predictions) and
  logged `scheduled refresh: ran=True attempts=1 reason=refresh run #6
  completed (50 predictions)`. Row counts before and after were identical
  (12,038 / 12,038 / 50), so the upserts are idempotent.
- The first live trigger (run #5) exposed that scheduled runs were recorded as
  `kind=on_demand`; `refresh()` now takes a `kind` parameter and the scheduler
  passes `scheduled`. The default weekdays-only rule also kept a Sunday quiet
  until the test enabled all days, which is the documented behavior.

Live proof (2026-10-05, Windows, WIB):

- `Prog5\scripts\install-windows-task.cmd` registered "Prog5 daily refresh"
  (weekly, MON-FRI, 17:35) and `schtasks /run` executed it against the live
  database. The first tick exposed a real defect: `run_scheduled` queried
  `prog5_refresh_runs` before `init_db()` ran, so a database that predates the
  table rename failed with `no such table` and no run was ever scheduled. The
  fix initialises the schema before the due check and is covered by
  `tests/test_scheduler.py::test_scheduled_run_migrates_a_legacy_database_before_the_due_check`.
- The next tick logged `Scheduled slot 2026-10-05 17:30 is due` and completed
  refresh run #7 (`kind=scheduled`, all ten tickers, 50 predictions) in about
  16 seconds; a forced tick then produced run #8 and left the stored counts
  unchanged (12,048 / 12,048 / 100 before and after), so the writes are
  idempotent with the new date included.
- Served UI after the ticks: ADRO T+1 2,635.43 IDR buy, last close 2,590,
  "DATA AS OF 05 Oct 2026 today", Fresh badge, and runs #7 and #8 both listed;
  browser console had no errors and every request was a 200.

## Where the data lives (Postgres, 2026-10-06)

The local host now stores into the same Neon database the deployment reads;
SQLite is only the fallback when no Postgres URL is configured.

`prog5/config.py` reads an optional, gitignored `Prog5/.env` after the real
environment (`env_value()`), so a workstation no longer depends on `setx` or
on a fresh logon for `PROG5_DATABASE_URL` to take effect:

- Real environment variables always win, and an empty value counts as unset.
- A missing file is not an error; a clean checkout keeps the old SQLite path.
- `PROG5_ENV_FILE` points the lookup elsewhere. `tests/conftest.py` uses it to
  keep the suite on temporary SQLite files and now also asserts
  `config.database_url() is None` in `temp_db`, so a developer's live URL can
  never be written to by `python -m pytest`.
- `Prog5/.env.example` documents the four accepted names
  (`PROG5_DATABASE_URL`, `DATABASE_URL_POOLED`, `DATABASE_URL_UNPOOLED`,
  `DATABASE_URL`); only values starting `postgres://`, `postgresql://` or
  `postgresql+` switch storage over.

Proof that one database serves both ends (2026-10-06, WIB):

- With every `*DATABASE_URL*` variable removed from the shell, `python -m
  prog5.cli refresh --symbols TLKM` resolved the URL from `.env`, printed
  `refresh run #8 status=completed`, and left `Prog5/data/prog5.sqlite3`
  untouched (its newest run was still #9 from the previous day).
- `/api/v1/health` on this host and on `https://pokonya-lulus.vercel.app`
  returned the same `last_run` block, byte-identical down to
  `started_at=2026-10-05T21:48:54.608338` and
  `summary=prices=1204 indicators=1204 predictions=5 warnings=1`, both with
  `"storage_backend":"postgresql"`. The deployment is therefore reading the
  row this laptop wrote, not a baked snapshot.
- The dashboard footer reflects it: "Stored in PostgreSQL", 12,048 price rows,
  12,048 indicator rows, 100 predictions, last refresh #8.

The one thing this host cannot verify is whether the GitHub Actions secret
`DATABASE_URL` exists: secrets are write-only through the API. The workflow
fails loudly if it is absent.

## What the artifacts cannot support

1. **Two of the paper's three paths do not exist as artifacts.** Only the price
   regression path (LSTM/GRU/RNN) was saved. The ML voting path and the DL
   voting path exist only as notebook code, so `89.34%` ensemble accuracy cannot
   be served here without retraining (the notebooks are recoverable from CODE's
   git HEAD).
2. **The saved models predict price levels fixed to 2018-2023**, so they revert
   toward the training mean in a different regime. Earlier out-of-sample work in
   this repo showed signal accuracy below the always-hold baseline at every
   horizon. The OOD flag is the honest warning; it is not a fix.
3. **No confidence scores exist** in the artifacts; `predicted_price` plus the
   threshold rule is all there is.
4. **Current sentiment is not available.** The fused indicators stored here are
   technical only; news sentiment would need the crawl plus the SVM
   pseudolabelling model restored and re-validated.
5. **Corporate actions block predictions.** Yahoo returns raw (unadjusted)
   prices, so splits appear as >30% overnight moves; the refresh skips a horizon
   whose input window contains one rather than predicting on stretched data.
6. **Scale.** The service is single-user and EOD; there is no intraday data and
   no scheduling yet.

## Layout

```
prog5/config.py          paths, tickers, thresholds
prog5/models.py          SQLAlchemy tables
prog5/db.py              lazy engine/session factory
prog5/market_data.py     yfinance fetch, normalization, validation
prog5/indicators.py      TA-Lib-compatible pandas indicators
prog5/signals.py         thresholds, labels, OOD scoring
prog5/model_registry.py  artifact discovery, hashing, scaler reconstruction, inference
prog5/storage.py         idempotent upserts and reads
prog5/refresh.py         the only writer: fetch -> validate -> store -> predict
prog5/replication.py     proof that the registry reproduces the research CSVs
prog5/api.py             read-only FastAPI endpoints
prog5/scheduler.py       unattended refresh: due check, retries, loop
prog5/static/            dashboard served at /app (index.html, app.css, app.js)
prog5/cli.py             refresh / verify / inventory / serve / schedule
scripts/                 Windows Task Scheduler runner and one-command installer
```

## Commands

```powershell
cd Prog5
python -m pip install -r requirements-dev.txt
python -m pytest -q                       # 81 tests
python -m prog5.cli inventory             # artifact check per ticker
python -m prog5.cli verify --symbols ADRO # replication against research CSVs
python -m prog5.cli refresh --symbols ADRO,BMRI
python -m prog5.cli schedule              # unattended refresh loop
python -m prog5.cli schedule --once       # one due-check, for Task Scheduler
.\scripts\install-windows-task.cmd        # register the weekday Task Scheduler job
python -m prog5.cli serve                 # /docs for the API, /app for the dashboard
```

Environment overrides: `PROG5_DB_PATH`, `PROG5_ARTIFACT_DIR`,
`PROG5_RESEARCH_DATA_DIR`, `PROG5_DATABASE_URL` (Postgres switches storage
over), `PROG5_ENV_FILE` (where the optional `.env` is read from). The same
names work in `Prog5/.env`; see `Prog5/.env.example`.
