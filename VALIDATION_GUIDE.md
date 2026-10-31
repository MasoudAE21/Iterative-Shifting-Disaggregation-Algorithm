# Manual tests, smoke run, and Town analysis

Run these commands from PowerShell in order. They are ready for your manual run; this cleanup did not rerun the tests or regenerate results. Stop at the first failure and preserve its traceback.

## 1. Tests

```powershell
Set-Location D:\work\repo
.\.venv\Scripts\python.exe -m pytest tests -q
```

The repository's `conftest.py` automatically selects a unique `.pytest_tmp/run-...` directory for each run, avoiding Windows permissions on `Temp/pytest-of-Masoud`. An explicit `--basetemp` still overrides this. Scratch directories are ignored by Git and can be deleted after tests finish.

The last completed suite had 96 passing tests. It covers daily weather, legacy hourly adapters, bill windows, solver behavior, exports and verification. The hello-world placeholder was removed; the regression tests remain useful.

## 2. Small real-data smoke run

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --config configs/smoke.json --output outputs/smoke
```

This uses 100 fully covered customers, two outer fits and two shifting cycles, without checkpoints. It inherits the current Town settings: January 2–February 28, 2025; direct daily apparent temperature; accepted GMT/local-date approximation; original bill totals with weather-bounded exclusion. No TBS scaling is performed. JSON overrides the current IDE CONFIG, not legacy library defaults.

Check that `outputs/smoke/run_manifest.json` has `model_diagnostics.fallback_reason` equal to null. A completed export alone does not prove the ISD model ran.

```powershell
.\.venv\Scripts\python.exe scripts/verify_peak_outputs.py --output outputs/smoke
```

The independent verifier checks exported accounting and peak results. Its report is saved in `handoff/peak_final_verification.json`. Inspect the two weather SVGs, peak summary and run summary in the smoke output. Verification establishes internal consistency, not agreement with measured TBS.

## 3. Town input analysis

```powershell
.\.venv\Scripts\python.exe scripts/run_town_analysis.py
```

This runs the audit, writes the report, and draws the full bill-interval coverage plot. It reads current prepared files and raw TBS for an extraction cross-check. It does not fit the algorithm or modify input data. Allow time for the coverage-window calculations.

Review these regenerated files in `outputs/town_analysis/`:

- `Town_data_analysis_report.md`: current readiness findings.
- `daily_coverage.csv` and `audit.json`: evidence and source fingerprints.
- `selected_bill_daily_coverage.png`: selected bills inside and outside the target.
- `selected_bill_daily_counts.csv`: daily counts behind that plot.

The plot uses Pillow, available in the current environment. If rebuilding the environment, install the packages in `requirements.txt`.

## Later: full algorithm run

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --config configs/peak.json --output data/algorithm_output
```

This is not needed for the smoke/input-analysis stage. The apparent-temperature HDD feature remains the current provisional baseline; selecting better temperature features is the next investigation. Do not interpret this setup as a decision that the current feature is best.
