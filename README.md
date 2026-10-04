# Prog5 IDX Signal Desk

Web dashboard for inspecting saved LSTM price forecasts for ten IDX tickers at T+1, T+5, T+10, T+20, and T+50. It reports the model output and threshold-based signal with data freshness and out-of-distribution context; it does not provide confidence probabilities or investment advice.

## Run locally

Use Python 3.12+, then install and start the service from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-torch-cpu.txt
python -m pip install -r Prog5/requirements-dev.txt
$env:PYTHONPATH = "$PWD/Prog5"
$env:PROG5_ARTIFACT_DIR = "$PWD/models"
$env:PROG5_RESEARCH_DATA_DIR = "$PWD/Prog5/data/research"
python -m prog5.cli serve --host 127.0.0.1
```

The dashboard is at `/`, API docs at `/docs`, and health at `/api/v1/health`. Without `DATABASE_URL`, Prog5 stores local data in `Prog5/data/prog5.sqlite3`.

## Neon and production

Set `DATABASE_URL` to Neon's pooled connection string for the running service. Keep the direct URL out of deployment runtime; use it only for one-time administration or bulk snapshot import. At startup Prog5 creates its additive tables with a `prog5_` prefix, leaving the existing application's tables untouched.

Import the existing local snapshot once before opening the dashboard:

```powershell
$env:PROG5_DATABASE_URL = $env:DATABASE_URL_UNPOOLED
python -m prog5.cli import-snapshot --sqlite-path "C:\path\to\prog5.sqlite3"
```

The importer preserves existing records and can be rerun safely. Configure `PROG5_ARTIFACT_DIR` and `PROG5_RESEARCH_DATA_DIR` only when running outside the included Docker image; the Vercel image sets these paths itself. Local scheduler execution remains an operator-managed process; Vercel's ephemeral filesystem is not used for scheduled writes.

## Model and data provenance

The image includes the 50 LSTM `.h5` files from `CODE/Price Prediction Model` and the fusion and labelled close series needed to reconstruct scalers. Their SHA-256 values match the original model files. GRU/RNN experiments, replication outputs, raw stock fixtures, notebooks, workbooks, raw news, and unrelated research exports stay outside the runtime image; CI retains the verification fixtures and `prog5.cli verify` compares predictions with the research CSVs.

The source models were trained on data ending in 2023. Out-of-distribution and corporate-action checks are warnings/guards; they do not correct regime drift or make the forecasts reliable for trading.

## Verification

```powershell
$env:PYTHONPATH = "$PWD/Prog5"
$env:PROG5_ARTIFACT_DIR = "$PWD/models"
$env:PROG5_RESEARCH_DATA_DIR = "$PWD/Prog5/data/research"
python -m pytest -q Prog5/tests
python -m prog5.cli inventory
python -m prog5.cli verify
```

GitHub Actions runs both the existing application checks and the Prog5 test, artifact replication, and Docker build checks. The linked Vercel project deploys its container from `main`.

## Product and engineering decisions

- [Prog5 PRD](Prog5/PRD.md)
- [Engineering notes and PDM](Prog5/NOTE.md)
- [Verification report](Prog5/REPORT.md)
