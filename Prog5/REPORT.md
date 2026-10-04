# Prog5 UI pass report

Only what was actually run on 2026-10-04, in order, plus what broke. Evidence
for the UI acceptance criteria in [PRD.md](PRD.md). The antislop Delivery Gate
is at the end. Everything below was observed in this session; anything not
observed is listed under "Not exercised".

## 1. Test suite

Commands (both from `Prog5/`):

```
python -m pytest -q
```

- Run 1: `48 passed, 3 warnings in 10.82s`, exit 0.
- Run 2 (after the retry fix in `app.js`): `48 passed, 3 warnings in 11.11s`,
  exit 0.
- Warnings are the known Starlette TestClient deprecation and the keras/torch
  numpy `__array__ copy` deprecation.

## 2. Serving the app

```
python -m uvicorn prog5.api:app --host 127.0.0.1 --port 8123
```

- `/api/v1/health` returned 200 and reported `stocks=2`, `price_rows=2407`,
  `indicator_rows=2407`, `prediction_rows=10`, artifacts for 10 tickers, last
  run #2 completed.
- `/app/` returned `200 text/html`.
- The browser loaded `http://127.0.0.1:8123/app/` as a first-time visitor; it
  defaulted to `?symbol=ADRO&horizon=1` and rewrote the URL as selections
  changed (no history spam; `replaceState`).

## 3. What the first load rendered (ADRO T+1)

Predicted 2,536.85 IDR, last close 2,500 IDR, +1.47% over 1 session, signal
"hold", signal threshold 1.5%, data as of 02 Oct 2026 with "2 days old",
"Fresh" badge, model file `LSTM_ADRO_Target_1.h5`, SHA-256 shown as
`96b465a8e072…` (full hash in the title attribute), OOD z 0.69 (inside range),
price rows read 180, the training rule in plain words, a 180-session chart
(06 Jan 2026 to 02 Oct 2026, range 1,865 to 2,840 IDR), seven indicator chips,
one prediction-history row, and both refresh runs in the runs table. All
figures matched the API payloads fetched with curl.

## 4. Element-by-element click-through (R-35 evidence)

| Element | Action | Result |
| --- | --- | --- |
| Page load | Open `/app/` | Default ADRO T+1 card, stats, chart, chips, history, runs; no console errors; only 200s in the network log |
| Horizon T+50 | Real click | Card changed to ADRO T+50: 2,455.85 IDR, hold, 11% threshold, window 23 Jul to 02 Oct, 50 sessions; URL updated |
| Ticker select | Choose BMRI | Card changed to BMRI T+50: 5,025.72 IDR, buy, +24.71%, 11% threshold, OOD 0.30; URL updated |
| Horizon T+20 | Keyboard (Tab then Enter) | Card changed to ADRO T+20: 2,658.9 IDR; `aria-pressed` moved to T+20; URL updated |
| Ticker select | Choose TLKM (no stored rows) | Empty state: "TLKM has 5 saved models but no stored market rows yet… `python -m prog5.cli refresh --symbols TLKM`"; chart, chips, and history each said what was missing; no error state |
| Theme toggle | Real click, both directions | dark to light and back; `aria-pressed`, label, localStorage, and all tokens changed; body background computed `rgb(245, 244, 239)` then `rgb(18, 22, 19)` |
| Skip link | Tab, then Enter | Slides to `left: 0` with a visible focus ring when the page has focus; Enter set `location.hash` to `#main` |
| Footer links | Inspect | Point at `/docs`, `/openapi.json`, `/api/v1/health`, all served by the same app |
| Retry button | Real click after a real failure | See section 6 |

Not-a-control check: the page contains no button or link without a real
destination, no nav to nonexistent sections, no placeholder toggles.

## 5. Freshness and OOD paths (temp DB copy)

Live rows are all 2 days old and unflagged, so those two display paths cannot
occur with the current data. To exercise them honestly, the live SQLite file
was copied to a temp path, one ADRO T+1 row was updated to `ood_flag=1`,
`ood_z=2.61`, `data_as_of=2026-09-15`, and one ADRO T+5 row to
`data_as_of=2026-09-28`; a second uvicorn instance served that copy on
127.0.0.1:8124.

- ADRO T+1 rendered the "Stale" badge (19 days old) and the OOD block:
  "Outside the model's training range. The most recent close sits 2.61 training
  standard deviations from the training mean…", with `role="note"`.
- ADRO T+5 rendered the "Older" badge (6 days old) and no OOD block.
- Temp server stopped and temp DB deleted afterwards; `Prog5/data/` contains
  only `prog5.sqlite3`.

## 6. What broke

One real defect, found by the error-state test and fixed:

- **Retry after a boot-time failure did nothing.** `renderError` wired the
  button to `load()`, but a boot failure happens before any ticker is selected,
  so `load()` returned immediately (`state.symbol` is null). Fix in
  `prog5/static/app.js`: the button now re-runs `boot()` when there is no
  selection. Re-verified end to end: with an empty DB the boot failed with
  `500 Internal Server Error from /api/v1/stocks` in the error card; after
  restoring the real DB, one click on "Try again" rebuilt tickers, runs, the
  footer status, and the default ADRO card.

One tooling limitation, reported as a limitation, not a pass:

- Screenshots could not be captured: the preview webview reported "not being
  composited" from the start and after a reload and a fresh tab. Layout was
  therefore verified with geometry and computed styles instead of pixels: no
  horizontal overflow at 375px or 1280px, all controls 44px tall, tables
  scroll inside their panel, meta grid 1/2/4 columns by breakpoint, chart
  scales to its container. Actual rendered pixels were not seen this session.
- Keyboard presses only moved focus after the page held OS focus (a real click
  restored it). The Tab, Enter, and focus-ring results above were recorded
  after that, with trusted key events.

## 7. Contrast

`C:/Users/NAUFAL DARISKARIM/.agents/skills/antislop-human/contrast-check.py`,
run on 23 pairs sampled from the live computed styles plus the tokens the live
rows do not show (sell, warn, focus backgrounds):

- Light: `#4E5A53` on `#F5F4EF` 6.55:1, on `#FFFFFF` 7.21:1; `#0B6355` on
  `#F5F4EF` 6.51:1; `#1A201C` on `#F5F4EF` 15.05:1, on `#FFFFFF` 16.57:1;
  `#FFFFFF` on `#0B6355` 7.17:1; `#14653F` on `#E1EFE6` 5.97:1, on `#FFFFFF`
  7.09:1; `#414B45` on `#E9EAE3` 7.48:1; `#9E2F22` on `#F7E4E0` 5.94:1;
  `#71420A` on `#F8EBD7` 7.18:1; `#0B6355` on `#DFEEE8` 5.98:1.
- Dark: `#A6B1A9` on `#121613` 8.25:1, on `#1A1F1B` 7.55:1; `#E9EDE9` on
  `#1A1F1B` 14.14:1, on `#121613` 15.44:1; `#6BC6B2` on `#121613` 9.00:1, on
  `#17332B` 6.70:1; `#081712` on `#6BC6B2` 9.06:1; `#7FD6A6` on `#143024`
  8.17:1; `#CBD4CC` on `#262C27` 9.39:1; `#F09A8B` on `#3A1E19` 7.03:1;
  `#EDBE7E` on `#382B15` 8.05:1.

All pass the normal-text 4.5:1 and large-text 3:1 thresholds.

## 8. Copy and content checks

- Em dash scan: searched `prog5/static/` for the em dash character with grep;
  none found.
- Every number on the page comes from an API payload or the artifacts; there
  are no invented statistics, testimonials, or claims. The footer states the
  real source (Yahoo Finance EOD rows in SQLite) and the not-advice caveat.
- The pipeline warning field is `null` in all ten stored predictions, so the
  card's "Pipeline note" line never appears with live data; the runs table
  still shows the run-level `warnings=1` count in its summary.

## 9. Not exercised

- The 404 and 422 paths in the browser: the UI never requests an unsupported
  ticker or horizon, by construction.
- Pixel-level rendering, see section 6.

## 10. Ten-ticker coverage pass (same day, later)

Commands (from `Prog5/`):

```
python -m prog5.cli refresh --symbols ANTM,BNGA,EXCL,INCO,INKP,MEDC,PGAS,TLKM
python -m prog5.cli refresh --symbols ADRO,ANTM,BMRI,BNGA,EXCL,INCO,INKP,MEDC,PGAS,TLKM
```

- The first command (run #3) populated the eight missing tickers: 9,631 price
  rows, 9,631 indicator rows, 40 predictions, with only the benign `largest
  calendar gap is 12 days` warning once per ticker.
- The second command (run #4) then re-ran all ten in one pass as the final
  authoritative refresh: 12,038 price rows, 12,038 indicator rows, 50
  predictions, same benign warning per ticker. Stored row counts before and
  after were identical (12,038 / 12,038 / 50 with five predictions per
  ticker), so the upsert keys held and nothing duplicated.
- SQLite check per ticker: every one of the ten tickers now has 1,203 or 1,204
  price rows, the same number of indicator rows, last close 2026-10-02, and
  predictions for T+1, 5, 10, 20, and 50. The cross-join for missing
  ticker/horizon pairs returned `none`.
- Corporate-action audit, run over the stored series with the existing
  `corporate_action_dates` and `window_has_corporate_action`: zero >30%
  overnight moves in the five-year window for all ten tickers, so no horizon
  was skipped and nothing failed. The skip branch itself is covered by
  `tests/test_refresh_pipeline.py::test_refresh_skips_horizons_with_a_corporate_action_in_the_window`
  and two tests in `tests/test_market_data.py`; this data simply never triggers
  it.
- OOD flags are now live data: ANTM +2.13, BNGA +3.08, MEDC +2.93, TLKM -3.30;
  the other six are inside range.
- Footer after the refresh: 12,038 price rows, 12,038 indicator rows, 50
  predictions; the runs table shows runs #3 and #4.
- UI check after a reload, every ticker at T+1: the card shows predicted price,
  signal, threshold, data as of 02 Oct 2026 with the Fresh badge, SHA-256
  prefix, and OOD z for all ten, and the walk was repeated after run #4 with
  identical values. The "Outside the model's training range" block
  and the row-level pipeline note appear on exactly the four flagged tickers
  and on none of the clean six. TLKM T+50 spot-checked: 3,483.04 buy, 11%
  threshold, warning shown. The sell chip is now exercised by live ANTM rows.
  The selection note reads `10 of 10 research tickers have stored data`.
- Console after the walk: empty; the network log contains only 200s. The test
  suite was re-run: `48 passed, 3 warnings in 9.22s`, exit 0.
- No code changed in this pass, so the Delivery Gate results below still stand.
- Nothing could not be produced: all ten tickers and all five horizons are
  stored. There is no skipped-horizon example to show because no ticker has a
  corporate action in any input window.


## 11. Unattended refresh (scheduler, same day, later)

Commands and observations:

- `python -m pytest -q` after the scheduler work: `60 passed, 3 warnings in
  6.60s`, exit 0 (the suite grew from 48 to 60 with 12 scheduler tests).
- Overlap proof: with a fresh lock file placed at `data/prog5.sqlite3.lock`,
  `python -m prog5.cli schedule --once --force` printed `scheduled refresh:
  ran=False attempts=0 reason=locked: Another refresh is running (lock
  ...prog5.sqlite3.lock).` and did not delete the lock.
- Live trigger: a detached scheduler process (PowerShell `Start-Process`) was
  started at 20:20:35 with the slot set to 20:26 local. It logged `Scheduler
  started`, then `Scheduled slot 2026-10-04 20:26 is due`, fetched all ten
  tickers, and logged `scheduled refresh: ran=True attempts=1 reason=refresh
  run #6 completed (50 predictions)`. SQLite: run #6 has `kind=scheduled`,
  `status=completed`, `prices=12038 indicators=12038 predictions=50
  warnings=10`. Row counts and per-ticker prediction counts were unchanged
  (idempotent).
- What broke and was fixed in the code: the first live trigger (run #5) was
  recorded as `kind=on_demand` because `refresh()` hardcoded the kind. The same
  pipeline now takes a `kind` parameter, the scheduler passes `scheduled`, and
  `tests/test_scheduler.py::test_refresh_records_the_run_kind` covers it. Run
  #6 proves the fix end to end.
- Host/process observation: a daemon started through the agent's background
  wrapper was reaped after its first run with no traceback; the same daemon
  started as a detached Windows process kept running after its run. NOTE.md
  documents the console session and Windows Task Scheduler as the supported
  ways to keep it alive on this host.
- Weekday rule observation: the first live attempt on Sunday 2026-10-04 did
  nothing because the default schedule is weekdays only; enabling all days for
  the test made the trigger fire. That is the documented behavior, not a bug.
- UI check after run #6: `/app/` shows `#6 · scheduled completed` with all ten
  symbols first in the runs table, the footer reads `Last refresh #6
  completed`, and the card still renders (TLKM T+1, 2,439.52 IDR buy).
- Resolved in the production pass: the browser now treats naive API datetimes
  as UTC before formatting them in the visitor's local timezone. On this
  Jakarta workstation, run #6 and the card both show `04 Oct 2026, 20:26`.

## 12. Production packaging and final review

- The existing 50 LSTM model files in the repository were compared with
  `CODE/Price Prediction Model`; every SHA-256 digest matches. Prog5's runtime
  image includes those files plus only the fusion and labelled close CSVs
  needed to rebuild scalers. Raw stock and replication CSVs stay in the repo
  for CI verification and are excluded from the image.
- Prog5 now uses Neon/PostgreSQL when `DATABASE_URL` (or
  `DATABASE_URL_POOLED`) is set and local SQLite otherwise. Tables use the
  `prog5_` prefix so the older app's schema is unaffected. Local SQLite table
  names are migrated in place; the snapshot importer is safe to rerun and
  updates PostgreSQL sequences after preserving row IDs.
- A copied SQLite snapshot served locally after migration. The dashboard root,
  10 tickers, latest prediction, run history, storage label, and WIB timestamps
  rendered correctly. Browser console had no errors or warnings.
- Final repo verification: `85 passed, 18 warnings` across the existing and
  Prog5 suites; all warnings are third-party deprecations. Artifact inventory
  is 5/5 for all ten tickers, all 50 model/horizon outputs reproduce their
  research CSVs (maximum absolute difference 0.004977 IDR), and the existing
  training-engine smoke run completes.
- The local machine has no Docker CLI, so container builds remain delegated to
  the two GitHub Actions image-build steps. A Neon snapshot import attempt was
  rejected with password authentication failure before any database write;
  refresh `DATABASE_URL` with the current Neon credential before relying on
  hosted data.

## antislop Delivery Gate

Block 1, Hard Gate (all "no" by design):

- R-02 PASS: no em dash in any agent-written text; a grep scan of
  `prog5/static/` found none.
- R-03 PASS: at 375px no horizontal overflow, no clipped text, tables scroll in
  their own panel, controls 44px tall; measured with bounding rects.
- R-17, R-18, R-23, R-36, R-38 PASS: every figure traces to the DB or the
  artifacts; no testimonials, avatars, or invented numbers; the only generated
  asset is the "P5" text mark.
- R-24 PASS: footer links point at `/docs`, `/openapi.json`, `/api/v1/health`,
  verified 200.
- R-25 PASS: 23 pairs checked, 5.94:1 to 16.57:1, all above AA in both themes.
- R-26 PASS: every button, link, and control has a real behavior; the only
  button without a page destination is the theme toggle and the retry, both
  functional (click-through section 4).
- R-27 PASS: loading, empty, and error states all observed, including a real
  500.
- R-28 PASS: no FAQ exists.
- R-32 PASS: Tab walk, Enter activation, skip link, visible focus ring
  recorded.
- R-33 PASS: no patch scripts; the feature is in the source files.
- R-34 PASS: both themes toggled and measured; contrast checked in both.
- R-35 PASS: app run and clicked through element by element (section 4).
- R-37 PASS: Design Read declared in NOTE.md; direction taken from the brief,
  dials ENERGY 1 / RHYTHM 2 / MOTION 1, held across the page.

Block 2, Purpose-Gate (technique plus written reason):

- R-01, R-04, R-07, R-08, R-09, R-10, R-13, R-14, R-22 PASS: no gradients,
  icon fonts, background patterns, arrows, capsule badges, glass, glow, or
  illustrations exist at all.
- R-06 PASS: system UI stack chosen for native analysis chrome; mono only for
  model files and hashes.
- R-12 PASS: exactly one shadow, on the prediction card, as the focal point.
- R-19 PASS: no animation beyond hover, focus, and theme color transitions,
  matching MOTION 1.

Block 3, Liveliness (all "yes"):

- Dials declared and consistent: ENERGY 1 / RHYTHM 2 / MOTION 1.
- One focal point per screen: the prediction card.
- Whitespace is structural: panels separated by a fixed rhythm, no filler.
- One deliberate accent: deep teal, reserved for interactive and action color.
- Identity motif: the "P5" wordmark and the number-first card; swapping the
  name would change the product, not just the label.
- Design Read declared before generation (NOTE.md).

Block 4, Craftsmanship and Quality Locks (all "no" by design):

- C-1 to C-5 PASS: every decision has a one-line reason (NOTE.md table); no
  dead controls; sections exist because the product needs them; states,
  themes, breakpoints, and keyboard all hold; no fabricated claims.
- R-05, R-11, R-15, R-16, R-20, R-21, R-29, R-30, R-31 PASS: no template
  sections, radius scale 12/8/6 by role, no generic CTAs or buzzwords, both
  themes real, palette is neutrals plus one accent plus semantic status hues,
  no popular-product clone, reasons written down.

Verdict: no FAIL item. Passed before delivery.
