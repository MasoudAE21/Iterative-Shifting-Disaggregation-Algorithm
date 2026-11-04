"""Comparable retrospective winter and customer diagnostics for a saved run."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


def evaluate(run):
    run = Path(run)
    out = run / 'evaluation'
    out.mkdir(exist_ok=True)
    manifest = json.loads((run / 'run_manifest.json').read_text())
    comparison = pd.read_csv(run / 'simulation_daily_comparison.csv')
    comparison = comparison[comparison.date_gregorian.between('2024-12-01', '2025-02-28')].dropna(subset=['tbs_daily_m3', 'final_algorithm_consumption_m3'])
    metrics = []
    for period, frame in [('winter', comparison)] + list(comparison.groupby(comparison.date_gregorian.str[:7])):
        for factor in [1., .8]:
            truth = frame.tbs_daily_m3.to_numpy() * factor
            predicted = frame.final_algorithm_consumption_m3.to_numpy()
            error = predicted - truth
            metrics.append(dict(period=period, measured_factor=factor, days=len(frame),
                MAPE=float(100*np.mean(np.abs(error)/truth)),
                RMSE=float(np.sqrt(np.mean(error**2))),
                R2=float(1-np.sum(error**2)/np.sum((truth-truth.mean())**2)),
                RSQ=float(np.corrcoef(truth, predicted)[0, 1]**2)))
    pd.DataFrame(metrics).to_csv(out / 'aggregate_metrics.csv', index=False)
    reconciliation = pq.read_table(run / 'bill_reconciliation.parquet').to_pandas()
    full = pq.read_table(run / 'full_bill_daily.parquet', columns=['bill_id', 'SubscriptionNumber', 'date_gregorian', 'estimated_consumption', 'method']).to_pandas()
    full.date_gregorian = pd.to_datetime(full.date_gregorian)
    assert np.isfinite(full.estimated_consumption).all() and (full.estimated_consumption >= 0).all()
    sums = full.groupby('bill_id').estimated_consumption.sum()
    ledger = reconciliation.set_index('bill_id').sort_index()
    assert set(sums.index) == set(ledger.index)
    errors = (sums-ledger.bill_total).abs()
    cfg = manifest['configuration']
    assert (errors <= cfg['reconciliation_atol'] + cfg['reconciliation_rtol']*ledger.bill_total.abs()).all()
    positive = set(ledger.index[(ledger.bill_total > 0) & (ledger.method == 'cohort_exposure_isd')])
    modeled = full[full.bill_id.isin(positive)]
    statistics = modeled.groupby('bill_id').estimated_consumption.agg(['sum', 'min', 'max', 'size'])
    peak_ratio = statistics['max']*statistics['size']/statistics['sum']
    winter = modeled[modeled.date_gregorian.between('2024-12-01', '2025-02-28')]
    grouped = winter.groupby('bill_id').estimated_consumption.max()
    customer = full[full.SubscriptionNumber == '15013341402'].copy()
    customer.to_csv(out / 'customer_15013341402_daily.csv', index=False)
    special = customer[customer.bill_id == 'b0f9dca0e3c4bf0b56f6cb5adbb5a3744f8770bf0f09e35f6bdb0b2cc913fa8d']
    monthly = special.groupby(special.date_gregorian.dt.strftime('%Y-%m')).estimated_consumption.sum()
    monthly.to_csv(out / 'customer_229_bill_monthly.csv')
    result = dict(run=run.name, configuration=cfg, input_hashes=manifest['inputs'], metrics=metrics,
        bills_checked=len(ledger), max_bill_error=float(errors.max()),
        positive_winter_bills=len(grouped), near_zero_winter_bills=int((grouped < 1e-10).sum()),
        positive_winter_days=len(winter), near_zero_winter_days=int((winter.estimated_consumption < 1e-10).sum()),
        peak_to_mean_quantiles={str(q):float(peak_ratio.quantile(q)) for q in [.5,.9,.99]},
        minimum_daily_to_bill_mean=float((statistics['min']*statistics['size']/statistics['sum']).min()),
        customer_bill_sum=float(special.estimated_consumption.sum()),
        customer_winter_sum=float(special.loc[special.date_gregorian.between('2024-12-01', '2025-02-28'), 'estimated_consumption'].sum()),
        customer_february_sum=float(monthly.get('2025-02', 0)),
        customer_september_sum=float(monthly.get('2024-09', 0)),
        customer_bill_peak=float(special.estimated_consumption.max()),
        population_peak=manifest['peak'], wall_seconds=manifest['wall_seconds'])
    floor = cfg.get('redistribution_floor', 0)
    assert result['minimum_daily_to_bill_mean'] >= floor - 1e-9
    (out / 'metrics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ['run', 'customer_winter_sum', 'customer_september_sum', 'near_zero_winter_bills', 'minimum_daily_to_bill_mean', 'peak_to_mean_quantiles']}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    evaluate(parser.parse_args().run)
