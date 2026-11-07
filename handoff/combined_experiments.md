# Conserved seasonal-reference experiment

Base: fourier at 0563cc7. The only billing source for these experiments is
`data/prepared/bill_Customers_Town_Q_full_year.csv`. Existing target dates,
monthly-weighted boundary adjustment, population rules, and partial-customer
uniform fallback remain unchanged. Reconciliation concerns effective bill totals.

The reference is B times a mixture of 10% uniform and 90% normalized 1+HDD65.
Initialization uses this reference. Every residual proposal reserves 10% uniform;
every bill visit then blends 3% toward the reference, including zero-residual
visits. The reference and proposal maintain the bill-relative uniform floor.
Zero bills remain zero. Disabled settings preserve the original equations.
This is an adaptation, rejected in strict paper-reference mode.

Run from the repository root using the project Python environment:

```
python scripts/run_combined.py --smoke --output outputs/seasonal_reference_combined_smoke
python scripts/run_combined.py --output outputs/seasonal_reference_combined_10x10
python scripts/run_combined.py --long --output outputs/seasonal_reference_combined_50x25
python scripts/evaluate_combined.py outputs/seasonal_reference_combined_10x10 outputs/seasonal_reference_combined_50x25 --baselines
python scripts/synthetic_combined.py
python -m pytest tests -q
```

The evaluator independently sums saved bill allocations, verifies validity,
checks identical effective ledgers, records winter-collapse counts (all available
December–February days), bill peak/mean quantiles, missing customer-day counts,
customer peak dates, matched TBS errors and runtime. Uniform and seasonal
baselines use the same ledger; seasonal weights have no uniform reserve.
Their runtime field is the source pipeline runtime, not a separate baseline timing.
Customer peak-date agreement is measured against the first supplied run.
TBS is independent validation for this branch. Synthetic known-truth scores
measure reconstruction on constructed scenarios, not real-customer accuracy.

Tests include engine equivalence, conservation, floor preservation, recorded zero,
zero residual correction, invalid parameters, disabled behavior, checkpoint resume,
and rejection when reference weights change. The existing Fourier fixture now
includes a warm day so its active CDD65 feature has nonzero spread.
