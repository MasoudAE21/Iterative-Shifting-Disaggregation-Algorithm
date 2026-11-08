"""Trace customer source bills, eligibility, and final allocations in saved runs."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_hyperparameter_experiments import add_uniform_allocations, plot_profiles


def trace_customer(batch, customer, before_batch=None):
    output = batch / f'customer_trace_{customer}'
    output.mkdir(exist_ok=True)
    bill_rows, daily_rows, current_curves = [], [], []
    stages = [('corrected', batch)]
    if before_batch is not None:
        stages.insert(0, ('previous', before_batch))
    for stage, directory in stages:
        provenance = json.loads((directory / 'validation.json').read_text(encoding='utf-8'))
        for model in provenance:
            folder = directory / model['model']
            manifest = json.loads((folder / 'run_manifest.json').read_text(encoding='utf-8'))
            ledger = pd.read_parquet(folder / 'normalized_bills.parquet')
            bills = ledger[ledger.SubscriptionNumber == customer]
            daily = pq.read_table(folder / 'target_customer_daily.parquet',
                                  filters=[('SubscriptionNumber', '=', customer)]).to_pandas()
            if daily.empty or bills.empty:
                raise ValueError(f'Customer {customer} absent from {folder}')
            daily['date_gregorian'] = pd.to_datetime(daily.date_gregorian)
            daily = add_uniform_allocations(daily, ledger).sort_values('date_gregorian')
            daily_rows.append(daily.assign(stage=stage, model=model['model']))
            saved = pq.read_table(folder / 'full_bill_daily.parquet',
                                  filters=[('SubscriptionNumber', '=', customer)]).to_pandas()
            saved['date_gregorian'] = pd.to_datetime(saved.date_gregorian)
            for bill in bills.itertuples():
                part = saved[saved.bill_id == bill.bill_id]
                start, end = pd.Timestamp(bill.start_day), pd.Timestamp(bill.end_day_exclusive)
                outside = int(((part.date_gregorian < start) | (part.date_gregorian >= end)).sum())
                if bill.record_status == 'accepted':
                    expected = pd.date_range(start, end, inclusive='left').tolist()
                    if part.date_gregorian.tolist() != expected or outside:
                        raise ValueError('Saved bill allocations do not match the bill period')
                    if not np.isclose(part.estimated_consumption.sum(), bill.Consumption, atol=1e-8, rtol=1e-10):
                        raise ValueError('Bill volume moved or lost')
                bill_rows.append(dict(stage=stage, model=model['model'],
                    coverage_policy=manifest['configuration']['coverage_policy'],
                    coverage_class=daily.coverage_class.iloc[0], bill_id=bill.bill_id,
                    source_FromDate=bill.raw_FromDate, source_ToDate=bill.raw_ToDate,
                    source_Consumption=bill.raw_Consumption,
                    effective_FromDate=bill.FromDate, effective_ToDate=bill.ToDate,
                    effective_Consumption=bill.Consumption, window_action=bill.window_action,
                    day_count=bill.day_count, model_group_id=bill.model_group_id,
                    method=','.join(part.method.unique()), allocated_days=len(part),
                    allocated_first_day=str(part.date_gregorian.min().date()),
                    allocated_last_day=str(part.date_gregorian.max().date()),
                    allocated_sum=float(part.estimated_consumption.sum()), outside_bill_days=outside))
            if stage == 'corrected':
                current_curves.append((model['model'], daily.date_gregorian, daily.estimated_consumption.to_numpy()))
                uniform = daily
    current_curves.append(('Uniform bill allocation', uniform.date_gregorian, uniform.uniform_consumption_m3.to_numpy()))
    panels = [(customer + ' full simulation', current_curves)]
    winter_curves = []
    for name, dates, values in current_curves:
        mask = dates.between('2024-11-15', '2025-03-15').to_numpy()
        winter_curves.append((name, dates[mask], values[mask]))
    panels.append((customer + ' winter', winter_curves))
    plot_profiles(output / 'customer_profiles.png', panels, 'Models and uniform allocations on the customer bill support', columns=1)
    pd.DataFrame(bill_rows).to_csv(output / 'bill_trace.csv', index=False)
    combined = pd.concat(daily_rows, ignore_index=True)
    combined.to_csv(output / 'daily_trace.csv', index=False)
    summaries = []
    for (stage, model), frame in combined.groupby(['stage', 'model'], sort=False):
        supported = frame.estimated_consumption.notna()
        summaries.append(dict(stage=stage, model=model,
            covered_days=int(supported.sum()), uncovered_days=int((~supported).sum()),
            modeled_days=int(frame.method.str.endswith('_isd').sum()),
            uniform_fallback_days=int(frame.method.eq('uniform_full_interval').sum()),
            uncovered_dates=frame.loc[~supported, 'date_gregorian'].dt.strftime('%Y-%m-%d').tolist()))
    (output / 'summary.json').write_text(json.dumps(summaries, indent=2), encoding='utf-8')
    lines = [f'# Customer {customer}: allocation trace', '',
             '1. Read the source FromDate/ToDate as inclusive bill dates; convert to a half-open interval for array indexing.',
             '2. Apply the configured window policy. Boundary proration may retain only part of a source bill total; bill_trace.csv records both source and effective dates/totals.',
             '3. Classify target coverage. The previous balanced policy sent an entire partial customer to uniform fallback, even when only one target day was uncovered.',
             '4. Under observed_support_isd_v1, include accepted full and partial histories in ISD and use daily exposure for the supported modeled population. Internal and edge gaps remain blank.',
             '5. Initialize each bill within its own array slice; update and reconcile that same slice during disaggregation. The Fourier branch also applies its customer-weather smoothing within those bill slices.',
             '6. Export each bill only on its interval. This trace checks every customer bill date and total; the experiment validator independently checks every bill-day in the full population.', '',
             '| Stage | Model | Covered days | ISD days | Uniform fallback days | Missing days |',
             '|---|---|---:|---:|---:|---:|']
    for item in summaries:
        lines.append(f'| {item["stage"]} | {item["model"]} | {item["covered_days"]} | '
                     f'{item["modeled_days"]} | {item["uniform_fallback_days"]} | {item["uncovered_days"]} |')
    lines += ['', 'All accepted customer bills have exactly their own expected dates, conserved effective totals, and zero outside-period allocations.',
              'The daily CSV retains uncovered dates as missing values; they are not zeros or consumption assigned from another bill.', '',
              '![Customer profiles](customer_profiles.png)', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(pd.DataFrame(summaries).to_string(index=False))
    print(f'Customer trace: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--customer', required=True)
    parser.add_argument('--before-batch', type=Path)
    args = parser.parse_args()
    trace_customer(args.batch.resolve(), args.customer,
                   args.before_batch.resolve() if args.before_batch else None)


if __name__ == '__main__':
    main()
