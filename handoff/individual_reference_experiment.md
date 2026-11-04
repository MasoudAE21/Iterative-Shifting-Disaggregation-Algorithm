# Individual reference residual experiment

Independent branch from f640191. One new parameter:
individual_reference_strength (eta), default 0; trial values .01 and .05.
Initialization remains uniform. For every modeled bill create a fixed reference
q = B*(1+HDD65)/sum_bill(1+HDD65), using the existing weather features.

After each ordinary sequential aggregate-residual bill update produces u:

```
individual_residual = q - u
new_allocation = u + eta * individual_residual
```

The correction happens before restoring the daily aggregate, so later bills
observe it immediately. Both u and q sum to B, so correction preserves the total.
Zero bills remain zero. If the aggregate residual is zero, the individual
correction still applies; such an update is not counted as a zero-residual no-op.
eta is applied once per bill visit, independently of alpha; eta=1 forces the
reference, while eta=0 reproduces the original solver. This is not a new fitted
customer model: the reference is a hypothesis shared across customer types.
Its memory cost is one additional float64 value per modeled bill-day.

Tests cover both engines, zero aggregate residual, conservation, disabled mode,
and checkpoint rejection when the reference weights change. Checkpoint identity
includes reference weights; the reference is reconstructed on resume.

```
python run_pipeline.py --config configs/experiment_reference_01.json --bills data/prepared/bill_Customers_Town_Q_full_year_all_types.csv --output outputs/reference_01_long
python scripts/evaluate_customer_experiment.py outputs/reference_01_long
```

Use experiment_reference_05.json / reference_05_long for eta=.05. Both trials use
50×25 and alpha=.05, with checkpoint I/O and optional monthly CSV copies off.
Neither a better TBS metric nor a plausible-looking customer curve establishes
individual daily accuracy. The all-types heating reference requires validation.
