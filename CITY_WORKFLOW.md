# Final city workflow: edit configuration, run, extract

Edit `configs/city_final.json`. This is the only file you need to change for the
city workflow. Town_Q is a comparison/validation dataset and is not used as city
truth. The scientific defaults are the selected g013 settings.

Run the commands below from the repository root in PowerShell. Use a working
Python environment with `requirements.txt` installed; the existing `.venv` works
on this machine. Do not launch a second run into the same output folder manually.
The workflow creates unique timestamped directories automatically.

## 1. Set inputs and the saved simulation period

| Configuration field | What to set |
|---|---|
| `bills_path` | New city bill CSV path, absolute or relative to the repository root |
| `weather_path` | Weather export covering the full simulation and any retained bill days |
| `output_directory` | Parent folder for city runs, pilots and preflight reports |
| `simulation.bill_date_format` | `%Y-%m-%d` for ISO dates or `%m/%d/%Y` for M/D/YYYY |
| `simulation.target_start` and `simulation.simulation_start` | The same first saved day |
| `simulation.target_end_exclusive` and `simulation.simulation_end_exclusive` | The same day AFTER the last saved day |

The final configuration uses `data/prepared/qom_city_bills_1403.csv`, selects only
`simulation.consumption_types=["40"]`, and saves June 1, 2024 through
March 15, 2025 inclusive (288 days). Both start fields are `2024-06-01`;
both exclusive-end fields are `2025-03-16`. `max_customers=null` retains all
selected customers, including rows with unavailable estimates in the reports.

Save the widest period you may need later. All customer-day estimates within
that period remain in Parquet, so reports can be regenerated for any dates or
windows inside it without fitting again. Dates outside the saved period, new
input bills, or changed model settings necessarily require a new simulation.

The bill CSV must have these seven uniquely named columns; column order may vary:

```text
SubscriptionNumber,FromDate,ToDate,Consumption,ConsumptionType,UnitCount,Capacity
```

Customer IDs are 11-digit strings; preserve leading zeros. Bill endpoints are
inclusive and consumption is m3 per customer bill. The configured type-40 filter is applied at ingestion, preserving original physical
source-row identities and recording excluded type counts. Other types are excluded
from fitting, coverage denominators and reports. Set consumption_types to null only
when all types are intended. This does not establish that the input contains every
city customer. Invalid/conflicting records follow
the existing pipeline quarantine rules and remain visible in audit/missing reports.

For g013's summer baseline, the algorithm uses retained Juneâ€“September days.
The configured simulation begins June 1, 2024, retaining the full summer season
through September 30. Customers need at least 10 covered summer days after bill
boundary handling; otherwise the configured fallback applies. Keep
`divide_consumption_by_unit_count=false` for customer totals.

Keep `max_customers=null`, `peak_mode=individual`, and `tbs_path=null` for the full
city run. The template retains g013's `monthly_weighted` boundary policy and
150-day boundary-bill limit; preflight reports which bills were adjusted/excluded.
City measured totals, if later available, belong in the report settings, not in
the model's `tbs_path`. The raw truth series is never scaled during fitting.

## 2. Set report preferences before or after the simulation

| `reports` field | Meaning |
|---|---|
| `automatic_after_simulation` | Generate reports immediately after a validated run |
| `include_all_saved` | Add a report window covering the entire saved target period |
| `windows` | Named `[start, end_exclusive]` windows, e.g. `"february": ["2025-02-01", "2025-03-01"]` |
| `requested_dates` | Every date for which every customer's consumption is wanted |
| `requested_date_role` | Label describing the evidence for these dates |
| `profile_customers` | Explicit quoted customer IDs, e.g. `["15013341402"]` |
| `profile_sample_count` / `profile_seed` | Reproducible additional illustrative profiles |
| `export_monthly_daily_csv` | Optional large CSV copies of all saved daily estimates |
| `minimum_peak_cohort_fraction` | Below this fraction, label a modeled peak cohort as limited; default 0.8 |
| `measured_city_daily_csv` | Optional city truth file, otherwise `null` |
| `truth_scales` | Separate evaluation assumptions, default `[1.0]` |
| `excluded_metric_dates` | Exclude dates from accuracy scoring only, never from peak searches |
| `metric_min_coverage_fraction` | Minimum fraction of input customers with estimates for scoring; default 1.0 |

February 10 and February 25, 2025 are already configured as candidate peak dates
inferred from weather and Town_Q. They are not measured city peaks. Both are always
exported even if the model's peak occurs on another date.

The optional truth CSV requires `date_gregorian,consumption_m3`, with unique ISO
dates and numeric daily totals. Ensure its geography, customer types, units and
population match the city input. Without it, `metrics.csv` has headers only and
the report explicitly says measured accuracy is unavailable; `quality_metrics.csv`
still provides coverage, reconciliation and floor-source statistics.

The `all_saved` report gives individual peaks over September 15, 2024Ã¢â‚¬â€œMarch 15,
2025. The additional `winter` window covers November 15, 2024Ã¢â‚¬â€œMarch 15, 2025.
Requested February dates are exported automatically. Window ends are exclusive;
dates outside the saved grid cause an error and are never silently clipped.

## 3. Preflight, pilot and final simulation

```powershell
.\.venv\Scripts\python.exe scripts/city_workflow.py preflight --config configs/city_final.json
.\.venv\Scripts\python.exe scripts/city_workflow.py pilot --config configs/city_final.json
.\.venv\Scripts\python.exe scripts/city_workflow.py run --config configs/city_final.json
```

Preflight audits actual bills through the same normalization, boundary and floor
logic as the simulation, checks weather, reports customer-day counts, gaps,
quarantine, source hashes, floor sources, free RAM and disk. It performs no fitting.
Read its warnings and summary before the final run. It is repeated by pilot/run.

Use the `pilot` command for the smoke simulation before the final `run`.
The pilot uses `pilot.max_customers` (1000), with all g013 model iterations.
Both pilot and final reports select 10 customer profiles with the configured seed;
the sample is stratified by coverage and consumption magnitude.
It generates the same report bundle and `resource_summary.json` for observed RAM,
runtime, disk and customer-day counts. Its customer selection is deterministic.
Pilot profiles use a sample because requested full-city IDs may be absent.
Pilot resource use is evidence for planning, not a guaranteed linear extrapolation.

The final command has no customer cap. It prints sweep progress, preserves a
source snapshot and input hashes, then independently validates saved allocations:
finite/nonnegative values, correct customer/bill dates, no duplicate or missing
accepted bill-days, floor compliance and bill reconciliation. Solver fallback or
unfinished cycles prevents acceptance (the explicit all-zero fast path is allowed).

Output locations:

```text
outputs/final_city/
  preflight/<timestamp>/preflight.json
  pilot_/<timestamp>/...
  run_/<timestamp>/...
  latest_pilot.json
  latest_run.json
```

`simulation_complete.json` means the saved simulation passed validation.
`validation.json`, `run_manifest.json`, `resource_summary.json` and the normalized
bill ledger document what happened. A report directory's `completion.json` means
that report extraction also finished. If reporting fails after a successful run,
fix report settings and use the reports command; do not rerun the simulation.
If simulation itself fails, there is no accepted completion marker. This workflow
uses fresh runs and does not automatically resume failed simulations.

## 4. Extract or change reports without rerunning

Edit only the `reports` section and run:

```powershell
.\.venv\Scripts\python.exe scripts/city_workflow.py reports --config configs/city_final.json
```

This uses `latest_run.json`, which points only to the latest validated FULL city
run, never a pilot. Each extraction creates a fresh `reports/<timestamp>` folder.
To select an older run explicitly:

```powershell
.\.venv\Scripts\python.exe scripts/city_workflow.py reports --config configs/city_final.json --run-dir "outputs/final_city/run_/YOUR_TIMESTAMP"
```

Reports use the saved run's actual configuration, not edited simulation settings.
Original bill and weather files are not needed for report-only extraction; the
saved Parquet/ledger and manifest must be retained. Source allocations are read-only.

## Deliverables

| File | Contents |
|---|---|
| `simulation_daily_comparison.csv` | Daily uniform total, final algorithm total, included customer fraction and total effective floor; no TBS column for city runs. Written in the run folder and refreshed report folders. |
| `<window>/individual_customer_peaks.csv` | Every customer, maximum m3/day, earliest tied Gregorian/Jalali date, available/window days, coverage status and type |
| `customers_on_2025-02-10.csv`, `customers_on_2025-02-25.csv` | Every customer's estimate, date, method, status and missing reason on each requested day |
| `requested_date_summary.csv` | Totals, available/missing customer counts and evidence label for requested dates |
| `<window>/customers_on_modeled_peak.csv` | Every customer on the window's modeled cohort peak date, plus cohort membership |
| `<window>/fixed_cohort_daily_totals.csv/.png` | Demand from customers covered on every day of that window |
| `daily_totals_and_coverage.csv`, `daily_demand.png`, `daily_coverage.png` | Available-customer totals and changing coverage, clearly labeled |
| `customer_coverage.csv`, `quality_metrics.csv` | Coverage and internal validation statistics, even without measured city totals |
| `<window>/individual_peak_distribution.csv/.png` | Customer peak magnitude distribution |
| `<window>/individual_peak_date_counts.csv`, `individual_peak_dates.png` | Distribution of individual peak dates |
| `customer_profiles.csv`, `customer_profiles_01.png`, etc. | Paginated profiles against uniform bill allocation, 12 customers per image |
| `profile_selection.json` | Explicit and sampled customer IDs, seed and selection policy |
| `metrics.csv`, optional `metric_daily_pairs.csv` and `measured_city_comparison.png` | Measured city accuracy only when matching truth is supplied |
| `report.md`, `report_manifest.json`, `report_settings.json` | Readable summary, definitions, counts, units, source hashes and exact reporting choices |

The profile sample spans consumption type, coverage status and consumption order
of magnitude. It is illustrative, not a statistically representative city sample.
Individual maxima use available days; partial coverage can underestimate a true
peak. Missing estimates stay blank, and valid zeros stay zero. Each input customer
has a row even when all their estimates are unavailable.

The modeled shared peak uses a fixed COMPLETE-WINDOW cohort. This can differ
across windows and from Town_Q's older fixed-full-target report definition. The
cohort size/fraction is explicit; a small cohort is not a city-wide peak. If no
complete-window customers exist, shared peak/date outputs are unavailable, while
individual and requested-date outputs still succeed. Never infer a peak from a
changing-coverage sum without acknowledging its population changes.

Parquet is the reusable source. City-wide monthly CSVs can exceed Excel's row
limit; keep them disabled unless needed, and use Parquet or a suitable data tool
for the full grid. Import customer IDs as text. Keep the entire accepted run folder
to support future report extraction without another simulation.
