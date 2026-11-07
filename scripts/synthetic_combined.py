"""Known-truth stress tests; synthetic results do not validate real customer peaks."""
from dataclasses import replace
from pathlib import Path
import sys
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from isd.config import Config
from isd.solver import State, solve, seasonal_reference
from isd.fourier import fourier_basis
from isd.town_features import town_features


def main():
    rng = np.random.default_rng(20261107)
    n = 365
    days = np.arange(n)
    temp = 16 + 15*np.sin(2*np.pi*days/365)
    daily = pd.DataFrame(dict(apparent_temperature_mean_C=temp, wind_max_kmh=10+5*np.cos(days/6)))
    features = town_features(daily)
    X = np.column_stack(list(features.values()))
    X[:, 1:] = (X[:, 1:] - X[:, 1:].mean(axis=0))/X[:, 1:].std(axis=0)
    weights = 1 + features['HDD65']
    reports = []
    for scenario in ['heating', 'heterogeneous', 'weak_weather']:
        truth, starts, lengths, totals, owners = [], [], [], [], []
        for customer in range(12):
            if scenario == 'heating':
                y = (customer+1)*.2*weights
            elif scenario == 'heterogeneous':
                y = 3 + rng.uniform(.1, 1)*features['HDD65'] + rng.uniform(0, 2)*features['CDD65']
                y = np.maximum(0, y + rng.normal(0, 1, n))
            else:
                y = np.maximum(0, 15 + rng.normal(0, 3, n))
            if customer == 0:
                y = np.zeros(n)
            truth.append(y)
            start = 0
            while start < n:
                length = min(int(rng.integers(20, 61)), n-start)
                starts.append(start); lengths.append(length); owners.append(customer)
                totals.append(y[start:start+length].sum()); start += length
        truth = np.array(truth)
        st = State(np.array(starts), np.array(lengths), np.array(totals), np.r_[0, np.cumsum(lengths)], n)
        cfg = Config(checkpoint=False, initialization='seasonal_reference', redistribution_floor=.1,
                     individual_reference_strength=.03, n_lr_models=10, n_disagg_cycles=10)
        outputs = dict(uniform=np.concatenate([np.full(l, t/l) for l, t in zip(lengths, totals)]),
                       seasonal=seasonal_reference(st, weights, replace(cfg, redistribution_floor=0)),
                       combined=solve(st, X, cfg, reference_weights=weights).allocations)
        if 'customer_model' in cfg.as_dict():
            basis = fourier_basis(pd.date_range('2024-01-01', periods=n), 365.2425, 5)
            curve = basis @ np.linalg.lstsq(basis, truth.sum(axis=0), rcond=None)[0]
            aggregate_X = np.column_stack([np.ones(n), (curve-curve.mean())/curve.std()])
            weather_X = np.column_stack([features[k] for k in ['intercept', 'HDD65', 'CDD65', 'HDDpW65', 'HDD65_ma3']])
            outputs['fourier_customer_weather'] = solve(
                st, aggregate_X, replace(cfg, customer_model='weather_ridge'), reference_weights=weights,
                customer_groups=np.array(owners), customer_design=weather_X).allocations
        for method, a in outputs.items():
            estimate = np.zeros_like(truth)
            for k, owner in enumerate(owners):
                estimate[owner, starts[k]:starts[k]+lengths[k]] = a[st.offsets[k]:st.offsets[k+1]]
            reports.append(dict(scenario=scenario, method=method,
                                individual_wape=float(np.abs(estimate-truth).sum()/truth.sum()),
                                aggregate_wape=float(np.abs(estimate.sum(axis=0)-truth.sum(axis=0)).sum()/truth.sum()),
                                peak_value_mae=float(np.abs(estimate.max(axis=1)-truth.max(axis=1)).mean()),
                                peak_date_match=float((estimate.argmax(axis=1)==truth.argmax(axis=1)).mean())))
    out = ROOT/'outputs/synthetic_combined.csv'
    pd.DataFrame(reports).to_csv(out, index=False)
    print(pd.DataFrame(reports).to_string(index=False))


if __name__ == '__main__':
    main()
