# Independent customer-allocation experiments

Baseline: main at f6401911a1d3b024077c4808103a36c54563c223. Main was not modified.
All three branches start directly at that baseline; they do not include one
another's algorithm modifications.

| Branch | Change | Initial trial settings |
|---|---|---|
| codex/redistribution-floor | Reserve a uniform share in every residual proposal | redistribution_floor = 0.10, 0.20 |
| codex/seasonal-initialization | Initialize each bill with normalized 1+HDD65 weights | initialization = seasonal_hdd65; 5×5 and 50×25 |
| codex/individual-reference-residual | Correct reference minus updated individual allocation after every bill visit | individual_reference_strength = 0.01, 0.05 |

All trials retain alpha=.05, accepted source data, bill policies, full customer
population and weather features. Reference and initialization weights use the
existing apparent-temperature HDD65 definition, as selected by the user. Trials
disable checkpoint disk I/O and monthly CSV copies; standard Parquet, aggregate,
peak and reconciliation outputs are retained. No new dependencies were needed.

## Retrospective results

Metrics use December 1, 2024–February 28, 2025, all 90 matched days. MAPE80 uses
the assumed 80% measured coverage scenario, not a verified target. Near-zero
means below 1e-10 m³/day for every available winter day on a positive modeled
bill. There are 23,259 such positive winter-overlapping bills in each run.
Customer winter means December–February allocation of the 229 m³ bill for
15013341402. Its true winter allocation is unknown.

| Run | Fits×cycles | Original MAPE % | MAPE80 % | Customer winter m³ | Near-zero winter bills | P90 daily peak / bill daily mean |
|---|---:|---:|---:|---:|---:|---:|
| Accepted 05 | 50×25 | 26.100 | 8.422 | ~0 | 4,096 | 41.00 |
| Baseline 06 | 5×5 | 27.035 | 9.214 | 33.75 | 0 | 6.62 |
| Uniform reserve 10% | 50×25 | 26.167 | 8.500 | 10.85 | 0 | 36.10 |
| Uniform reserve 20% | 50×25 | 26.155 | 8.486 | 21.69 | 0 | 31.40 |
| Seasonal initialization, short | 5×5 | 22.698 | 8.885 | 106.70 | 0 | 4.17 |
| Seasonal initialization, long | 50×25 | 22.524 | 8.681 | ~0 | 4,471 | 49.00 |
| Individual correction 1% | 50×25 | 25.094 | 8.960 | 29.13 | 0 | 36.79 |
| Individual correction 5% | 50×25 | 24.672 | 9.925 | 88.88 | 0 | 4.41 |

All 113,077 accepted bills reconcile independently in all runs. Maximum absolute
discrepancy using independent pandas grouped sums is at most 4.55e-13 m³.
Input hashes, model feature-scaling metadata and number of modeled bills match
the baseline. No case replaces missing consumption with zero in evaluation.

## Interpretation

1. Uniform reserve is effective as a lower bound. The measured minimum
   daily-to-bill-mean ratios are 0.1 and 0.2 within floating-point tolerance.
   Aggregate scores barely move. However, this customer's winter allocation
   settles at the exact uniform reserve, while September still receives 185.15
   or 168.18 m³. Large daily spikes remain. This is a safeguard, not evidence
   that seasonal behavior has been identified.
2. Seasonal initialization has a strong short-run effect. The starting reference
   allocates 173.31 m³ of the bill to winter; after 5×5 the algorithm retains
   106.70 m³. After 50×25 it falls to 9.48e-20 m³ and concentration is worse
   across the population. Initialization alone is not robust to more updates.
   Its long-run aggregate accuracy is different despite the same features:
   this also demonstrates sensitivity to the starting allocation.
3. Individual correction persists at high iteration count. At 1% the effect is
   too weak to substantially reduce high-end concentration. At 5%, P90 falls
   sharply, but P99 remains 25.90 (versus 22.57 for baseline 06 and 13.86 for
   seasonal short). September still receives 101.02 m³ of the special bill.
   Original-measurement MAPE improves versus 05 while MAPE80 worsens. The
   observed trade-off should not be hidden by reporting only one target scenario.

The individual correction is applied after the ordinary alpha update:
u <- u + eta*(q-u). Eta is not multiplied by alpha. If the ordinary aggregate
proposal is zero repeatedly, the limiting reference contribution is
eta/[alpha+eta-alpha*eta] times q. For this customer's winter days the observed
results closely reflect that lower envelope. A positive winter value alone is
therefore not proof of customer accuracy, even with the persistent reference.

## Peak-date implications

The winter fixed-population peak is February 10, 2025 in all trials except
individual correction 5%, which selects February 25. Peak totals are:

| Run | Winter peak m³/day |
|---|---:|
| Accepted 05 | 163,920.14 |
| Baseline 06 | 160,781.95 |
| Reserve 10% | 163,992.99 |
| Reserve 20% | 164,151.82 |
| Seasonal short | 192,730.76 |
| Seasonal long | 193,736.00 |
| Individual correction 1% | 174,980.00 |
| Individual correction 5% | 191,376.73 |

For downstream customer contributions, distinguish consumption on a common
comparison date from consumption on each method's own modeled peak date.

## Validation and reproduction

Full existing-plus-new test suites passed on every branch: 140 tests for the
reserve branch, 138 for seasonal initialization and 141 for individual correction.
New tests cover bill conservation, zero bills, reference/scaled engine agreement,
checkpoint resume and rejection of incompatible settings or weights. The
individual branch also verifies correction when the aggregate residual is zero.

Each branch includes scripts/evaluate_customer_experiment.py. It independently
checks saved bill sums and writes evaluation/aggregate_metrics.csv,
evaluation/customer_15013341402_daily.csv, evaluation/customer_229_bill_monthly.csv,
and evaluation/metrics.json within each run. Baseline 05 and 06 were evaluated
with the same script. Full run outputs are local ignored artifacts, not commits.

Run folders under outputs/:

- floor_10_long, floor_20_long
- seasonal_short, seasonal_long
- reference_01_long, reference_05_long

The combined table is outputs/constraint_experiments/comparison.csv. Configs
and example commands are documented in each branch's method-specific handoff.
Select a branch using git switch; these branches reuse the current checkout.
There are no extra worktrees and no automatic merge into main.

## Next decision

Keep the three ideas separate while reviewing results. For a persistent remedy,
the individual-reference branch is the most direct candidate for further tuning;
an intermediate strength between .01 and .05 is a reasonable next experiment,
not an established optimum. Seasonal short is a useful comparator but its
iteration sensitivity prevents calling it a durable fix. Uniform reserve is
the smallest safeguard but leaves substantial concentration. None establishes
true individual peaks without customer-level validation. The same heating
reference applied across all consumption types remains an assumption to test.
