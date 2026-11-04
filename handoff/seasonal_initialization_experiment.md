# Seasonal initialization experiment

Independent branch from f640191. Config initialization defaults to uniform;
seasonal_hdd65 initializes each modeled bill with B*(1+HDD65)/sum_bill(1+HDD65).
HDD65 uses the existing daily apparent-temperature weather adapter and units.
No Fourier coefficients or new calendar weights are introduced. Zero bills
remain zero; positive bills preserve their full normalized totals. Uniform
fallback bills are unchanged. The standard baseline definitions remain intact.

Only initialization changes; subsequent sequential residual updates are exactly
the original algorithm. Thus there is no persistent seasonal constraint. Tests
compare 5×5 and 50×25 to determine whether the seasonal start survives updates.
Checkpoint identity includes initial weights to reject incompatible resumes.

```
python run_pipeline.py --config configs/experiment_seasonal_short.json --bills data/prepared/bill_Customers_Town_Q_full_year_all_types.csv --output outputs/seasonal_short
python scripts/evaluate_customer_experiment.py outputs/seasonal_short
```

Use experiment_seasonal_long.json / seasonal_long for 50×25. All configs use
alpha=.05 and disable checkpoint I/O and optional CSV copies. Outputs preserve
the accepted run's bill policies. This is a controlled retrospective experiment,
not independent validation of customer daily accuracy.
