# Local full interval ISD pipeline

This implementation produces provisional, retrospective daily estimates from complete bill intervals. It contains a readable Section 3 reference engine and an explicitly different balanced-cohort adaptation. The default customer output mixes cohort ISD, uniform full-interval fallback and null missing days. No independent local daily consumption truth was supplied, and no measured daily accuracy is claimed. The full available dataset is now supported for provisional peak export; production semantic gates remain closed.

## Run from an IDE

Open `D:/work/repo/run_pipeline.py`. Select `D:/work/repo/.venv/Scripts/python.exe` as the interpreter, edit `CONFIG` and `OUTPUT_DIRECTORY` near the top, and click Run. No PowerShell commands are needed. Default execution uses every customer in the available full billing file, with alpha=0.05 and 10 regression iterations x 10 shifting cycles. It reads the full CSV as the source of truth and retains every bill of the selected subscriptions. It never combines the prefix file with the full file.

The optional CLI is `python run_pipeline.py --config configs/pilot.json --output outputs/my_pilot`. Paths passed on the CLI are relative to your working directory; the IDE default root is the script directory. `configs/paper_reference.json` preserves the five-column Section 3 example and fits every domain day. `configs/cohort_pilot.json` selects 10,000 members by hash within the balanced cohort. Separate boundary and wind-feature sensitivity configurations are registered. The provisional intended year is 1403; its tested mapping yields a 60-day target. Confirmation flags remain false.

For another Python installation, install pinned dependencies with `python -m pip install -r requirements.txt`. Python 3.12 was tested. The local environment inherits bundled numpy/pandas and has project-local Arrow, Numba, calendar, test and memory tools. Requirements pin all mathematical/calendar dependencies; the review bundle excludes the environment. Run tests with `python -m pytest tests -q`. Reproduce the review with `python scripts/execute_review.py`; this runs synthetic tests first, and then pilots/benchmarks, never full production.

## Inputs, decisions and stages

Raw `data/` is read-only by convention and ignored by Git. Physical CSV row 2 is the first data record. Bills have exactly seven columns, UTF-8 BOM and Gregorian ISO text dates; IDs are string values. Bill identity is SHA256(source file hash + ':' + physical row). A strict single-line-record adapter prevents incorrect multiline row provenance. Raw date, consumption and metadata text are retained. Invalid records, ambiguous within-customer overlaps, and gaps between accepted bills that intersect the target dates quarantine that entire customer's model (target gaps use reason `internal_target_gap`). Missing coverage only before the first bill or after the last bill remains partial coverage. Gaps entirely outside the target do not trigger this rule; no credit, correction, extra meter or missing bill is inferred. Exact duplicates require explicit audit confirmation before removal; the current source has none.

Stages are import and audit; UTC weather inspection; local-day linear point integration; frozen population and exposure selection; full-interval allocation; bill reconciliation; target export. An input hash change causes fresh structural auditing and is recorded rather than forcing old counts. Accepted bills extend the full domain beyond the target. Weather must cover every modeled interval and UTC points bracketing Tehran midnight. No extrapolation or weather-gap filling occurs.

Cohort adaptation fits only the fixed, fully covered target cohort on complete target days, with centered/scaled intercept + HDD65 features and exposure-scaled predictions outside the target. Paper reference uses unscaled intercept/HDD65/HDD55/HDDW65/CDD65 and all domain days. Both engines perform the same sequential Eqs.20-23 update for the chosen mode. A rank/count/condition gate failure in the adaptation falls back uniformly for the entire cohort. Reference retains deficient SVD minimum-norm fits with explicit diagnostics. Recorded-zero bills stay exactly zero; missing customer-days stay null. A zero residual sum keeps the current allocation unchanged and increments a no-op counter.

Checkpointing saves only completed cycles to `checkpoint.npz`, atomically replacing the previous checkpoint. Set `CONFIG.resume=True` with the same input, mathematical configuration, output directory and checkpoint. The saved fixed prediction is restored without refitting inside that outer iteration. Changed mathematical inputs are rejected. Memmaps are used when allocation values exceed the configurable size threshold; fallback bills remain compact until export. Storage chunk sizes do not change canonical visit order or split the population into models.

## Outputs

Daily weather plots are saved automatically in each run's `weather_plots/` folder as `temperature_mean_C.svg`, `apparent_temperature_mean_C.svg`, and `wind_mean_kmh.svg`. They show only the configured target dates (end excluded), with unavailable days left as gaps. Open the SVG files in a browser. Direct callers can enable this with `daily_integral(..., plot_directory=..., target_start=..., target_end_exclusive=...)`; the returned daily table is unchanged. `save_daily_weather_plots()` can also plot an existing daily table without rerunning integration or the solver.

Each output directory contains `normalized_bills.parquet` with raw provenance and the audit ledger; `daily_weather.parquet`; `full_bill_daily.parquet`; `bill_reconciliation.parquet`; `target_customer_daily.parquet`; and `aggregate_daily.parquet`. Small `aggregate_daily_summary.csv`, `baseline_comparison.csv`, `iteration_summary.csv`, `run_summary.csv` and `run_manifest.json` support inspection. Every selected customer has all 60 requested dates, including nulls. Target and full-interval totals are checked independently.

Bulk files and checkpoints remain on this machine and are excluded from the review ZIP. Aggregate CSVs contain no customer IDs. Reference and optimized equality, wall time, process RSS and profile evidence appear in `handoff/implementation/`. Review fixtures replace IDs and retain bill relationships; they are examples, not representative data, and are not production inputs. The discontinuous weather fixture is intentionally not a complete weather export.

The uniform baseline is B/L on the full interval. The weather-weighted baseline is B*(1+HDD65)/sum_interval(1+HDD65), with fixed baseload weight 1 and HDD coefficient 1. It is a comparison choice, not ISD or a fitted customer model. The last aggregate OLS prediction is non-reconciled and retained as a diagnostic. Real-data comparisons are shape differences and sensitivity, never measured daily error. Known synthetic truth is scored separately.

## Production boundary

A production claim requires confirmed year, endpoint, calendar/day basis, consumption units and weather processing, plus the documented rank/coverage/correctness gates. Config rejects `production=True` while those mandatory flags remain unresolved. Simply setting `max_customers=None` would request full exploratory data, not scientifically validated production; the current user request authorizes this full exploratory scope. Reconciliation proves bill accounting, not customer daily accuracy. See `handoff/implementation/algorithm_specification.md` and `recorded_decisions.md` for paper conflicts, policies and scientific limitations.

## Final daily peak export

Choose `peak_mode='population'` (default) or `peak_mode='individual'` in the
`run_pipeline.py` CONFIG; JSON configs accept `"peak_mode": "individual"` too.
Individual mode writes `SubscriptionNumber,peakCosumptionValue,peakDate` to
`customer_peak_consumption.csv`. Each customer uses their highest available
target-day estimate, with earliest-date tie breaking. Dates are Gregorian
`YYYY-MM-DD`. Partial coverage uses available days only; customers with no
available estimate have blank value and date, with reasons in
`peak_missing_reasons.csv`. Valid zeros remain numeric. Individual mode needs
no full-coverage cohort and does not produce `peak_daily_totals.csv`; its summary
and manifest describe individual maxima, not a simultaneous population total.
Population mode retains the existing two-column CSV and the policy below.

`python scripts/verify_peak_outputs.py` independently checks the files in
`outputs/` using the peak mode recorded in `run_manifest.json`. Individual mode
checks each customer's maximum value, earliest tied date, missing reasons and
manifest counts; population mode checks the shared peak-day export. Verification
also checks full-bill reconciliation and requires the current source fingerprint
to match the run manifest. It writes `handoff/peak_final_verification.json`.

Run `run_pipeline.py` in the IDE with its default CONFIG, or use `--config configs/peak.json --output outputs`. All input customer histories are allocated over complete billing intervals before extracting the established 60-day target. The fixed population with valid billing coverage throughout that target selects the largest daily total, using compensated float64 summation and earliest-date tie breaking. Every input customer is exported on that same date; partial customers retain their existing uniform full-bill estimates where covered, otherwise a blank. Valid zeros remain zero.

`outputs/customer_peak_consumption.csv` has exactly `SubscriptionNumber,peakCosumptionValue`. IDs remain strings; values use shortest round-trip float64 decimal text without fixed-decimal rounding. `peak_missing_reasons.csv` records missing estimates separately. `peak_daily_totals.csv`, `peak_summary.md` and `run_manifest.json` record the population, reconciliation, configuration and hashes. This is a modeled cohort peak, not a complete city or measured daily peak. See `handoff/peak_review_resolutions.md` for the three required review fixes and verification.
