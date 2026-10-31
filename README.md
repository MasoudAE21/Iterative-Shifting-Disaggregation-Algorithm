# Local full interval ISD pipeline

This implementation produces provisional, retrospective daily estimates from complete bill intervals. It contains a readable Section 3 reference engine and an explicitly different balanced-cohort adaptation. The default customer output mixes cohort ISD, uniform full-interval fallback and null missing days. TBS daily consumption is available for aggregate validation; the pipeline does not yet score against or adjust TBS. The full available dataset is now supported for provisional peak export; production semantic gates remain closed.

## Run from an IDE

Open `D:/work/repo/run_pipeline.py`. Select `D:/work/repo/.venv/Scripts/python.exe` as the interpreter, edit `CONFIG` and `OUTPUT_DIRECTORY` near the top, and click Run. No PowerShell commands are needed. Default execution uses every customer in the available full billing file, with alpha=0.05 and 10 regression iterations x 10 shifting cycles. It reads the full CSV as the source of truth and retains every bill of the selected subscriptions. It never combines the prefix file with the full file.

The optional CLI is `python run_pipeline.py --config configs/peak.json --output data/algorithm_output`. This config and the IDE defaults use the confirmed January 2–February 28, 2025 target (58 inclusive days). Bill endpoints, m3 units, local station days, and the target year are confirmed. Production remains provisional. Use `configs/smoke.json` for a 100-customer, two-fit/two-cycle check. JSON values override the current IDE CONFIG; omitted settings retain the current daily-weather defaults. See `VALIDATION_GUIDE.md` for manual tests, smoke, and analysis.

For another Python installation, install pinned dependencies with `python -m pip install -r requirements.txt`. Python 3.12 was tested. The local environment inherits bundled numpy/pandas and has project-local Arrow, Numba, calendar, test and memory tools. Run tests with `python -m pytest tests -q`. Historical review reproduction scripts require the original data/weather contracts and are not the current Town workflow.

## Inputs, decisions and stages

Raw `data/raw/` is read-only by convention and ignored by Git. Physical CSV row 2 is the first data record. Bills have exactly seven columns, UTF-8 BOM and Gregorian ISO text dates; IDs are string values. Bill identity is SHA256(source file hash + ':' + physical row). A strict single-line-record adapter prevents incorrect multiline row provenance. Raw date, consumption and metadata text are retained. Invalid records, ambiguous within-customer overlaps, and gaps between accepted bills that intersect the target dates quarantine that entire customer's model (target gaps use reason `internal_target_gap`). Missing coverage only before the first bill or after the last bill remains partial coverage. Gaps entirely outside the target do not trigger this rule; no credit, correction, extra meter or missing bill is inferred. Exact duplicates require explicit audit confirmation before removal; the current source has none.

Stages are bill audit; direct daily weather ingestion; frozen population and exposure selection; full-interval allocation; bill reconciliation; target export. The current weather export covers November 1, 2024–April 1, 2025 and supplies daily mean apparent temperature and daily maximum wind. Values are used directly, without hourly integration. GMT daily date labels are aligned to local station date labels as an explicitly accepted approximation; the winter boundary offset is 3.5 hours. Source timezone, elevation, variable meanings, and adapter version are recorded. No weather-gap filling occurs. The existing weather-bounded exclusion policy retains only complete bills within available weather dates.

The active feature preset is `daily_apparent_hdd65_v1`: intercept plus heating-degree values computed from daily mean apparent temperature. This is not the previous air-temperature HDD model. Maximum wind is retained and plotted, but never substituted into the mean-wind HDDW formula. Legacy hourly ingestion remains available only for historical inputs/tests.

Cohort adaptation fits only the fixed, fully covered target cohort on complete target days, with centered/scaled intercept + HDD65 features and exposure-scaled predictions outside the target. Paper reference uses unscaled intercept/HDD65/HDD55/HDDW65/CDD65 and all domain days. Both engines perform the same sequential Eqs.20-23 update for the chosen mode. A rank/count/condition gate failure in the adaptation falls back uniformly for the entire cohort. Reference retains deficient SVD minimum-norm fits with explicit diagnostics. Recorded-zero bills stay exactly zero; missing customer-days stay null. A zero residual sum keeps the current allocation unchanged and increments a no-op counter.

Checkpointing saves only completed cycles to `checkpoint.npz`, atomically replacing the previous checkpoint. Set `CONFIG.resume=True` with the same input, mathematical configuration, output directory and checkpoint. The saved fixed prediction is restored without refitting inside that outer iteration. Changed mathematical inputs are rejected. Memmaps are used when allocation values exceed the configurable size threshold; fallback bills remain compact until export. Storage chunk sizes do not change canonical visit order or split the population into models.

## Outputs

Daily weather plots are saved in `weather_plots/` as `apparent_temperature_mean_C.svg` and `wind_max_kmh.svg`. They show target dates with unavailable days left as gaps. No air-temperature or mean-wind plot is fabricated for the daily file. The shared weather adapter dispatches directly to daily date alignment for this input.

Each output directory contains `normalized_bills.parquet` with raw provenance and the audit ledger; `daily_weather.parquet`; `full_bill_daily.parquet`; `bill_reconciliation.parquet`; `target_customer_daily.parquet`; and `aggregate_daily.parquet`. Small `aggregate_daily_summary.csv`, `baseline_comparison.csv`, `iteration_summary.csv`, `run_summary.csv` and `run_manifest.json` support inspection. Every selected customer has all 58 requested dates, including nulls. Target and full-interval totals are checked independently.

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
`data/algorithm_output/` using the peak mode recorded in `run_manifest.json`. Individual mode
checks each customer's maximum value, earliest tied date, missing reasons and
manifest counts; population mode checks the shared peak-day export. Verification
also checks full-bill reconciliation and requires the current source fingerprint
to match the run manifest. It writes `handoff/peak_final_verification.json`.

Run `run_pipeline.py` in the IDE with its default CONFIG, or use `--config configs/peak.json --output data/algorithm_output`. All input customer histories are allocated over complete billing intervals before extracting the confirmed 58-day target. The fixed population with valid billing coverage throughout that target selects the largest daily total, using compensated float64 summation and earliest-date tie breaking. Every input customer is exported on that same date; partial customers retain their existing uniform full-bill estimates where covered, otherwise a blank. Valid zeros remain zero.

`data/algorithm_output/customer_peak_consumption.csv` has exactly `SubscriptionNumber,peakCosumptionValue`. IDs remain strings; values use shortest round-trip float64 decimal text without fixed-decimal rounding. `peak_missing_reasons.csv` records missing estimates separately. `peak_daily_totals.csv`, `peak_summary.md` and `run_manifest.json` record the population, reconciliation, configuration and hashes. This is a modeled cohort peak, not a complete city or measured daily peak. See `handoff/peak_review_resolutions.md` for the three required review fixes and verification.
# Town Q validation data

## Limit bill intervals to available dates

`run_pipeline.py` now defaults to `bill_boundary_policy='exclude'` and
`bill_window='weather'`. This prevents a multi-year bill from expanding the
solver domain beyond complete local weather days. The original input CSV is
never modified. Direct `Config()` calls and old JSON configs retain the legacy
`keep` default; set the new fields or CLI flags explicitly for those runs.

```powershell
# Preserve source totals; exclude any bill extending outside the weather window.
python run_pipeline.py --bills data/prepared/bill_Customers_Town_Q.csv --bill-policy exclude --bill-window weather --output outputs/town_q_exclude

# Clip bills to target days with weather, prorating by retained calendar days.
python run_pipeline.py --bills data/prepared/bill_Customers_Town_Q.csv --bill-policy prorate --bill-window target --output outputs/town_q_prorated
```

`--bill-policy` supports `keep` (original full intervals), `exclude` (only bills
fully inside the window), or `prorate` (retain intersections and multiply totals
by retained days / original days). Bills outside the window are excluded in
both bounded modes. `--bill-window weather` uses the contiguous complete local
weather range; `target` intersects that range with the configured target dates.
Internal weather gaps raise an error rather than silently bridging missing
weather. Source bill endpoints are inclusive; internal windows are half-open.
Thus retaining 10 days of a 100-day bill keeps 10% of its consumption.

Source validation/quarantine runs first and stays in force. Coverage and cohort
selection are recomputed after the boundary policy. Partially covered customers
still use the existing uniform fallback; no-coverage customer days remain null.
If no fully covered customers remain, population peak selection raises its
existing error. `keep` ignores the window setting and preserves old behavior.

`normalized_bills.parquet` preserves source IDs and `raw_*` fields and adds
`original_day_count`, `original_consumption`, `retained_fraction`, and
`window_action`. Effective dates and consumption drive the solver and bill
reconciliation. `run_manifest.json` includes a `bill_window` summary with the
effective bounds and excluded/prorated counts and volume totals. `source_audit`
still describes the original input. Resume compatibility includes these settings;
start a fresh run when changing policy.

Proration assumes uniform use over the original interval; it does not measure
the winter portion of a multi-year bill. Treat it as a sensitivity run, not
ground truth. Production mode rejects prorating. For validation, compare an
unmodified-total exclusion run against a prorated run and account for different
customer coverage. Obtaining weather covering ordinary boundary-crossing bills
can preserve more measured bill totals without prorating them.

On the current SQL town export, weather-bounded exclusion retains 1,975 fully
covered customers; prorating retains 8,935. Target-only exclusion retains no
fully covered customers, so population peak selection cannot run in that case.
These counts depend on the supplied data and configured target dates.

## Data organization

- `data/raw/`: original database exports, original customer workbook, historical regional bills, and `TBS_Town_Q_daily_raw.tab`.
- `data/prepared/`: current Town bills and customer roster, weather input, and `TBS_Town_Q_daily_consumption.csv`. These are the inputs under evaluation.
- `data/algorithm_output/`: default destination for new algorithm results. The default bill input is `data/prepared/bill_Customers_Town_Q.csv`.

Reference PDFs and documents are in `references/`. Analysis reports are regenerated in `outputs/town_analysis/`. Generated results were cleared for the next manual run; three access-denied test directories remain, as recorded in `REPO_CLEANUP.md`.

Generate daily TBS consumption with `python scripts/extract_tbs_daily.py`. Its defaults read the raw station file and write the prepared CSV. The existing prepared `.tab` export is retained as an alternate copy; the analysis reads the CSV.

Run the Town audit, report and interval plot with `python scripts/run_town_analysis.py`. Run the algorithm with `python run_pipeline.py`. Explicit `--bills` and `--output` overrides remain available. Follow `VALIDATION_GUIDE.md` for the manual test/smoke/analysis sequence.
