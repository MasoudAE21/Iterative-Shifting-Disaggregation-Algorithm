# Manual tests, smoke run, and Town analysis

The current setup is December 1, 2023–April 30, 2025, using the full-year bills and new three-variable weather. The boundary-only 150-day limit and weighted allocation are documented in README.md. On November 2, 2026, all 120 tests and the 100-customer full-period smoke run passed. Stop at the first failure and preserve its traceback.

## 1. Tests

```powershell
Set-Location D:\work\repo
.\.venv\Scripts\python.exe -m pytest tests -q
```

The repository's `conftest.py` automatically selects a unique `.pytest_tmp/run-...` directory for each run, avoiding Windows permissions on `Temp/pytest-of-Masoud`. An explicit `--basetemp` still overrides this. Scratch directories are ignored by Git and can be deleted after tests finish.

The suite covers daily weather, legacy hourly adapters, bill windows, reordered/date-formatted bill ingestion, solver behavior, exports and verification.

## 2. Small real-data smoke run

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --config configs/smoke.json --output outputs/smoke
```

This uses 100 fully covered customers, two outer fits and two shifting cycles, without checkpoints. It inherits the current 517-day Town settings, full-year bill input, direct daily weather, and accepted GMT/local-date approximation. Bills over 150 days are excluded only when they cross a window boundary; other crossing bills use weighted allocation. No TBS scaling is performed. JSON overrides the current IDE CONFIG, not legacy library defaults.

Check that `outputs/smoke/run_manifest.json` has `model_diagnostics.fallback_reason` equal to null. A completed export alone does not prove the ISD model ran.

```powershell
.\.venv\Scripts\python.exe scripts/verify_peak_outputs.py --output outputs/smoke
```

The independent verifier checks exported accounting and peak results. Its report is saved in `handoff/peak_final_verification.json`. Inspect the three weather SVGs, peak summary and run summary in the smoke output. Verification establishes internal consistency, not agreement with measured TBS.

## 3. Town input analysis

```powershell
.\.venv\Scripts\python.exe scripts/check_town_setup.py
```

This checks current full-year inputs, source hashes, weather availability, boundary allocations, and retained coverage without fitting the algorithm or modifying inputs. Read `outputs/town_setup/readiness.json` and `daily_readiness.csv`. TBS has no December 2023 measurements and records zero on April 30, 2025.

The older `scripts/run_town_analysis.py` workflow and these files in `outputs/town_analysis/` describe the historical January–February audit, not the new experiment:

- `Town_data_analysis_report.md`: current readiness findings.
- `daily_coverage.csv` and `audit.json`: evidence and source fingerprints.
- `selected_bill_daily_coverage.png`: selected bills inside and outside the target.
- `selected_bill_daily_counts.csv`: daily counts behind that plot.

The plot uses Pillow, available in the current environment. If rebuilding the environment, install the packages in `requirements.txt`.

## Later: full algorithm run

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --config configs/town.json --output outputs/experiment_01
```

This is not needed for the smoke/input-analysis stage. The apparent-temperature HDD feature remains the current provisional baseline; selecting better temperature features is the next investigation. Do not interpret this setup as a decision that the current feature is best.
