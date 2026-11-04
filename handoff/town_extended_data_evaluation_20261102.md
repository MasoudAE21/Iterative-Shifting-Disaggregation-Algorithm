# Q_Town extended-input evaluation — 2026-11-02

## Decision

The new files support a substantially better **provisional validation study**, including 2024 and a second winter. They do **not** establish that the daily disaggregation is accurate, and they cannot be used unchanged by the current pipeline. Fix ingestion and explicitly define the weather-source, boundary, population, and validation policies before treating station agreement as acceptance evidence.

This evaluation ran the existing bill normalization/audit functions and probed the production readers. It did not fit the ISD solver, change production code/configuration, or alter input files. Date-normalized records used below exist only in the audit process. Existing unrelated working-tree changes were preserved.

Reproduce with `.\.venv\Scripts\python.exe scripts/audit_town_extended.py`. Evidence is in `outputs/town_extended_audit/`: `audit.json` (including source SHA-256 hashes), `daily_coverage.csv`, `monthly_coverage.csv`, `policy_scenarios.csv`, and `winter_candidates.csv`. The denominator is always the 9,298-customer roster. Raw coverage uses unions of valid inclusive intervals; it does not count missing customers as zero consumption.

## Measured file quality and coverage

| Measure | Previous prepared file | New file |
|---|---:|---:|
| Weather days | 152 | 548 |
| Weather dates, inclusive | 2024-11-01–2025-04-01 | 2023-12-01–2025-05-31 |
| Weather missing/duplicate dates or missing numeric values | 0 | 0 |
| Bill rows | 36,849 | 111,582 |
| Customers with bills | 9,021 | 9,066 |
| Roster customers without bills | 277 | 232 |
| Earliest bill start | 2021-08-29 | 2018-07-08 |
| Latest bill end | 2025-10-24 | 2025-10-24 |
| Median bill duration | 44 days | 42 days |
| 99th-percentile bill duration | 155 days | 140 days |
| Maximum bill duration | 1,478 days | 2,176 days |
| Zero-consumption rows | 2,442 | 8,171 |

After explicit date conversion for the audit, both bill histories have no invalid numeric/date intervals, negative consumption, exact duplicate rows, overlaps, or internal gaps. All customers occur in the roster. This is structural validity; it does not validate column meanings or establish that zero bills are physical zero demand.

The new file includes **all 36,849 previous bill intervals with identical consumption**. Do not concatenate the files: that would double-count the old history. The added 45 customers/history improve early coverage, but do not increase January–February 2025 support.

For January 2–February 28, 2025, minimum raw coverage is **96.63%** and mean coverage **96.73%**, unchanged from the previous bills. Across 2024, monthly minimum raw coverage ranges from **97.47% in January to 96.88% in December**. January–March 2025 monthly minima are **96.66%, 96.63%, and 96.09%**.

The station file has 523 dated rows, January 1, 2024–June 6, 2025, plus one blank trailing CSV record. There are no missing dates in that dated series. All 366 days of 2024 and all 90 days of January–March 2025 have positive station values and complete new weather. The 25 zero station values are April 30–May 24, 2025; retain a separate quality flag and investigate before using them as measured zero demand. The old audit's single missing value corresponds to the blank record, not a missing dated observation.

## Required ingestion fixes

1. **Correct the bill attribute mapping in a versioned preparation step.** Every matched old/new interval exhibits this rotation:

   | New column label | Apparent actual meaning | Canonical output column |
   |---|---|---|
   | ConsumptionType | Capacity (6, 10, 16, …) | Capacity |
   | UnitCount | ConsumptionType (always 40) | ConsumptionType |
   | Capacity | UnitCount (1, 2, 3, …) | UnitCount |

   This is supported by all 36,849 matched records, not just a sample. The rotated capacity/unit mapping also matches the roster for all 111,582 new rows, while the labeled mapping matches none. Verify the export mapping and preserve original values/provenance. The numeric validator alone does not detect this error; merely fixing dates would let the mislabeled attributes pass.
2. **Normalize bill dates with explicit `%m/%d/%Y` parsing.** The current production reader rejects all **111,582** raw new rows because it requires canonical `YYYY-MM-DD`. Preserve the source and generate a canonical derivative or extend the reader with an explicit schema version. Avoid ambiguous automatic day/month inference. The independent `town_uniform_daily.py` reader also requires ISO dates.
3. **Extend the daily weather schema.** The new file has mean air temperature, mean apparent temperature, and maximum wind, with CP1252 degree symbols and empty padding columns. The current reader handles the encoding/padding but rejects this four-column daily layout with `Weather headers/units changed`. Retain both temperature fields with distinct names and units; choose the modeling basis explicitly.
4. **Select inputs explicitly.** Two prepared `open-meteo*.csv` files now exist. Both the pipeline's default discovery and the previous Town audit require exactly one. The pipeline Python API accepts `weather_path`; the CLI currently has no `--weather` option. Default bill selection still points to the old file. Add explicit path configuration/CLI support rather than deleting the old evidence or selecting a file arbitrarily.

## Weather-source policy

The new weather is a **different location**, not a simple date extension:

| Metadata | Old | New |
|---|---|---|
| Latitude | 34.411247 | 34.69244 |
| Longitude | 50.490566 | 50.85967 |
| Elevation | 1,333 m | 939 m |
| Daily timezone | GMT | GMT |

Across their 152 overlapping days, new apparent temperature is **3.31°C warmer on average**, with mean absolute difference **3.34°C** and maximum absolute difference **6.10°C**. Maximum wind differs by **3.86 km/h** in mean absolute terms. Verify which point represents Q_Town; do not attribute a model improvement solely to longer history when the weather location also changed.

The previously documented GMT-date/local-station-date approximation can remain a labeled provisional assumption. These are daily summaries: they cannot be shifted to reconstruct exact Tehran local-day means. Obtain local-day weather if exact alignment is required.

Use the existing apparent-temperature model as one reproducible baseline, and assess air-temperature features separately. Daily maximum wind is not daily mean wind. The current `town_custom_v1` uses apparent temperature and maximum-wind interactions; report those as custom empirical features, not as verification of a mean-wind formula. Choose features on development data, then freeze them for held-out evaluation.

## Bill-boundary and duration policies

The longer weather range reduces exclusions, but does not cover all full bills. Of 17,338 accepted bills intersecting January 2–February 28, 2025, **20 start before the new weather and 176 end after it**; the full required envelope is August 29, 2021–October 10, 2025. For bills intersecting 2024, the envelope starts July 8, 2018. These counts can overlap; they are not additive exclusion totals.

The following scenarios retain original bill totals and exclude bills not wholly contained in the new weather range. Caps apply to original inclusive duration. They are sensitivity measurements, not changes to current settings:

| Target | Duration cap | Minimum daily roster coverage | Customers covering every target day |
|---|---:|---:|---:|
| Jan 2–Feb 28, 2025 | None | 94.65% | 8,796 |
| Jan 2–Feb 28, 2025 | 100 days | 91.16% | 8,385 |
| Jan 2–Feb 28, 2025 | 150 days | 93.85% | 8,695 |
| Jan 2–Feb 28, 2025 | 180 days | 94.32% | 8,743 |
| Full 2024 | None | 90.18% | 8,302 |
| Full 2024 | 150 days | 89.69% | 8,076 |
| Jan–Mar 2025 | None | 88.43% | 8,218 |

All these scenarios use the new weather, including the old-bill comparison rows in the evidence CSV. They should not be confused with the old-weather 89.13% minimum from the prior report. Coverage after exclusions is still not a claim of full-population station comparability.

Recommend preserving original totals as the primary accounting baseline, with exclusions and their lost support reported explicitly. Keep the existing January–February target for continuity, and use 2024 as additional development/evaluation data. A 60-day exploratory window, November 19, 2024–January 17, 2025, has 95.70% minimum weather-bounded coverage without a duration cap; it is a coverage-screening candidate, not an independent holdout if parameters have already been chosen using it.

Current code and old prose differ: `run_pipeline.py` uses `monthly_weighted`, target boundaries, and a 100-day cap; `configs/town.json` overrides the cap to 150 days. The previous report describes weather exclusion. Record effective settings in each comparison.

Executing the actual boundary-adjustment function on the date-normalized new records gives the following January 2–February 28 sensitivities. These are adjusted-total accounting results, not solver predictions:

| Monthly-weighted duration cap | Minimum coverage | Full-target customers | Adjusted target bill volume / TBS |
|---|---:|---:|---:|
| 100 days (entry point) | 91.16% | 8,385 | 76.94% |
| 150 days (Town JSON) | 94.19% | 8,725 | 79.24% |
| None | 96.63% | 8,985 | 81.13% |

The implemented `monthly_weighted` adjustment divides retained **day count** by the full bill's sum of month weights. It does not sum month weights in the numerator. With January/February weights equal to one this matches a weighted allocation for the current target; extending the same setting into summer can inflate retained consumption and does not generally conserve the original bill across complementary windows. Do not reuse it for annual validation without defining the intended formula. Clipping and retaining the entire original total is likewise inappropriate as an observed-total baseline. Report any modeled boundary allocation separately from measured bill totals.

## What validation can establish

**Code/accounting checks:** after ingestion fixes, run schema regression tests, a small real-data smoke run, and the independent output verifier. Check that fitting actually ran rather than returning uniform fallback. Test conservation against original bills when claiming original-total reconciliation; conservation of adjusted boundary totals proves only consistency with that adjustment.

**Aggregate predictive checks:** compare uniform allocation and ISD against untouched TBS on identical dates and customer support. Report bias, MAE/RMSE, total-volume ratio, peak magnitude/date, and coverage alongside metrics. Do not silently scale the station or predictions to force agreement. The existing TBS comparison excludes missing values but does not automatically reject the zero station run, so the expanded study needs a quality mask.

For the existing 58-day target, uniform allocation of all valid original new bills totals **72.91% of TBS**, exactly as with the old bills; weather-bounded original bills give **72.35%** without a duration cap. These are baseline diagnostics, not ISD results. A roughly 27% aggregate shortfall cannot be assigned to the roughly 3.3% missing customer-day share without demand evidence. Investigate station/customer scope, billing versus station volume corrections, boundary allocation, and other unrepresented consumption. Customer count is not consumption share.

**Independent evaluation:** develop features on 2024 and reserve early 2025 for a frozen evaluation, with an explicit no-leakage rule for bills crossing the split. A bill total spanning both periods already contains information about both; use a purge/embargo or identify the exercise as retrospective disaggregation. If early 2025 was used for feature selection, it is not an untouched final holdout. Additional held-out observations would be needed for that claim.

**Limit:** station totals can validate aggregate behavior, not the daily truth or individual peaks of each customer. More billing history strengthens constraints and seasonal diagnostics but does not replace daily customer meter measurements or synthetic known-truth tests.

No new solver is required simply because the time range is longer. Explicit preparation and evaluation policies are required before these files support defensible validation conclusions.

Verification completed: the audit script exited successfully; daily evidence has unique dates and coverage bounded by zero and one; all old intervals/consumption are found in the new history; January–February old/new raw coverage and uniform allocations agree (allocation tolerance 1e-7 m3); and the dated station series has no missing consumption values. No full solver run or full test-suite execution was performed for this evaluation.
