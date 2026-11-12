# Final Town_Q and city runs

Branch: `codex/final-town-q-city-g013`.
Status: Town_Q validation completed on `20261111T132937Z_180897bf`; its customer
daily estimates and metrics exactly reproduce g013. Town_Q is for comparison and
validation; the user handles its report extraction. City execution and reusable
reporting are implemented in `scripts/city_workflow.py` and `isd/city_reports.py`.
Use `configs/city_final.json` and [CITY_WORKFLOW.md](CITY_WORKFLOW.md) for steps 3-4.
The final full-city run awaits the user's updated data/configuration.

## Frozen selection

Reference: `outputs/summer_floor_grid/20261111T095842Z_672fc13f/town_summer95_ref_0p1__g013/resolved_config.json`.
The IDE entry point and `configs/town.json` match every reference setting except
the portable TBS path and `peak_mode=individual`, which changes the requested export.
Scientific settings: 5 LR models, 3 cycles, alpha 0.00001, uniform initialization,
observed-support coverage, reference strength 0.1, summer floor 0.95,
minimum 10 covered summer days, fallback fraction 0.1, redistribution floor 0,
no division by unit count, all input customers. Checkpoint/resume remain disabled
as in the selected run. Library Config defaults and legacy experiment configurations
are not changed; the application defaults and Town preset carry this selection.

## 1. Final Town_Q run

Use the same full-year Town_Q bills and weather as the selected experiment,
December 1, 2023 through April 30, 2025 inclusive. Preserve its bill-boundary
handling and 150-day boundary-bill limit. Record input hashes, source snapshot,
resolved configuration, effective bill ledger and selected profile customers.

Preferred command (one configuration, timestamped output, metrics and plots):

```powershell
.venv/Scripts/python.exe scripts/run_hyperparameter_experiments.py --config configs/final_town_q_experiment.json
```

The fixed seed 20261111 makes the additional profile sample repeatable. The 12
specified customers remain fixed. Outputs go under
`outputs/final_town_q/<timestamp>/town_q_final_g013`; the batch root contains
comparison plots, metrics, validation and completion records.
Do not also run the IDE entry point for this same deliverable: that is an alternative
route to `outputs/final_town_q_g013`, without the experiment reporting bundle.

Acceptance: all 15 sweeps complete; no solver fallback; finite, nonnegative
estimates; bill conservation within configured tolerance; no outside, duplicate
or missing accepted bill-days; summer floors respected; unavailable days remain
blank. Compare daily allocations and aggregate metrics with the selected g013
artifact, explaining any difference before accepting. Export-mode changes should
not change allocations. Reference 0.75 x TBS results: full-period MAPE
13.8660678%, RMSE 10055.6393, R2 0.95869695; winter MAPE 7.91951768%.

## 2. Peak export preparation

After accepting Town_Q, generate reports from saved daily Parquet; do not refit.
The pipeline's individual mode already exports each customer's peak and date.
The existing `scripts/export_customer_reports.py` exports both individual peaks
and a shared modeled peak for configured half-open windows. Point its config at
the actual accepted timestamped run and use a separate destination.
Report the full simulation and winter November 15, 2024 through March 15, 2025
(exclusive end March 16). Include available-day counts and missing reasons.

Implemented for the city workflow: explicit-date extraction in its report exporter,
independent of full-cohort peak selection. Export every input customer on each
requested date with ID, Gregorian/Jalali dates, m3/day, coverage, method/status and
missing reason. The user confirmed February 10 and February 25, 2025 as requested
comparison dates, inferred from weather and existing Town_Q reports. No measured
city-wide daily totals are available. Label these as candidate city peak dates,
not confirmed or measured city peaks; independently identify the modeled peak.
Retain both requested dates even if the modeled peak falls elsewhere. Test two
dates, unavailable values, zeros, ties, outside-window rejection and source
immutability. Verify same-day exports against saved daily allocations.

## 3. City input decision and preflight

Initial audit of `data/raw/bill_1403.csv` on November 11, 2026:

| Check | Result |
|---|---:|
| Bill rows | 513,921 |
| Unique customer IDs | 362,660 |
| Earliest bill start | 2025-01-02 |
| Latest bill end | 2025-04-29 |
| Exact duplicate rows / reversed intervals | 0 / 0 |
| Missing / negative consumption | 0 / 0 |
| ConsumptionType | 40 only |
| Customers with source coverage on 2025-02-10 | 315,351 |
| Customers with source coverage on 2025-02-25 | 351,803 |

These are raw coverage counts, before normalization, overlap handling or rejection.
47,309 and 10,857 input customers respectively lack a bill covering those dates.
The file alone does not establish that all city customers or customer types are
included. Audit duplicate/conflicting intervals, units, date semantics, ID roster,
weather coverage and accepted coverage before launching.

An updated city extract is recommended: ideally the same December 2023-April 2025
history as Town_Q, including summer 2024 and complete bills bracketing target
dates, plus all intended consumption types and a customer roster. The current
file has no summer history, so the configured customer summer floor uses its
insufficient-history fallback instead of the selected run's summer baseline.
Do not claim this reproduces g013's empirical behavior on the city.

If the current file is retained, explicitly accept that fallback and restrict the
city simulation/report window to supported dates (candidate January 2-April 29,
2025, exclusive end April 30). City dates use `%Y-%m-%d`, unlike Town_Q's
`%m/%d/%Y`. Set city `tbs_path=null`; Town_Q TBS is not city-wide ground truth.
Edit `configs/city_final.json` after the input/window decision. Do not
create a 517-day city grid from this short extract merely by inheriting Town defaults.

Run a deterministic city pilot before the complete run. Measure runtime, RAM,
disk and number of customer-days; inspect summer-fallback frequency and all
consumption types. The current 118-day candidate window is about 42.8 million
customer-days. Use Parquet and streamed peak/date exports; avoid a full CSV grid
unless specifically needed. Execute all customers in the accepted file only after
pilot validation. Keep input hashes and output locations separate from Town_Q.

## 4. City deliverables and validation

- Individual peak consumption and earliest tied peak date, with available-day
  counts, window and coverage status for every customer, including unavailable ones.
- Customer consumption on both requested city dates and on independently selected
  modeled peak dates, each labeled by date source and population definition.
- Daily totals and contributing-customer counts. Existing shared-peak reports use
  a fixed full-target coverage cohort; label that as a cohort peak, not a complete
  city peak. Do not rank changing-coverage totals as if population were constant.
- Bill reconciliation, missingness, fallback share, floor-source counts and
  distribution of peak values/dates. Cross-check exported customer counts and sums.
- City MAPE/RMSE/R2/Pearson only if matching city-wide measured daily totals are
  provided; otherwise report internal consistency and coverage, not measured accuracy.

## 5. Presentation package

Town_Q: winter/full-period metric table (MAPE, RMSE, R2, Pearson, matched/missing
days), raw TBS as the primary measured reference and 0.8/0.75 sensitivity columns;
aggregate daily overlay; fixed-customer profiles against uniform bill allocation;
peak-date/value distributions and a compact coverage/reconciliation summary.
Keep April 29-30 exclusions in the historical comparison metrics only, visibly
labeled; do not silently remove them from individual peak searches.

City: representative profiles stratified by consumption type, annual/available
consumption and coverage; individual-peak distribution; requested-date customer
consumption distribution; daily aggregate and coverage chart. Freeze the sample
and seed. Include exceptional/partial customers rather than only clean profiles.
All profiles and peaks are retrospective estimates, not measured customer daily
truth. Assemble presentation figures and tables after the accepted runs; no
additional hyperparameter search is planned on this branch.

## Remaining decisions

Confirm whether an updated full-history city extract will be supplied and whether
type 40 is the intended population. The year and inferred source of the two
requested comparison dates are confirmed; city measured-accuracy metrics are
unavailable unless matching measured city totals are supplied later.
These decisions affect the city execution, not the prepared Town_Q run.
