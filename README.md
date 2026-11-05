# Madrasflow

Hourly weekday/weekend ticket-demand forecasting and transparent service planning for Chennai ETM data. One historical benchmark and one pooled XGBoost model. Original ticket data stays outside this repository.

## Setup

Use Python 3.12 or newer for the exact tested versions, or a compatible Python environment with `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Optional project-local `.deps` packages are loaded only when their `python_abi.txt` matches the running interpreter. A normal virtual environment does not require `.deps`.

## Run the pipeline

Run from this project directory. ETM files remain in their original sibling directory.

```powershell
python run.py ingest --source ..\ETM\ETM\extracted
python run.py train --input data/hourly.parquet --output artifacts/boardings
python run.py segments --routes 10
python run.py train --kind segments --input artifacts/segments/segments.parquet --output artifacts/segment_model
python run.py profiles --input data/hourly.parquet --model-dir artifacts/boardings
python run.py profiles --input artifacts/segments/segments.parquet --model-dir artifacts/segment_model --output artifacts/segment_profiles.parquet
python run.py plan --flows 420 300 200 --trips 6 --target-load 40
python run.py reallocate --donor-flows 80 60 --donor-trips 4 --receiver-flows 420 --receiver-trips 6
```

`plan` takes **section passenger crossings**, not ticket boardings. Its numbers are conditional service arithmetic. Without validated section timing/service data, do not treat the segment proxy as measured bus occupancy.

For later daily data, repeat ingestion and profile generation with a new `--cutoff`. To retrain without overwriting an evaluated model, use `python run.py refit --cutoff YYYY-MM-DD --output artifacts/candidate-YYYY-MM-DD`. This reuses frozen settings and creates an unpromoted candidate; later-date validation is still required. The `train` command is the fixed March experiment, not an automatic production promotion job.

Use `scripts/verify_data.py --audit ../analysis/etm_profile.json` to cross-check ingestion against the earlier independent CSV audit. Changed daily inputs replace their aggregate partitions; unchanged files are skipped. Complete ETM days must be available before running evaluation.

## Outputs

- `data/ingestion_report.json`: exclusions, counts and passenger reconciliation.
- `data/hourly.parquet`: validated hourly ticketed boardings.
- `artifacts/boardings/metrics.json`: chronological validation/test metrics and selected model.
- `artifacts/segments/segment_report.json`: pilot selection, missing destinations, stage orientation and crossing reconciliation.
- `artifacts/segment_model/metrics.json`: forecast agreement with reconstructed section labels.
- `artifacts/*profiles.parquet`: separate 24-hour weekday/weekend reference profiles at the declared data cutoff.
- `artifacts/scenario.json`: minimum trip passages per hour and optional fleet lower bound.

Raw data, prepared datasets, model files, credentials and local dependencies are excluded from Git. Small aggregate validation summaries are tracked under `reports/` after verification.

## Scope

The working code covers ingestion, forecasting, stage-interval estimation and conditional service scenarios. Geographic stage-to-map matching, verified crossing-hour occupancy, mobile driver UI and a manager dashboard are subsequent integration work. Missing values do not imply a free section. The two forecast methods are a weekday/weekend historical benchmark and pooled XGBoost; PCA and K-means are intentionally absent.

See [methodology](docs/methodology.md) for target definitions, evaluation splits and limitations.
