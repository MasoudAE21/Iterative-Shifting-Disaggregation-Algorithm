# Reserved uniform-share experiment

Independent branch from f640191. New parameter: redistribution_floor, default 0.
For each bill, the ordinary normalized residual proposal z (sum B) becomes
rho * B/L + (1-rho) * z. The existing alpha update blends the old allocation
with that proposal. Uniform initialization and the zero-residual keep-current
rule ensure the lower bound rho*B/L persists (within floating-point tolerance).
Zero bills stay zero, and exact bill reconciliation remains enforced.

This reserves a uniform fraction; it is not a minimal-distance projection onto
a floor. Even proposals above the floor are blended with the reserved share.
No customer readings justify the chosen fractions yet. This is experimental,
not the unmodified paper algorithm. Values 0.1 and 0.2 are compared at 50×25,
alpha .05, with the accepted experiment 05 as the matching-count baseline.

Run from the repo root, using the usual all-types bills:

```
python run_pipeline.py --config configs/experiment_floor_10.json --bills data/prepared/bill_Customers_Town_Q_full_year_all_types.csv --output outputs/floor_10_long
python scripts/evaluate_customer_experiment.py outputs/floor_10_long
```

Use experiment_floor_20.json and floor_20_long for 20%. Configs disable checkpoint
I/O and optional monthly CSVs to keep experiments efficient; all Parquet and
standard peak outputs are still written. Evaluation is retrospective and does
not validate individual daily accuracy. Do not select a fraction solely to
optimize TBS fit or this one customer's winter total.
