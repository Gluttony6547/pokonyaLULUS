# Verification report

Everything below was run on 13 October 2026 on Windows, Python 3.14 with the
packages from `requirements.txt` plus CPU-only torch, against the Postgres
database the deployment uses. Commands are quoted as run; output is quoted as
returned, trimmed where a table was long.

## 1. Tests

```
python -m pytest -q
67 passed, 393 warnings in 13.69s
```

The suite covers the signal thresholds, the trading-calendar walk, indicator
parity with the research columns, storage upserts, the refresh pipeline
including the holiday branch, the holdout metrics, the API surface, and one
real LSTM retrain. Every test runs against a throwaway SQLite file with the
network replaced by fixtures, so nothing in the suite touches Postgres.

The warnings are from Keras and Starlette internals (numpy 2 `__array__`
deprecation and a `testclient` import deprecation), not from this code.

Re-run on 30 October 2026, after the range-pricing change in `a07f40d`:

```
python -m pytest -q
100 passed, 541 warnings in 29.47s
node --test tests/test_dashboard.js
5 pass, 0 fail
```

The dashboard tests run the real render functions in a `vm` context against a
small DOM stand-in, so the price ranges, table headers, and the guard against a
stale response are exercised as behaviour, not matched as source text.

## 2. Replication against the research output

```
python -m idx_signal.cli verify
ADRO   T1   rows=1219  max|diff|=0.001586 IDR  reproduced
...
TLKM   T50  rows=1219  max|diff|=0.001012 IDR  reproduced
ALL REPRODUCED
```

All 50 combinations reproduce the committed predictions to within 1.6
thousandths of one rupiah, on a tolerance of 0.01 IDR. This is the evidence
that the serving path (rebuilt scalers plus the saved artifacts) is the same
computation that produced `Result Price Prediction`.

```
python -m idx_signal.cli inventory
ADRO   5/5 artifacts
...
TLKM   5/5 artifacts
```

## 3. Signal rule against the research labels

The threshold rule in `idx_signal/signals.py` was checked directly against the
`target_H` columns of `Labelled_Stock_*.csv`, for every ticker and horizon:

```
ADRO T 1  rule-vs-research agreement=1.0000
ADRO T 5  rule-vs-research agreement=1.0000
...
BMRI T50  rule-vs-research agreement=1.0000
```

Exact agreement on all 150 ticker-horizon pairs.

## 4. Live refresh against Postgres

```
IDX_DATABASE_URL=<neon pooled url> IDX_DATABASE_SCHEMA=sinyal python -m idx_signal.cli refresh
```

Result: `status=success`, 11,980 price rows written, 50 predictions across 10
tickers and 5 horizons, 0 failures, 10 warnings (all of them the same
"largest gap between sessions is 12 calendar days" note, which is the Idul Fitri
week in the 5-year window). Wall clock 31s for the whole run, most of it the
provider fetch.

Row counts read back from the database:

| Table | Rows |
|-------|------|
| `stocks` | 10 |
| `market_holidays` | 36 |
| `daily_prices` | 11,980 (2021-10-13 to 2026-10-13) |
| `model_versions` | 50 |
| `predictions` | 50 |
| `data_update_logs` | 3 |

Signal mix in the current snapshot: 26 HOLD, 16 BUY, 8 SELL. Model metrics
example, `ADRO`: T1 accuracy 0.3934, T50 accuracy 0.7090, each tagged
`source: reference holdout (test split)`.

The database this ran against already contained tables from an earlier
iteration of the project under the same names but different columns
(`stocks.name` versus `stocks.company_name`, and so on). The application was
pointed at its own schema instead of migrating that data, so no existing table
was read, altered, or dropped. `information_schema` confirms the app's seven
tables exist only under the `sinyal` schema.

## 5. API behaviour

Server: `uvicorn idx_signal.api:app` against the same Postgres database.

| Request | Result |
|---------|--------|
| `GET /` | 200 |
| `GET /docs` | 200 |
| `GET /static/app.css`, `/static/app.js` | 200 |
| `GET /api/v1/stocks/GOTO/signals` | 404 `GOTO bukan emiten yang didukung.` |
| `GET /api/v1/predictions/ADRO?horizon_days=7` | 422 `horizon_days harus salah satu dari (1, 5, 10, 20, 50).` |
| `GET /api/v1/cron/refresh` with no `CRON_SECRET` set | 503 `CRON_SECRET belum diatur...` |
| `GET /api/v1/cron/refresh` with a wrong bearer token | 401 `Token jadwal tidak cocok.` |
| `GET /api/v1/cron/refresh` with the configured token | 200 `{"ran": false, "reason": "not due"}` |

The last row is the correct answer: the day's slot had already been served, so
the due check declined to fetch again. It proves the token comparison and the
due check both run.

### Latency (NFR-01, reads under 500 ms)

`GET /api/v1/stocks` initially took 0.50 to 0.76 s against the pooled remote
database: it looked up the newest close with one query per ticker. It now reads
all ten in a single window query.

| Endpoint | Before | After |
|----------|--------|-------|
| `/api/v1/stocks` | 0.50 to 0.76 s | 0.15 to 0.17 s (five runs: 0.165, 0.155, 0.161, 0.151, 0.167) |
| `/api/v1/stocks/ADRO/signals` | 0.249 s | unchanged |
| `/api/v1/prices/ADRO?limit=180` | 0.254 s | unchanged |
| `/api/v1/model-versions/ADRO` | 0.115 s | unchanged |

The payload was re-checked after the change: 10 tickers, each with its name,
last price date (2026-10-13) and last close (ADRO 2520.0, ANTM 3100.0,
BMRI 3990.0).

## 6. Dashboard click-through (R-35)

Driven in a real browser at 390x844 (mobile) and at desktop width, against the
live Postgres data. Every control was clicked one at a time.

| Control | Action taken | Result |
|---------|--------------|--------|
| Ticker rail, `BMRI` | clicked | Panel switched to "Bank Mandiri (Persero) Tbk, Financials", five signal rows re-rendered, chart and indicators reloaded |
| Ticker rail, `TLKM` | clicked | Panel switched; six model versions listed for T+1 including the retrained candidate |
| History horizon select | changed 1 to 50 | Rows re-fetched; T+1 showed `HOLD +0,47%`, T+50 showed `BUY +24,05%` |
| Theme toggle | clicked twice | `light` then `dark`, label swapped between "Mode gelap" and "Mode terang", `aria-pressed` tracked it |
| Refresh button | clicked | `POST /api/v1/update-logs/refresh` returned 200; banner read "Pembaruan selesai dengan status success. 50 sinyal dari 10 emiten"; freshness line updated to 22.58 WIB; the update log gained a row |
| Train form, `TLKM T+1` | submitted with no model change | API answered `reused: true` with the message that the combination already has an active model, matching PRD flow A1 |
| Train form, `TLKM T+1`, "latih ulang" checked | submitted | Job queued (`#1`), status moved queued to running to success, model version `#51` registered with its own metrics |
| "Jadikan aktif" on version `#51` | clicked | Banner "Versi #51 sekarang aktif"; the status cell flipped to `aktif` and the reference version `#46` offered the button instead |
| Keyboard: Tab from the top | pressed | Focus reached the ticker buttons in visual order, each with a visible `solid 1.6px rgb(224, 160, 90)` outline |

Console: no messages of any level. Network: every request 200, no failures.

After the click-through, version `#46` (the reference artifact) was reactivated
so the deployed database serves the verified reference models, not the
throwaway retrain. `training_jobs` keeps the run as a record of the test.

### Contrast (R-25)

Computed from the live rendered colours in both themes, resolving each element
against its nearest opaque background:

| Theme | Lowest ratio found | Where |
|-------|--------------------|-------|
| light | 6.27 | `HOLD` chip |
| dark | 7.12 | secondary text (`#freshness`, `.panel-sub`, footer) |

Both clear the 4.5:1 floor with room to spare, and the signal chips are
6.97 (BUY, light) and 8.31 (BUY, dark).

### Mobile (R-03)

At 390x844: `documentElement.scrollWidth` 374 against a 390 viewport, no
horizontal overflow, no element crossing the right edge, layout collapsed to a
single 341.6 px column. The smallest interactive target is 44 px high (ticker
buttons 63x44, theme toggle 130x44, refresh 204x44, and the checkbox label is a
44 px row around an 18 px box).

## 7. Schedule mapping

The two `vercel.json` entries are documented as sitting an hour after the slot
they serve. That mapping was checked directly against `due_slot`, building the
fire times as true UTC instants:

```
cron 1 (10:05 UTC)  fires Mon 17:05 WIB -> slot 16:05  PASS
cron 2 (12:05 UTC)  fires Mon 19:05 WIB -> slot 18:00  PASS
```

Vercel's Hobby plan fires a cron job within the scheduled hour rather than at
the exact minute, so every minute offset in the hour was checked:

```
cron 1 jitter +00m .. +59m  -> slot 16:05  PASS (all six offsets)
cron 2 jitter +00m .. +59m  -> slot 18:00  PASS (all six offsets)
```

The earliest any fire can land is 17:00 WIB, still after the 16:05 slot and
after the 16:00 market close, so no offset can miss its slot. Two further
cases: a cron fire already served earlier the same day returns no slot and
fetches nothing, and a Saturday fire resolves to Friday's slot, which the
trading-day check in `refresh()` then skips and logs as `skipped`.

`idx_signal.cli serve --port 8031`, the command the README gives, was run as
written: `/api/v1/health` and the dashboard both answered 200. With no database
URL set, the documented SQLite fallback created its tables and seeded 10
tickers and 36 holidays.

## 8. Repository state

Commit `4d73707`, "Serve the LSTM research as a deployable IDX signal dashboard",
pushed to `pokonyaLULUS` `main` as a fast-forward from `e6f575e`. 237 files
changed: 6,290 insertions, 25,625 deletions.

`main` is now the only branch on that remote. Five `codex/*` branches were
deleted, and because each held commits that were not in `main`, their tips were
first recorded as tags so nothing became unreachable:

| Tag | Was | Tip |
|-----|-----|-----|
| `archive/codex-cpu-torch-images` | `codex/cpu-torch-images` | `5f6271a` |
| `archive/codex-model-horizons` | `codex/model-horizons` | `6d0ed26` |
| `archive/codex-prog5-neon-bootstrap` | `codex/prog5-neon-bootstrap` | `19c3d9d` |
| `archive/codex-prog5-production` | `codex/prog5-production` | `f2b76f6` |
| `archive/codex-vercel-container` | `codex/vercel-container` | `4ead244` |

The same six local branches were removed. Two were deliberately kept, and no
branch was deleted anywhere else:

- `consolidate-to-pokonya-main` (`979ddba`) holds 14 commits that exist on no
  remote and in no archive tag, and differs from `main` in 261 files. It is the
  only remaining copy, so it stays.
- `main` (`a55e24b`) tracks `origin/main` on the `tugasakhir` remote, which is a
  separate repository and was not touched.

Artifacts and reference series moved into `models/<SYMBOL>/` and
`data/research/`, and git recorded all 171 of them as pure renames: `git
count-objects` reports the same 196.58 MiB pack before and after the commit, so
the re-organisation added no blob storage.

## 9. What is not verified

- **The container image was not built or run here.** Docker is not installed on
  this machine. `Dockerfile`, `Dockerfile.vercel`, and the CI job that builds and
  probes the image are written but unexecuted; the CI workflow is the first
  place they will actually run.
- **The deployment is live but its git SHA is not readable from here.**
  `https://pokonya-lulus.vercel.app` serves `index.html`, `app.css`, and `app.js`
  byte-identical, ignoring CRLF, to the checked-out commit, checked by comparing
  the served files with the local copies. No Vercel CLI, token, or deployment
  tool was available, so the deployed SHA is inferred from that content match
  rather than quoted from the platform. The crons, the container image, and
  first-deploy behaviour are otherwise as described in the README.
- **The Vercel cron path was exercised only locally**, by calling the endpoint
  with the exact `Authorization: Bearer <secret>` header Vercel sends. The
  scheduler itself (that Vercel fires within the hour) is platform behaviour.
- **Retrained artifacts do not survive on Vercel.** The container filesystem is
  ephemeral there; the retrain in this report ran against a local path. See the
  README's deploy section.
- **Sentiment features are not part of the serving path.** The reference
  research used 19 features including news sentiment; this service serves the
  closing-price path the artifacts expect.