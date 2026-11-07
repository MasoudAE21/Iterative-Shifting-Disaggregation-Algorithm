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
Their runtime field is blank because standalone baseline timing is not measured.
Customer peak-date agreement is measured against the first supplied run.
TBS is independent validation for this branch. Synthetic known-truth scores
measure reconstruction on constructed scenarios, not real-customer accuracy.

Tests include engine equivalence, conservation, floor preservation, recorded zero,
zero residual correction, invalid parameters, disabled behavior, checkpoint resume,
and rejection when reference weights change. The existing Fourier fixture now
includes a warm day so its active CDD65 feature has nonzero spread.

## Fourier aggregate / customer-weather branch

`configs/fourier_customer_weather.json` selects a five-harmonic measured-TBS
curve as the sole non-intercept aggregate feature. Existing aggregate OLS and
exposure scaling are retained: station volumes are not forced onto customers.

After each complete sequential ISD sweep, each customer's updated daily
allocations are fitted against intercept, HDD65, CDD65, HDDpW65 and trailing
three-day HDD65 mean. Means and population standard deviations use that
customer's covered days; constant non-intercept columns become zero. Ridge
penalty 1 applies to non-intercept coefficients only. Rank deficiency is handled
by ridge; unavailable fits (including fewer than two covered days), nonfinite
predictions or zero bill prediction sums use the conserved seasonal reference.
Negative predictions are clipped, normalized within each bill, mixed with a
10% uniform reserve, and blended 3% with the current allocation. Customer fits
use generated estimates: this is smoothing, not independently measured truth.
The full aggregate is rebuilt after this customer phase, before checkpointing.

Customer support scaling and ridge systems are prepared once, caching identical
support patterns. Numba evaluates daily fitting and redistribution sequentially;
no additional dependencies or parallel bill ordering are introduced. Reference
and compiled engines use the same customer arithmetic. Checkpoint identity
includes customer grouping, raw weather design, ridge penalty and correction
settings; derived fit state is reconstructed deterministically on resume.

```
python scripts/run_combined.py --config configs/fourier_customer_weather.json --smoke --output outputs/fourier_customer_weather_smoke
python scripts/run_combined.py --config configs/fourier_customer_weather.json --output outputs/fourier_customer_weather_10x10
python scripts/run_combined.py --config configs/fourier_customer_weather.json --long --output outputs/fourier_customer_weather_50x25
python scripts/evaluate_combined.py outputs/seasonal_reference_combined_10x10 outputs/seasonal_reference_combined_50x25 outputs/fourier_customer_weather_10x10 outputs/fourier_customer_weather_50x25 --baselines
```

TBS comparisons on this branch are explicitly in-sample reconstruction metrics.
The manifests include customer model provenance and per-cycle fallback counts.
The synthetic evaluation also fits Fourier to the synthetic aggregate truth and
therefore has the same input advantage; use its individual metrics to inspect
behavior, not to claim an independent aggregate validation win.
