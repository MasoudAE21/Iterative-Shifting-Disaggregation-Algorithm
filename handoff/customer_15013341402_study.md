# Customer 15013341402 — accepted experiment 05 allocation study

## Finding

The tiny February estimates are genuine solver allocations, not Excel formatting,
CSV corruption, missing coverage, or loss of the 229 m³ bill. The model moved
essentially all 229 m³ into September 1–October 4, 2024. Bill conservation alone
does not validate this inferred timing or the customer's daily peak.

## Input and export trace

- Source: `data/prepared/bill_Customers_Town_Q_full_year_all_types.csv`, physical
  source row 22704. The source hash matches the normalized ledger.
- Bill: September 1, 2024–March 9, 2025, inclusive, 190 days, 229 m³.
- Normalization: accepted, unchanged, retained fraction 1.0, shared-population
  model, full target coverage. The bill is not a February-only or winter-only bill.
- The configured 150-day duration limit uses `bill_duration_scope='boundary'`;
  it does not exclude this bill, which is contained within the simulation.
- Allocation method: `cohort_exposure_isd`, not uniform fallback.
- Full bill allocations and customer-day Parquet agree exactly; February CSV
  parsed with round-trip float precision also agrees exactly.
- The 190 daily allocations sum to 229 m³ using independent `math.fsum`.
- September receives 202.1038731432002 m³ (88.25497%); October receives
  26.896126856799796 m³ (11.74503%). Only 34 days exceed 1e-10 m³/day;
  the last is October 4. November through March 9 receive tiny positive remnants.
- December, January and February receive respectively 6.265656504134733e-27,
  5.893980180646961e-27 and 6.005646184482947e-27 m³.
- Bill maximum: September 2, 2024, 10.711504372373387 m³/day.
- The later 60 m³ bill is a separate boundary-adjusted bill (37.840909 m³
  retained through April 30); it does not explain February values.

## Mechanism

The solver starts this bill uniformly at 229/190 = 1.2052631579 m³/day.
For each sequential bill visit, it computes a nonnegative residual between the
aggregate regression prediction and all other bills' current contributions:

```
residual[d] = max(prediction[d] - (aggregate[d] - old_bill[d]), 0)
proposal[d] = bill_total * residual[d] / sum(residual)
new_bill[d] = 0.95 * old_bill[d] + 0.05 * proposal[d]
```

If the entire residual is negligible the bill is left unchanged. Otherwise,
days with zero residual receive a zero proposal and shrink by 0.95. Other days
receive the consumption necessary to preserve the bill total. This is an
aggregate residual allocation, not an independently fitted household heating
profile. The accepted run executes 50 fits × 25 sweeps = 1,250 visits per bill.
For a day receiving zero proposals throughout:

```
(229/190) * 0.95**1250 = 1.7202378235774876e-28
```

This matches the minimum saved allocation to floating-point precision. Other
February values can be slightly larger because they received positive proposals
in some updates. These are normal representable float64 numbers, far above
underflow; their scale follows repeated damping rather than a storage failure.

## Reproduction and evidence

Run `python scripts/study_customer_allocation.py`. It reconstructs canonical
modeled bills and checks the saved checkpoint's input/config/design fingerprint.
It uses the checkpoint's exact design and fit mask, initializes from the original
uniform allocations, and replays all fits and sweeps without replacing accepted
outputs. A wrapper splits each sweep immediately before and after this bill to
observe its residuals without changing arithmetic or customer order.

The script requires bit-for-bit equality of the entire replayed allocation array
and aggregate with the accepted checkpoint. Its artifacts are in
`outputs/experiment_all_types_05/customer_study_15013341402/`:

- `study_summary.json`: exact-replay assertions and population screening counts.
- `bill_229_sweep_trace.csv`: winter/February totals after every update.
- `bill_229_outer_profiles.csv`: the bill's daily profile after each outer fit.
- `zero_proposal_counts.csv`: number of zero proposals for each bill day.
- `source_customer_bills.csv`, `normalized_customer_bills.csv`, `customer_daily.csv`.
- `bill_229_monthly.csv`, `bill_229_largest_days.csv`.
- `near_zero_winter_positive_bills.csv`: positive modeled bills whose available
  winter days all have estimates below 1e-10 m³/day; this is a screening threshold,
  not a physical inactivity criterion.
- `allocation_diagnosis.svg`: the final bill profile and decay across updates.

The replay passed bit-for-bit equality for all 4,430,690 modeled daily allocations
and all 517 aggregate values. Every February day received a zero proposal in
1,247–1,250 sweeps. The exact uniform-decay minimum identifies days with zero
proposals throughout. Winter allocation falls from 106.718564 m³ after the first
sweep to 0.000343271 after 250, 9.25845e-10 after 500, 2.49712e-15 after 750,
6.73505e-21 after 1,000, and 1.816528286926464e-26 after 1,250.

Population screening found 4,096 of 23,259 positive modeled bills intersecting
December–February (17.61%) whose winter estimates are all below 1e-10 m³/day,
across 3,596 distinct customers. Affected bills can overlap only part of winter;
this count does not imply each customer's entire winter consumption is tiny.
Of 722,487 winter customer-days on positive modeled bills, 572,904 (79.30%) are
below the same threshold. Zero-total bills and uniform fallback bills are excluded
from these denominators. These are concentration flags, not proof of physically
incorrect consumption. They demonstrate that the phenomenon is widespread.

## Interpretation and next experiment

The billing data do not reveal whether consumption truly occurred only in early
autumn. Long intervals leave considerable freedom to move consumption between
seasons. Uniform allocation would assign 108.473684 m³ to the 90 winter days,
while preserving the same 229 m³ bill; this is a diagnostic alternative, not
ground truth. The full coverage flag and reconciliation check cannot choose
between these profiles.

Retain experiment 05 as the accepted aggregate experiment, but treat individual
customer peaks as unvalidated estimates. Do not fix this by rounding tiny values
to zero or imposing an arbitrary positive floor: neither establishes the correct
seasonal allocation. First examine iteration sensitivity and concentration on
positive long bills. Compare uniform, weather-weighted and regularized allocations
that preserve each bill total; select constraints using customer type and any
independent short-interval meter evidence. Test aggregate fit and customer-level
stability together. Fewer iterations can reduce the extreme collapse but are not
by themselves a validated solution. Daily customer timing requires additional
constraints or evidence beyond aggregate agreement and bill conservation.

The accepted solver and configuration were not changed by this investigation.
