<!-- antislop:start -->
## antislop
For UI, copy, people, mobile layout, or code comments work, read `antislop.md` (core) and then the skill for the task:
- UI / visual: `skills/antislop-ui/SKILL.md`
- Copy & text: `skills/antislop-copywriting/SKILL.md`
- People: `skills/antislop-human/SKILL.md`
- Mobile / responsive: `skills/antislop-layoutmobile/SKILL.md`
- Code comments: `skills/antislop-code/SKILL.md`
Before starting, follow the core's "Two Usage Modes" section in strict order: explicit session instruction first, then global preference, then ask. A session instruction always wins. For a resolved mode, say `antislop active: <mode> (session override).` or `antislop active: <mode> (global preference).` once before presenting findings or making edits, using the actual mode and source. Acknowledging the user's request without naming the source does not replace this notice.
Only an explicit choice of antislop during or after selects a session mode. A request to review, audit, or avoid file edits does not select a mode; read the global preference in that case. Another skill's mode does not select antislop's mode.
If the mode is unresolved, ask during/after and end the response; wait for the answer before any UI review, planning, or concept. For read-only tasks, put the active-mode notice only at the start of the final answer, never in progress messages. For editing tasks, announce before the first edit and omit it from the final answer.
To update antislop later: download `antislop.md` again, or run `npx antislop-ai --update` if it was installed as skill folders.
<!-- antislop:end -->

# Sinyal IDX

Web application that serves buy, hold, and sell signals for ten IDX tickers from
the saved LSTM artifacts in this repository.

## Where things are

| Path | Contents |
|------|----------|
| `idx_signal/` | application package: config, storage, prediction, refresh, scheduler, training, API |
| `idx_signal/static/` | the dashboard, one HTML page plus a stylesheet and a script, no build step |
| `models/<SYMBOL>/` | the 50 saved LSTM artifacts the signals come from |
| `data/research/` | reference series and committed research predictions, used to rebuild scalers and holdout metrics |
| `tests/` | pytest suite, network calls replaced by fixtures |
| `CODE/` | the research checkout (its own git repository, not part of the app image) |

## Commands

```bash
python -m pytest -q                  # tests
python -m idx_signal.cli seed        # create tables and seed tickers and holidays
python -m idx_signal.cli refresh     # fetch prices and write signals
python -m idx_signal.cli verify      # serving path vs the committed research output
python -m idx_signal.cli serve       # dashboard and API
python -m idx_signal.cli schedule    # the due check, in a loop
```

## Direction

`DESIGN.md` holds the visual direction for the dashboard. Read it before
changing anything a user sees. `README.md` has the run, database, and deploy
instructions; `REPORT.md` has the verification record.

## Conventions

- The dashboard is Indonesian, matching the interface language of the product.
  Code, comments, docstrings, and the README are English.
- Application state lives in Postgres when `IDX_DATABASE_URL` or `DATABASE_URL`
  is set, and in a local SQLite file otherwise. Tests always use SQLite.
- There is one writer: `idx_signal.refresh`. Both the manual button and the
  scheduled path call it, so they cannot diverge.
- Never commit `.env`, credentials, or the local SQLite file.