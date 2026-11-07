# 55% and 60% correction reruns with Section 3 features

Both completed with alpha 0.05, 5 regression fits and 10 shifting cycles per fit (50 cycles). New preset: `paper_section3_daily_air_maxwind_v1`.

Regression columns: intercept, HDD65, HDD55, HDDW65, CDD65. Temperature uses daily mean air temperature converted from Celsius to Fahrenheit. Wind uses daily maximum wind converted from km/h to mph by division by 1.609344 before evaluating the piecewise multiplier. Maximum wind is the user-approved substitution for unavailable mean wind, so this is not an exact weather-input reproduction.

The individual-reference correction remains the existing per-bill normalized `1 + HDD65` based on apparent temperature. Cohort selection, monthly-weighted bill adjustment, and other settings are preserved. Original runs are retained.

| Correction | Output directory | Billing input | Customers | Bills reconciled | Maximum bill discrepancy |
| --- | --- | --- | ---: | ---: | ---: |
| 55% | `outputs/reference_55_5x10_paper_features` | `bill_Customers_Town_Q_full_year.csv` | 9,066 | 111,003 | 1.82e-12 |
| 60% | `outputs/reference_60_5x10_paper_features` | `bill_Customers_Town_Q_full_year_all_types.csv` | 9,251 | 113,077 | 2.27e-13 |

Each rerun preserves its predecessor's billing input. Consequently, differences between the two strengths also reflect different populations; compare each against its own earlier run.

Both models completed without model-availability fallback. Partial-coverage customer uniform fallback remains part of the existing pipeline. Configurations are saved in `configs/experiment_reference_55_5x10_paper_features.json` and `configs/experiment_reference_60_5x10_paper_features.json`.

Validation: 59 targeted tests passed; the new feature tests were additionally rerun after extending the above-breakpoint wind check (2 passed). Independent saved-output evaluation checked finite nonnegative allocations and bill totals for both runs. Evaluation tables are in each output's `evaluation/aggregate_metrics.csv`. The evaluator also emits legacy customer-specific diagnostics; its hard-coded bill identifier does not match the 55% dataset, so zero values for that diagnostic must not be interpreted as zero consumption.

The 55% configuration retains monthly customer CSV export; the 60% configuration retains Parquet-only daily export. Both include feature CSVs, daily comparisons, reconciliation, peaks, and manifests with the air-temperature and maximum-wind provenance.
