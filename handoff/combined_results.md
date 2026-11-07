# Two-branch experiment results

Billing source: `data/prepared/bill_Customers_Town_Q_full_year.csv` only.

Both methods use alpha=.05, a 10% uniform reserve and 3% reference correction. The existing 2023-12-01 through 2025-04-30 domain, monthly-weighted boundary policy and cohort/uniform-fallback rules are preserved.

The Fourier/customer-weather 10x10 configuration is the preferred next research
candidate for individual-profile plausibility: typical concentration is much
lower, and individual peak dates are more stable across iteration counts. It is
not a validated estimator of true individual peaks. Its extreme tail remains
large; its TBS RMSE is worse than the seasonal-reference method and the simple
seasonal baseline. The 50x25 run adds substantial cost and worsens concentration
without a meaningful aggregate improvement, so more iterations are not recommended.

## Full-data comparison

| Method | P90 peak/mean | P99 peak/mean | TBS MAE m3/day | TBS RMSE m3/day | Seconds |
|---|---:|---:|---:|---:|---:|
| seasonal_reference_combined_10x10 | 18.54 | 29.55 | 23498.1 | 30184.5 | 150.3 |
| seasonal_reference_combined_50x25 | 23.73 | 40.99 | 23485.9 | 30333.6 | 344.0 |
| fourier_customer_weather_10x10 | 2.49 | 20.43 | 22838.6 | 32065.1 | 182.8 |
| fourier_customer_weather_50x25 | 2.56 | 23.84 | 22824.8 | 32064.7 | 713.2 |
| uniform | 1.00 | 1.00 | 24990.6 | 34563.4 | - |
| seasonal | 4.32 | 4.87 | 24311.9 | 29654.4 | - |

P90/P99 summarize the distribution across positive bills of maximum daily allocation divided by that bill's daily mean. TBS scores use 486 matched station days; the Fourier method uses those measurements as model inputs and its scores are in-sample reconstruction diagnostics. Baselines and the seasonal-reference method do not use TBS as an input.

## Independent checks

All runs use the same effective ledger SHA256 `7b12d27a0fc499ce4f4d6b0635950710590f00b795ff1b18d1fbba241a1ba01e`.

Each reconciles 111,003 accepted bills, including 106,520 modeled bills and 4,483 uniform-fallback bills, for 9,066 selected customers. Maximum independently grouped bill discrepancy: 5.46e-12 m3. All saved allocations are finite and nonnegative; the 10% floor holds on every positive-bill day in both methods. All four runs preserve 92,921 missing customer-days. No positive winter-overlapping bill collapses below 1e-10 m3/day across all available winter days.

Full per-run values, peak-date agreement against the first run, source-ledger hashes and timings are in `combined_comparison.csv`. Customer-specific peak tables remain in local output directories and are not committed.

## Known synthetic truth

| Scenario | Method | Individual WAPE | Aggregate WAPE | Peak value MAE | Exact peak date match |
|---|---|---:|---:|---:|---:|
| heating | uniform | 13.74% | 7.38% | 1.81 | 16.67% |
| heating | seasonal | 0.00% | 0.00% | 0.00 | 100.00% |
| heating | combined | 2.26% | 0.73% | 0.25 | 16.67% |
| heating | fourier_customer_weather | 3.42% | 1.99% | 1.13 | 16.67% |
| heterogeneous | uniform | 14.87% | 7.73% | 2.82 | 8.33% |
| heterogeneous | seasonal | 15.13% | 8.13% | 3.95 | 8.33% |
| heterogeneous | combined | 12.81% | 5.06% | 1.96 | 8.33% |
| heterogeneous | fourier_customer_weather | 7.90% | 3.16% | 2.13 | 8.33% |
| weak_weather | uniform | 15.63% | 4.89% | 7.58 | 8.33% |
| weak_weather | seasonal | 27.67% | 14.51% | 23.61 | 8.33% |
| weak_weather | combined | 19.56% | 6.16% | 4.84 | 8.33% |
| weak_weather | fourier_customer_weather | 15.63% | 4.88% | 7.43 | 8.33% |

Synthetic Fourier curves are fitted to synthetic aggregate truth, giving that method the same input advantage as measured TBS. These scenarios include a zero-consumption customer; exact-date scores include that customer. Results diagnose behavior and do not establish real customer daily accuracy. In particular, customer ridge fits smooth generated allocations rather than adding independent customer observations.

## Validation and reproduction

Seasonal branch: 143 tests passed; 24 solver/combination tests passed again after preserving the original disabled zero-residual path. Fourier/customer branch: 147 tests passed, including an independent augmented-least-squares ridge oracle. Both branches completed 100-customer smoke runs, full 10x10 runs and 50x25 sensitivity runs. Checkpoint resume equality, changed-input rejection, engine agreement, unavailable/zero-prediction fallback and conservation/floor checks are covered.

See `combined_experiments.md` on each respective branch for commands. Implementation commits: seasonal `a55e10e`; Fourier/customer `da658c4`. No dependencies were added and no branches were pushed.

## Iteration sensitivity

seasonal_reference_combined_10x10 versus 50x25: exact individual peak dates agree for 37.39% of 9,029 customers with available peaks in both runs. The fixed-cohort population peak is 2025-02-10 in both runs.

fourier_customer_weather_10x10 versus 50x25: exact individual peak dates agree for 71.75% of 9,029 customers with available peaks in both runs. The fixed-cohort population peak is 2024-12-18 in both runs.
