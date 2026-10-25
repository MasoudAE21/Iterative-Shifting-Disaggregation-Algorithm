# Manual validation guide

Run these commands one at a time in PowerShell. Stop at the first failure and
send the command and complete traceback. None of these commands has been run as
part of preparing this guide.

## 1. Use the project environment

```powershell
Set-Location D:\work\repo
.\.venv\Scripts\python.exe --version
```

Use `.venv\Scripts\python.exe` as your IDE interpreter too. The first solver test
may take longer while Numba compiles kernels.

## 2. Check data preparation and weather

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_data_weather.py -q -p no:cacheprovider
```

Expected: all tests pass. Covers normalization, internal-gap rejection, coverage,
prepared-state samples, weather integration and target-day plots.

## 3. Check solver math and engine agreement

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_solver.py tests/test_real_fixture.py -q -p no:cacheprovider
```

Expected: all tests pass. Includes hand-calculated updates, conservation,
checkpoint behavior, and reference/scaled comparison on a pseudonymized fixture.

## 4. Check pipeline, both peak modes, and independent verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py tests/test_peak_review.py tests/test_peak_verifier.py -q -p no:cacheprovider
```

Expected: all tests pass. These use temporary fixtures, not a full real-data run.
Together, steps 2–4 cover the current test modules; no need to repeat the whole
suite immediately afterward.

## 5. Run a small real-data smoke check

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from isd.config import Config; from isd.pipeline import run; run(Path.cwd(), Config(max_customers=100, sample_scope='cohort', n_lr_models=2, n_disagg_cycles=2, checkpoint=False), output_dir=Path('outputs/smoke'))"
```

This still reads/audits the input file, but models at most 100 full-coverage
customers with fewer iterations. Expect a `Completed ...` message. Inspect
`outputs/smoke/run_manifest.json` for `model_diagnostics.fallback_reason`: a
completed export can contain uniform fallback, so completion alone does not
prove ISD ran. Inspect the peak summary, CSVs and three weather SVGs. The
standalone verifier targets `outputs/`, not this smoke subdirectory.

## 6. Run all customers

In `run_pipeline.py`, keep `max_customers=None` and choose:

- `peak_mode='population'`: one shared population peak date; existing two-column CSV.
- `peak_mode='individual'`: each customer's own maximum and Gregorian `peakDate`.

Keep `resume=False` (the Config default) for this fresh run. Do not change
`production` just to process all customers; it controls semantic confirmation,
not dataset size. Keep the configured 10 outer fits and 10 cycles per fit.

Run the file in the IDE, or:

```powershell
.\.venv\Scripts\python.exe run_pipeline.py
```

Do not pass `--config` unless intended: JSON replaces the IDE CONFIG, and missing
fields use Config defaults, including a 1,000-customer limit.

This selects all customers with usable identifiers and retains their histories.
Only accepted bills are allocated. Full-coverage customers enter cohort ISD;
other accepted bills receive uniform fallback. Quarantined internal-gap customers
remain unavailable. Population peak mode requires at least one full-coverage
customer; individual mode does not.

Memory and disk needs depend on bill counts and interval lengths. Ingestion is
chunked but combines normalized records in memory; file-backed allocations do
not eliminate solver copies. Large daily exports and checkpoints need disk space.
There is no reliable runtime estimate from the recent focused checks.

## 7. Verify the completed full output before changing code

```powershell
.\.venv\Scripts\python.exe scripts/verify_peak_outputs.py
```

Expected: a JSON report with `"passed": true`, also saved to
`handoff/peak_final_verification.json`. It checks the mode stored in the manifest.
Use normal Python, without `-O`, because this script uses assertions. Keep source
files/configuration unchanged between generation and verification: the verifier
checks the source fingerprint.

Eyeball `outputs/peak_summary.md`, `customer_peak_consumption.csv`,
`peak_missing_reasons.csv`, and `weather_plots/`. In individual mode dates can
differ; ties use the earliest day. Missing values/dates are blank; zeros are
numeric. Review manifest audit and fallback counts as well.

To try the other mode, first verify and preserve any results you want, change
`peak_mode`, and repeat steps 6–7. The next run replaces outputs. Old checkpoints
are not interchangeable across configuration changes.

## Optional: synthetic experiment report

```powershell
.\.venv\Scripts\python.exe -c "from isd.experiments import synthetic_experiment; print(synthetic_experiment().to_string(index=False))"
```

Expected: 12 rows (four scenarios × three methods), not a pass/fail result.
ISD is not required to outperform every baseline in every scenario.

If anything fails, send: step/command, full traceback, peak mode and configuration,
and whether this was a test, smoke run, full run or verifier. For a failed run,
also report whether a new run_manifest.json was created. Preserve failed outputs
until we diagnose the issue; do not send raw customer data unnecessarily.
