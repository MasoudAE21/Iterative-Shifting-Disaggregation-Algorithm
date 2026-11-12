## Final-run defaults

For the final **city** run, edit `configs/city_final.json` and use
`scripts/city_workflow.py preflight`, `pilot`, `run`, or `reports`.
See [CITY_WORKFLOW.md](CITY_WORKFLOW.md) for configuration fields, exact commands,
peak definitions and reusable report extraction without another simulation.

The IDE entry point and `configs/town.json` now use selected configuration
`town_summer95_ref_0p1__g013` and individual peak export. For a timestamped Town_Q
run with metrics and profiles, use `configs/final_town_q_experiment.json` with
`scripts/run_hyperparameter_experiments.py`. See [FINAL_RUN_PLAN.md](FINAL_RUN_PLAN.md)
for the Town_Q acceptance checks, city input requirements and presentation outputs.
Older run recipes below describe their historical settings.

## Accepted-run customer reports

Run `python scripts/export_customer_reports.py --config configs/customer_reports.json`
to extract reports from `experiment_all_types_05` without rerunning or changing
its allocations. Settings select December 2024–February 2025 and the entire
simulation. Results go into that run's `customer_reports/` subdirectory.
Each window has `customers_on_town_peak_day.csv`, `individual_customer_peaks.csv`,
and `population_daily_totals.csv`. The shared peak uses the accepted run's fixed
full-target coverage cohort in both windows, not a changing daily population.
Individual peaks use available days and include coverage counts; ties choose the
earliest date. Missing estimates remain blank, and numeric zeros remain zero.
The report manifest records dates, counts, units, and source hashes. Requested
windows outside the saved target customer-day grid are rejected.

Every selected customer's daily estimates already exist in
`target_customer_daily.parquet`, including unavailable days and method/status
fields. Set `export_customer_daily_csv` to `true` in the report config to also
write monthly CSVs under `customer_reports/customer_daily_csv/`; set it to
`false` to skip them (and remove previous monthly files owned by that exporter).
The option is also available in pipeline `Config`, JSON overrides, and the IDE
CONFIG in `run_pipeline.py` (default false). Pipeline CSVs go into
`customer_daily_csv/` in the run directory and cover its target dates. Parquet is
always retained. Monthly splitting keeps this Town run below Excel's row limit;
import SubscriptionNumber as text to preserve leading zeros. These are modeled
estimates for selected customers, not measured daily values for missing consumers.

## Current weighted partial-bill policy

Town now uses `monthly_weighted` for January 2–February 28, 2025. For each partial bill:

`adjusted consumption = original consumption * target overlap days / sum(original daily weights)`

Calendar-month weights: January, February, December = 1; November = 0.55; October = 0.2; March = 0.57; all others = 0.1. January 1 contributes weight 1 to the denominator but is outside the target numerator. Fully contained bills remain unchanged. The configured original bill-duration limit still applies before adjustment.

The normalized ledger records `original_weight_sum`, `target_day_count`, and the multiplier in `retained_fraction`, preserving original consumption. Reconciliation uses adjusted consumption. Town JSON's existing hyperparameters and 150-day limit are preserved. The standalone raw-bill uniform script is unaffected.

## Current Town boundary policy

`python run_pipeline.py --config configs/town.json` now runs only January 2–February 28, 2025 (58 days), saving to `outputs/town/`.
The `clip_preserve_total` policy clips overlapping bill dates to the target but keeps their full consumption unchanged. For example, a 1000 m3 bill overlapping 20 target days allocates all 1000 m3 across those 20 days. Bills with no overlap are excluded. The existing original-duration limit of 100 days and source audit rules remain in force.

Original dates and totals remain in the normalized bill ledger. Reconciliation uses the unchanged bill total; `window_action=clipped_preserved_total` identifies clipped bills. The daily comparison CSV now covers the same 58 days. No partial-bill consumption adjustment is applied. Start a fresh run (`resume=false`) when changing policies. The independent raw-bill uniform script remains unchanged.

Earlier configurations are documented below for reference.

## Town configured run

New runs default to `outputs/town/` (override with `--output`).
`simulation_daily_comparison.csv` contains every simulation date and four columns:
`date_gregorian`, `tbs_daily_m3`, `total_uniform_consumption_m3`, and
`final_algorithm_consumption_m3`. Uniform totals distribute each retained bill
uniformly over its effective interval; final totals combine ISD allocations and
existing fallback allocations. Missing TBS measurements stay blank. The separate
`tbs_daily_comparison.csv` still covers only the target comparison period.


Run `python run_pipeline.py --config configs/town.json`. IDE defaults use the same Town settings. Simulation spans November 1, 2024 through March 31, 2025; comparison and target exports span January 2 through February 28, 2025. Weather must cover every simulation day. Bills exceeding 100 original inclusive days are excluded; remaining bills intersecting the simulation are retained and prorated by retained days / original days. Source audit exclusions still apply.

Edit `configs/town.json` to change `n_lr_models`, `n_disagg_cycles`, dates, and bill limits. Edit `isd/town_features.py:town_features` to try weather features; return named arrays with an intercept first. The pipeline scales features using fit dates. The existing cohort model fits on the target period and allocates across the simulation. Start a fresh run after feature changes.

At completion, `tbs_daily_comparison.csv` contains all 58 comparison dates, customer aggregate and coverage columns, TBS consumption, and differences. `run_manifest.json` records matched-day totals, bias, MAE, RMSE, and TBS provenance. Missing station dates remain missing; totals use matched days. Customer totals include available support and uniform fallback, so incomplete coverage can affect comparison with the whole station. Inputs default to the Town prepared bills, prepared weather, and prepared TBS report.

The historical workflow notes below describe earlier configurations.

# Local full interval ISD pipeline

This implementation produces provisional, retrospective daily estimates from complete bill intervals. It contains a readable Section 3 reference engine and an explicitly different balanced-cohort adaptation. The default customer output mixes cohort ISD, uniform full-interval fallback and null missing days. TBS daily consumption is available for aggregate validation; the pipeline does not yet score against or adjust TBS. The full available dataset is now supported for provisional peak export; production semantic gates remain closed.

## Run from an IDE

Open `D:/work/repo/run_pipeline.py`. Select `D:/work/repo/.venv/Scripts/python.exe` as the interpreter, edit `CONFIG` and `OUTPUT_DIRECTORY` near the top, and click Run. No PowerShell commands are needed. Default execution uses every customer in the available full billing file, with alpha=0.05 and 10 regression iterations x 10 shifting cycles. It reads the full CSV as the source of truth and retains every bill of the selected subscriptions. It never combines the prefix file with the full file.

The optional CLI is `python run_pipeline.py --config configs/peak.json --output outputs/town`. This config and the IDE defaults use the confirmed January 2–February 28, 2025 target (58 inclusive days). Bill endpoints, m3 units, local station days, and the target year are confirmed. Production remains provisional. Use `configs/smoke.json` for a 100-customer, two-fit/two-cycle check. JSON values override the current IDE CONFIG; omitted settings retain the current daily-weather defaults. See `VALIDATION_GUIDE.md` for manual tests, smoke, and analysis.

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
`outputs/town/` using the peak mode recorded in `run_manifest.json`. Individual mode
checks each customer's maximum value, earliest tied date, missing reasons and
manifest counts; population mode checks the shared peak-day export. Verification
also checks full-bill reconciliation and requires the current source fingerprint
to match the run manifest. It writes `handoff/peak_final_verification.json`.

Run `run_pipeline.py` in the IDE with its default CONFIG, or use `--config configs/peak.json --output outputs/town`. All input customer histories are allocated over complete billing intervals before extracting the confirmed 58-day target. The fixed population with valid billing coverage throughout that target selects the largest daily total, using compensated float64 summation and earliest-date tie breaking. Every input customer is exported on that same date; partial customers retain their existing uniform full-bill estimates where covered, otherwise a blank. Valid zeros remain zero.

`outputs/town/customer_peak_consumption.csv` has exactly `SubscriptionNumber,peakCosumptionValue`. IDs remain strings; values use shortest round-trip float64 decimal text without fixed-decimal rounding. `peak_missing_reasons.csv` records missing estimates separately. `peak_daily_totals.csv`, `peak_summary.md` and `run_manifest.json` record the population, reconciliation, configuration and hashes. This is a modeled cohort peak, not a complete city or measured daily peak. See `handoff/peak_review_resolutions.md` for the three required review fixes and verification.
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

## Current full-year Town experiment

The IDE/CLI defaults and `configs/town.json` now use **December 1, 2023–April 30, 2025 inclusive** (517 days). `target_end_exclusive` and `simulation_end_exclusive` are `2025-05-01`. The requested November start was moved to December 1 to match available weather.

The entry point reads `bill_Customers_Town_Q_full_year.csv` and `open-meteo-2024-25.csv` from `data/prepared`. Bill columns are mapped by header name, M/D/YYYY dates are parsed explicitly, and original source values remain in `raw_*` fields. Legacy ISO inputs require `bill_date_format: "%Y-%m-%d"` when overriding the bills.

- Bills wholly inside the window retain their full totals, including bills longer than 150 days.
- Bills partly inside the window are excluded only if their original inclusive duration exceeds 150 days.
- Remaining partly included bills use `Consumption × sum(retained daily month weights) / sum(full-bill daily month weights)` and are clipped to the window.
- Bills wholly outside the window are excluded. `bill_duration_scope: "boundary"` selects this behavior; `"all"` retains the legacy global duration cap.

The weighted formula now uses month weights in both numerator and denominator; it applies correctly beyond January/February. The existing `MONTH_WEIGHTS` in `isd/bill_window.py` are unchanged. Original bill totals and adjusted reconciliation totals are recorded separately.

```powershell
# Check the full source and resulting coverage without fitting.
.\.venv\Scripts\python.exe scripts/check_town_setup.py
# Run the full experiment, with a separate output folder for each variant.
.\.venv\Scripts\python.exe run_pipeline.py --config configs/town.json --output outputs/experiment_01
# Quick check using 100 fully covered customers and two fits/cycles.
.\.venv\Scripts\python.exe run_pipeline.py --config configs/smoke.json --output outputs/town_full_year_smoke
```

Edit `alpha`, `n_lr_models`, and `n_disagg_cycles` in a copy of `configs/town.json` for hyperparameter trials. Keep `resume: false` for changed experiments. For the IDE, edit `CONFIG` in `run_pipeline.py`; a supplied JSON overrides those values. The default destination is `outputs/town_full_year`.

Edit `town_features(daily)` in `isd/town_features.py` to test weather features. Available columns are `temperature_mean_C`, `apparent_temperature_mean_C`, and `wind_max_kmh`. The current function uses apparent temperature; replace its temperature assignment with `daily.temperature_mean_C.to_numpy(dtype=float)` to experiment with air temperature. Keep the intercept first. `daily_apparent_hdd65_v1` and `intercept_only_v1` provide simpler preset baselines. Maximum wind remains a distinct statistic from mean wind.

Each run writes `weather_features.csv`: one row per modeled day, with the date, available temperature/wind inputs, weather status, and active model features (including the intercept). Feature values are exported before standardization and exposure scaling; the scaling parameters remain in `run_manifest.json`. Custom feature edits automatically change the exported feature columns.

Use `moving_average(values, n)` in `isd/town_features.py` for trailing weather features. It averages today and the preceding `n-1` days; the first `n-1` days use their own daily value. Inputs must be in consecutive daily order. For example, enable `"temp_ma7": moving_average(temperature, 7)` or `"HDD65_ma7": moving_average(hdd65, 7)` in the feature dictionary. These examples are initially commented out so you can choose the window and feature combination for your next experiment. The resulting feature is exported and standardized like other custom features.

Inspect each run's `run_manifest.json`, `iteration_summary.csv`, and `simulation_daily_comparison.csv`. A null `model_diagnostics.fallback_reason` confirms that fitting ran. The source snapshot records feature code and configuration for reproducibility. A sampled smoke run is only a code check and is not comparable in volume to the entire station.

`simulation_daily_comparison.csv` includes `included_customer_fraction`: customers with accepted bill coverage on that day divided by the distinct full Town roster (9,298 customers in the current file). Values range from 0 to 1; zero-consumption and uniform-fallback customers count as included, while excluded/uncovered customers do not. Runs without a roster use their selected run population, and the manifest identifies the denominator. This differs from `aggregate_daily_summary.csv`'s existing `coverage_fraction`, whose denominator is the selected run population.

The checked full inputs give 579 excluded boundary bills, 16,593 weighted boundary bills, 8,423 full-period customers, and a minimum of 8,615 active bills after filtering. TBS is missing for December 2023 (31 days) and is zero on April 30, 2025. Missing TBS days stay missing; the current error summary includes the recorded zero. Report or separately assess that zero when comparing experiments. Earlier target-specific examples/counts in this README describe historical configurations.

## Two-branch hyperparameter experiments

Run both experimental methods with one editable config:

```powershell
.\.venv\Scripts\python.exe scripts/run_hyperparameter_experiments.py --config configs/hyperparameter_experiments.json
```

The initial config uses the full customer population, 5 LR models, 5 disaggregation cycles per model, and alpha=0.05. Change `shared_parameters` for both methods, or `models[].parameters` for one method; model parameters override shared values. Other Config fields can also be added to those dictionaries. To compare several setups in one invocation, add model entries with distinct names and parameters; multiple entries may use the same branch. Each model inherits its branch's `run_pipeline.CONFIG`, and its complete effective configuration is saved as `resolved_config.json`. `tbs_fourier_harmonics` is the Fourier order p (initially 5 on the Fourier branch); it is inactive for the seasonal method. The annual period is `tbs_fourier_period_days`. The other exposed defaults are a 0.10 redistribution floor, 0.03 reference strength, and 1.0 Fourier customer ridge penalty.

The three shared parameters `n_lr_models`, `n_disagg_cycles`, and `alpha` accept either a scalar or a nonempty list. Lists run every combination (Cartesian product) for each model entry. For example, inside `shared_parameters`:

```json
"n_lr_models": [5, 10],
"n_disagg_cycles": [5, 10],
"alpha": [0.01, 0.05]
```

This creates 8 combinations per branch, or 16 model runs for the two configured branches. The supplied config uses `[5]`, `[5]`, and `[0.05]`, preserving the original two-run workload. Other shared hyperparameters and all model-specific parameters still require scalars. Model-specific scalars override the shared grid for that model; duplicate choices are removed. Counts must be positive integers, and alpha must be finite and between 0 and 1.

Preview the expanded runs without starting simulations or creating output folders:

```powershell
.\.venv\Scripts\python.exe scripts/run_hyperparameter_experiments.py --config configs/hyperparameter_experiments.json --dry-run
```

Multi-combination runs use distinct folders such as `seasonal_reference_combined__g001`. `experiment_plan.json` maps each run name to its exact scalar parameters, and the combined `metrics.csv` includes those values for comparison. Single-value setups keep their existing model folder names. All combinations in a batch use the same selected customer sample.

Each invocation creates a new timestamped folder in `outputs/hyperparameter_experiments`, preserving previous trials. It reads committed snapshots of the configured local branches without switching branches; arbitrary uncommitted scientific-code edits are excluded. For `coverage_policy: "observed_support_isd_v1"`, it applies the common fix in `patches/observed_support_isd.patch` to older snapshots of both branches. The exact patch and its SHA256 are saved alongside the base commit; modified scientific source is included in the run's source fingerprint. Branch names can also be pinned to commit hashes. Snapshots, commit IDs, the runner, input hashes, full effective configs, terminal logs, and customer random seed are retained. The working checkout only needs this runner, its config, and the policy patch; it does not need to be switched between methods.

The experiment config now uses `observed_support_isd_v1`: partial customers enter ISD on their accepted bill periods, and internal or edge gaps remain unavailable. Daily exposure uses the number of supported modeled customers on each day divided by the modeled population; regression fits complete-weather days with nonzero exposure. This changes the fitting population and assumes comparable average response across changing customer support, so scores should be compared separately from the older balanced-cohort runs. Conflicting/overlapping, duplicate, or invalid histories remain quarantined. The original `balanced_cohort_uniform_elsewhere_v1` policy is still available and remains the library default.

Every new experiment independently verifies that each saved allocation belongs to the bill's customer, lies inside both the effective and original source bill dates, appears exactly once per bill-day, and conserves its effective bill total. Window clipping/proration follows the existing configured boundary policy; it never assigns a bill's consumption to dates outside that bill.

`metrics.csv` compares MAPE (%), RMSE (m3/day), R2, and Pearson correlation (`pearson_r`) for November 15, 2024 through March 15, 2025 inclusive, and the entire configured simulation. Each window has separate scores against measured TBS and 0.75 times TBS, controlled by `truth_scales: [1.0, 0.75]`; predictions stay unchanged. Rows identify their `truth_scale` and `truth_reference`. April 29 and 30, 2025 are excluded from metrics only. Missing measurements/predictions are omitted as pairs and counted; measured zeros are excluded from MAPE only. Constant/insufficient TBS yields an undefined R2; Pearson is undefined if either paired series is constant or fewer than two pairs exist. Positive scaling of TBS leaves Pearson unchanged. `metric_daily_pairs.csv` exposes the dates, truth series, and inclusion flags. Fourier uses TBS as an input, so its scores are in-sample reconstruction diagnostics; truth scaling affects evaluation only.

The 12 fixed customers plus 5 randomly chosen additional customers are shared across methods in a trial. A null `random_seed` selects a new sample per invocation; set an integer to repeat it. `customer_selection.json` records the actual seed and IDs. `customer_daily_estimates.csv` contains their complete daily grids, keeping unavailable consumption blank. Its `uniform_consumption_m3` column uses each accepted effective bill's total divided by its bill days, including the run's boundary adjustments. `customer_profiles_comparison.png` overlays both methods and a grey uniform bill-allocation baseline; each model also has its own profile plot and CSV with that baseline. `aggregate_tbs_comparison.png` shows both truth scales. `report.md` summarizes the experiment. Full bill conservation, finite/nonnegative allocations, reserve-floor compliance, matching effective ledgers, and completion of the requested cycles are checked for new simulations before `completion.json` is written.

To update only the reports for an existing completed batch, preserving its saved allocations and random customer selection:

```powershell
.\.venv\Scripts\python.exe scripts/run_hyperparameter_experiments.py --reports-only outputs/hyperparameter_experiments/20261108T082633Z_65845009
```

This reads the batch's saved `experiment_config.json` and reuses its previous allocation audit without repeating model fitting.

## Data organization

- `data/raw/`: original database exports, original customer workbook, historical regional bills, and `TBS_Town_Q_daily_raw.tab`.
- `data/prepared/`: current Town bills and customer roster, weather input, and `TBS_Town_Q_daily_consumption.csv`. These are the inputs under evaluation.
- `outputs/town_full_year/`: default destination for new algorithm results. The entry point's default bill input is `data/prepared/bill_Customers_Town_Q_full_year.csv`.

Reference PDFs and documents are in `references/`. Analysis reports are regenerated in `outputs/town_analysis/`. Generated results were cleared for the next manual run; three access-denied test directories remain, as recorded in `REPO_CLEANUP.md`.

Generate daily TBS consumption with `python scripts/extract_tbs_daily.py`. Its defaults read the raw station file and write the prepared CSV. The existing prepared `.tab` export is retained as an alternate copy; the analysis reads the CSV.

Run the Town audit, report and interval plot with `python scripts/run_town_analysis.py`. Run the algorithm with `python run_pipeline.py`. Explicit `--bills` and `--output` overrides remain available. Follow `VALIDATION_GUIDE.md` for the manual test/smoke/analysis sequence.

The default weather source is `data/prepared/open-meteo-2024-25.csv`; override it with `--weather PATH`. Its daily mean air temperature, mean apparent temperature, and maximum wind are retained in daily exports and plots. Current model presets continue to use apparent temperature; reading air temperature does not silently change the fitted features. The earlier two-variable daily format remains supported.

Generate a daily uniform allocation from **every row** in the corrected full-year bill file:

```powershell
.\.venv\Scripts\python.exe scripts/town_uniform_daily.py
```

This writes `outputs/town_uniform/full_year_daily_uniform.csv`, with `date`, `number_of_bills` (active bill rows), `number_of_customers` (distinct customers with active bills), and `uniform_consumption` (m3/day). Each bill contributes `Consumption / (ToDate - FromDate + 1)` on every inclusive bill date. No weather, duration, target-window, or population filtering is applied. Overlapping/duplicate rows count independently toward bill count and consumption; customers count once per day. Zero-support dates between the first and last bill dates are retained. ISO and explicit M/D/YYYY source dates are supported. Use `--bills PATH --output PATH` for other files.

### Customer summer floors

The Town entry point (`run_pipeline.py`) and `configs/seasonal_reference_combined.json` enable customer summer floors. Settings can be overridden in the run JSON:

```json
{
  "customer_summer_floor": true,
  "summer_floor_fraction": 0.95,
  "summer_min_covered_days": 30,
  "summer_fallback_fraction": 0.10,
  "divide_consumption_by_unit_count": false
}
```

Summer is June 1 through September 30, inclusive, in the Gregorian calendar. For accepted, effective bills after date-window adjustments, the baseline is `sum(summer_overlap_days * Consumption / day_count) / sum(summer_overlap_days)`. Available summers are pooled. Audited customer histories do not overlap; missing days are excluded and recorded zero bills count as covered days. Bills crossing a summer boundary contribute only their summer overlap, using their full effective bill's uniform daily consumption.

With at least `summer_min_covered_days`, the requested daily floor is `summer_floor_fraction * customer_baseline`. Otherwise it is `summer_fallback_fraction * bill_daily_average`. Each bill's effective floor is capped at its own daily average, preserving bill totals and zero bills. The solver reserves this floor on every supported day and distributes the remaining bill volume using residual weights. Seasonal initialization and reference correction use the same floor. A bill clipped to its average becomes uniform. Uniform allocation fallbacks also satisfy these floors. Disable `customer_summer_floor` to use the legacy `redistribution_floor`; the low-level `Config()` retains this disabled default for reference-method compatibility.

`normalized_bills.parquet` records `summer_covered_days`, `summer_daily_baseline`, `daily_floor`, `floor_source`, and `floor_feasibility_adjusted`. `aggregate_daily_summary.csv` and `simulation_daily_comparison.csv` include `total_floor_consumption_m3`, the sum of feasible bill floors on each date across accepted, selected customer support, including uniform fallback bills. Unsupported dates outside the exported aggregate domain remain missing in the comparison file.

When `divide_consumption_by_unit_count` is true, accepted bill consumption is divided by that bill's positive integer `UnitCount` before date-window adjustments, baseline calculation, solving, and export. Raw source fields and `consumption_before_unit_normalization` preserve the original values. Invalid unit counts stop the run. Reconciliation then conserves normalized effective bill totals. Export column names are retained for compatibility, but modeled totals are sums of per-unit consumption, not physical town consumption. The run manifest records this basis, and station bias/MAE/RMSE are omitted because physical TBS totals are not directly comparable. Capacity constraints are not applied.

### Grid search with the customer summer floor

Run the six-combination full-town grid from the `codex/customer-floor-vs-share-cap` checkout:

```powershell
.\.venv\Scripts\python.exe scripts/run_hyperparameter_experiments.py --config configs/summer_floor_grid.json --dry-run
.\.venv\Scripts\python.exe scripts/run_hyperparameter_experiments.py --config configs/summer_floor_grid.json
```

This holds the summer fraction at 0.95, minimum coverage at 30 days, fallback at 0.10, and UnitCount normalization off. It varies alpha over `[0.00001, 0.00002]` and reference strength over `[0.1, 0.2, 0.3]`, with 10 LR models and 3 sweeps per model. Edit the shared grid lists or model scalar settings in `configs/summer_floor_grid.json` for other combinations.

The config explicitly selects `source: "working_tree"`. The runner freezes the current checkout's source, including uncommitted changes and new files, once at batch start; every working-tree model receives that same copy. The configured branch must be checked out. `working_source/working_tree_snapshot.json` records the base commit and per-file SHA256 hashes, and each run retains a copy. Existing configs continue using committed branch snapshots by default.

Each invocation writes a fresh timestamped batch under `outputs/summer_floor_grid`, with the same customer profile PNGs/CSVs, aggregate TBS comparison, metrics CSV/JSON, report, validation, and completion files as previous grid runs. The same 12 fixed plus 5 random customers are used across all six combinations. Winter/full-simulation windows, date exclusions, and TBS truth scales are copied from the prior experiment config. Every simulation comparison also retains the new total-floor column.
