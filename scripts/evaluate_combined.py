"""Independently reconcile saved allocations and compare both experiment branches."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def evaluate(folder, baseline=None):
    folder = Path(folder)
    manifest = json.loads((folder/'run_manifest.json').read_text())
    ledger = pd.read_parquet(folder/'normalized_bills.parquet')
    bills = ledger[ledger.record_status == 'accepted'].set_index('bill_id').sort_index()
    keys = ['SubscriptionNumber', 'start_ordinal', 'end_ordinal', 'Consumption']
    digest = hashlib.sha256(bills[keys].sort_index().to_csv().encode()).hexdigest()
    daily = pd.read_parquet(folder/'full_bill_daily.parquet',
                            columns=['bill_id', 'date_gregorian', 'estimated_consumption'])
    if baseline:
        weights = np.ones(len(daily))
        if baseline == 'seasonal':
            weather = pd.read_parquet(folder/'daily_weather.parquet')
            w = 1 + np.maximum(65 - (weather.apparent_temperature_mean_C * 1.8 + 32), 0)
            lookup = pd.Series(w.to_numpy(), index=pd.to_datetime(weather.date_gregorian))
            weights = pd.to_datetime(daily.date_gregorian).map(lookup).to_numpy()
        daily['weight'] = weights
        denom = daily.groupby('bill_id').weight.transform('sum')
        daily['estimated_consumption'] = daily.bill_id.map(bills.Consumption) * weights / denom
    assert np.isfinite(daily.estimated_consumption).all() and daily.estimated_consumption.ge(0).all()
    sums = daily.groupby('bill_id').estimated_consumption.sum()
    assert sums.index.equals(bills.sort_index().index)
    error = (sums - bills.Consumption).abs()
    assert (error <= 1e-8 + 1e-10*bills.Consumption).all()
    daily['month'] = pd.to_datetime(daily.date_gregorian).dt.month
    winter = daily[daily.month.isin([12, 1, 2])].groupby('bill_id').estimated_consumption.max()
    positive_winter = winter[bills.Consumption.reindex(winter.index) > 0]
    peak = daily.groupby('bill_id').estimated_consumption.max()
    means = bills.Consumption / bills.day_count
    ratios = (peak/means).replace([np.inf, -np.inf], np.nan).dropna()
    agg = pd.read_parquet(folder/'aggregate_daily.parquet')
    baseline_totals = {}
    for column in ['uniform_baseline_sum', 'weather_weighted_baseline_sum']:
        baseline_totals[column] = float(agg[column].sum())
    peaks = pd.read_parquet(folder/'target_customer_daily.parquet',
                           columns=['SubscriptionNumber', 'bill_id', 'date_gregorian', 'estimated_consumption'])
    if baseline:
        peaks = peaks.drop(columns='estimated_consumption').merge(
            daily[['bill_id', 'date_gregorian', 'estimated_consumption']],
            on=['bill_id', 'date_gregorian'], how='left', validate='many_to_one')
    null_count = int(peaks.estimated_consumption.isna().sum())
    peaks = peaks.dropna(subset=['estimated_consumption']).sort_values(
        ['SubscriptionNumber', 'estimated_consumption', 'date_gregorian'], ascending=[True, False, True])
    peaks = peaks.drop_duplicates('SubscriptionNumber')
    suffix = baseline or 'combined'
    peaks.to_csv(folder/f'evaluation_{suffix}_customer_peaks.csv', index=False)
    tbs = manifest.get('tbs_comparison', {})
    if baseline:
        station = pd.read_csv(manifest['tbs_comparison']['path'])
        station['date_gregorian'] = pd.to_datetime(station.date_gregorian)
        reconstructed = daily.groupby('date_gregorian').estimated_consumption.sum().rename('estimate').reset_index()
        reconstructed['date_gregorian'] = pd.to_datetime(reconstructed.date_gregorian)
        matched = reconstructed.merge(station, on='date_gregorian').dropna(subset=['consumption_m3'])
        delta = matched.estimate - matched.consumption_m3
        tbs = dict(bias_m3=float(delta.mean()), mae_m3=float(delta.abs().mean()), rmse_m3=float(np.sqrt((delta**2).mean())))
    metrics = dict(run=baseline or folder.name, ledger_sha256=digest, bills=len(bills),
                   max_bill_error=float(error.max()),
                   near_zero_positive_winter_bills=int((positive_winter < 1e-10).sum()),
                   positive_winter_bills=len(positive_winter),
                   p90_peak_mean=float(ratios.quantile(.9)), p99_peak_mean=float(ratios.quantile(.99)),
                   null_customer_days=null_count, wall_seconds=None if baseline else manifest['wall_seconds'],
                   modeled_bills=manifest['model_diagnostics']['modeled_bills'],
                   fallback_reason=manifest['model_diagnostics']['fallback_reason'],
                   tbs_role='Validation only' if baseline else tbs.get('evaluation', 'Validation only'),
                   **{k: tbs.get(k) for k in ['bias_m3', 'mae_m3', 'rmse_m3']}, **baseline_totals)
    (folder/f'evaluation_{suffix}.json').write_text(json.dumps(metrics, indent=2))
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folders', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, default=Path('outputs/combined_comparison.csv'))
    parser.add_argument('--baselines', action='store_true')
    args = parser.parse_args()
    results = [evaluate(folder) for folder in args.folders]
    if args.baselines:
        results.extend(evaluate(args.folders[0], name) for name in ['uniform', 'seasonal'])
    assert len({r['ledger_sha256'] for r in results}) == 1, 'Different bill ledgers'
    first = pd.read_csv(args.folders[0]/'evaluation_combined_customer_peaks.csv', dtype={'SubscriptionNumber':str})
    files = [folder/'evaluation_combined_customer_peaks.csv' for folder in args.folders]
    if args.baselines:
        files += [args.folders[0]/f'evaluation_{name}_customer_peaks.csv' for name in ['uniform', 'seasonal']]
    for file, row in zip(files, results):
        other = pd.read_csv(file, dtype={'SubscriptionNumber':str})
        pairs = first.merge(other, on='SubscriptionNumber', suffixes=('_base', '_run'))
        row['peak_date_agreement_with_first'] = float((pairs.date_gregorian_base == pairs.date_gregorian_run).mean())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(args.output, index=False)
    print(pd.DataFrame(results).to_string(index=False))


if __name__ == '__main__':
    main()
