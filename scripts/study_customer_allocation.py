"""Forensic replay of accepted experiment 05; writes separate audit artifacts."""
import json
import math
from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isd.config import Config
from isd.data import prepare_state, date_ordinal, sha256
from isd.pipeline import canonical
import isd.solver as solver

RUN = Path('outputs/experiment_all_types_05')
OUT = RUN / 'customer_study_15013341402'
CUSTOMER = '15013341402'


def plot_saved_study():
    """Write a self-contained SVG from saved evidence, without extra dependencies."""
    frame = pd.read_csv(OUT / 'customer_daily.csv')
    frame = frame[frame.bill_id == 'b0f9dca0e3c4bf0b56f6cb5adbb5a3744f8770bf0f09e35f6bdb0b2cc913fa8d']
    trace = pd.read_csv(OUT / 'bill_229_sweep_trace.csv')
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="720" viewBox="0 0 1100 720">',
           '<rect width="1100" height="720" fill="white"/>',
           '<style>text{font-family:Arial,sans-serif;fill:#263449;font-size:15px}.axis{stroke:#a0a8b0;fill:none}.grid{stroke:#e4e7eb}</style>',
           '<text x="70" y="32" style="font-size:22px;font-weight:bold">Customer 15013341402: where the 229 m³ was allocated</text>']
    def text(x, y, value):
        svg.append(f'<text x="{x}" y="{y}">{value}</text>')
    # Upper panel: linear consumption.
    x = lambda i: 90 + i/189*960
    y = lambda v: 285-v/12*220
    svg.append(f'<rect x="{x(91)}" y="65" width="{x(181)-x(91)}" height="220" fill="#fff0d7"/>')
    for v in [0, 3, 6, 9, 12]:
        svg.append(f'<path class="grid" d="M90 {y(v)} H1050"/>')
        text(45, y(v)+5, str(v))
    points = ' '.join(f'{x(i):.2f},{y(v):.2f}' for i, v in enumerate(frame.estimated_consumption))
    svg.append(f'<polyline points="{points}" fill="none" stroke="#147d92" stroke-width="2.5"/>')
    svg.append(f'<path d="M90 {y(229/190)} H1050" stroke="#777" stroke-dasharray="6,5"/>')
    text(90, 58, 'Daily allocation (m³/day)')
    for i, label in [(0, 'Sep 1'), (30, 'Oct 1'), (61, 'Nov 1'), (91, 'Dec 1'), (122, 'Jan 1'), (153, 'Feb 1'), (181, 'Mar 1')]:
        text(x(i)-15, 308, label)
    text(90, 338, 'Teal: accepted estimate | Dashed: uniform baseline, 1.205 m³/day (not ground truth)')
    text(90, 363, 'Orange: December–February validation period. Bill dates: September 2024–March 2025.')
    # Lower panel: log10 winter allocation across updates.
    xx = lambda n: 90+(n-1)/1249*960
    yy = lambda log: 640-(log+27)/30*220
    text(90, 402, 'Exact replay: winter allocation shrinks over 1,250 sweeps (logarithmic scale)')
    for exponent in [-25, -20, -15, -10, -5, 0]:
        svg.append(f'<path class="grid" d="M90 {yy(exponent)} H1050"/>')
        text(25, yy(exponent)+5, f'1e{exponent}')
    points = ' '.join(f'{xx(n):.2f},{yy(math.log10(v)):.2f}' for n, v in zip(trace.sweep, trace.winter_sum))
    svg.append(f'<polyline points="{points}" fill="none" stroke="#9a3c64" stroke-width="2.5"/>')
    for n in [1, 250, 500, 750, 1000, 1250]:
        text(xx(n)-15, 665, str(n))
    text(420, 699, 'Allocation sweep number')
    svg.append('</svg>')
    (OUT / 'allocation_diagnosis.svg').write_text('\n'.join(svg), encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((RUN / 'run_manifest.json').read_text())
    cfg = Config(**manifest['configuration'])
    normalized = pq.read_table(RUN / 'normalized_bills.parquet').to_pandas()
    bills = normalized[normalized.SubscriptionNumber == CUSTOMER]
    bills.to_csv(OUT / 'normalized_customer_bills.csv', index=False)
    raw_path = Path('data/prepared') / bills.source_file.iloc[0]
    assert sha256(raw_path) == bills.source_file_sha256.iloc[0]
    raw = pd.read_csv(raw_path, dtype={'SubscriptionNumber': str})
    raw[raw.SubscriptionNumber == CUSTOMER].to_csv(OUT / 'source_customer_bills.csv', index=False)
    daily = pq.read_table(RUN / 'target_customer_daily.parquet', filters=[('SubscriptionNumber', '=', CUSTOMER)]).to_pandas()
    daily.date_gregorian = pd.to_datetime(daily.date_gregorian)
    daily.to_csv(OUT / 'customer_daily.csv', index=False)
    bill = bills[bills.original_consumption == 229].iloc[0]
    target = daily[daily.bill_id == bill.bill_id].copy()
    assert len(target) == 190
    assert math.fsum(target.estimated_consumption) == 229
    full = pq.read_table(RUN / 'full_bill_daily.parquet', filters=[('bill_id', '=', bill.bill_id)]).to_pandas()
    assert np.array_equal(full.estimated_consumption, target.estimated_consumption)
    csv_feb = pd.read_csv(RUN / 'customer_reports/customer_daily_csv/2025-02.csv', dtype={'SubscriptionNumber': str}, float_precision='round_trip')
    feb = daily[daily.date_gregorian.between('2025-02-01', '2025-02-28')]
    assert np.array_equal(csv_feb[csv_feb.SubscriptionNumber == CUSTOMER].estimated_consumption, feb.estimated_consumption)
    monthly = target.groupby(target.date_gregorian.dt.strftime('%Y-%m')).estimated_consumption.agg(['sum', 'min', 'max'])
    monthly.to_csv(OUT / 'bill_229_monthly.csv')
    target.nlargest(20, 'estimated_consumption').to_csv(OUT / 'bill_229_largest_days.csv', index=False)

    # Reconstruct the original canonical modeled population and verify its checkpoint identity.
    rec = pq.read_table(RUN / 'bill_reconciliation.parquet').to_pandas()
    modeled = canonical(normalized[normalized.bill_id.isin(rec.loc[rec.method == 'cohort_exposure_isd', 'bill_id'])])
    with np.load(RUN / 'checkpoint.npz') as checkpoint:
        saved = {key: checkpoint[key].copy() for key in checkpoint.files}
    origin = date_ordinal(cfg.simulation_start)
    state = prepare_state(modeled, origin, len(saved['y']))
    assert state.identity_token == str(saved['source_order_identity'])
    assert solver.state_lock(state, saved['design'], saved['fit_mask'], cfg) == str(saved['lock'])
    index = int(np.flatnonzero(modeled.bill_id.to_numpy() == bill.bill_id)[0])
    lo, hi = state.offsets[index:index + 2]
    start = state.starts[index]
    dates = pd.date_range(bill.FromDate, periods=190)
    winter = (dates >= '2024-12-01') & (dates < '2025-03-01')
    feb_mask = (dates >= '2025-02-01') & (dates < '2025-03-01')
    zero_counts = np.zeros(190, dtype=int)
    trace, profiles = [], []
    original_sweep = solver.scaled_sweep

    def traced_sweep(a, y, p, starts, lengths, totals, offsets, alpha, atol, rtol):
        # Split at this bill without changing visit order or arithmetic.
        noops = original_sweep(a, y, p, starts[:index], lengths[:index], totals[:index], offsets[:index + 1], alpha, atol, rtol)
        residual = np.maximum(p[start:start + 190] - np.maximum(y[start:start + 190] - a[lo:hi], 0), 0)
        zero_counts[:] += residual == 0
        noops += original_sweep(a, y, p, starts[index:index + 1], lengths[index:index + 1], totals[index:index + 1], offsets[index:index + 2], alpha, atol, rtol)
        values = a[lo:hi].copy()
        n = len(trace) + 1
        trace.append(dict(sweep=n, outer=(n - 1)//cfg.n_disagg_cycles + 1,
            positive_residual_days=int((residual > 0).sum()),
            winter_positive_residual_days=int((residual[winter] > 0).sum()),
            winter_sum=math.fsum(values[winter]), february_sum=math.fsum(values[feb_mask]),
            september_sum=math.fsum(values[dates.month == 9]),
            bill_sum=math.fsum(values), min_daily=float(values.min()), max_daily=float(values.max())))
        if n % cfg.n_disagg_cycles == 0:
            profiles.append(pd.DataFrame({'date': dates, 'outer': n//cfg.n_disagg_cycles, 'consumption': values}))
            if n % 250 == 0:
                print(f'Replayed {n}/1250 sweeps; winter total={math.fsum(values[winter]):.6g}', flush=True)
        noops += original_sweep(a, y, p, starts[index + 1:], lengths[index + 1:], totals[index + 1:], offsets[index + 1:], alpha, atol, rtol)
        return noops

    solver.scaled_sweep = traced_sweep
    try:
        result = solver.solve(state, saved['design'], replace(cfg, checkpoint=False, resume=False), saved['fit_mask'], exposure=saved['g'])
    finally:
        solver.scaled_sweep = original_sweep
    assert np.array_equal(result.allocations, saved['a']), 'Replay differs from accepted allocations'
    assert np.array_equal(result.y, saved['y'])
    pd.DataFrame(trace).to_csv(OUT / 'bill_229_sweep_trace.csv', index=False)
    pd.concat(profiles).to_csv(OUT / 'bill_229_outer_profiles.csv', index=False)
    pd.DataFrame({'date': dates, 'zero_proposal_sweeps': zero_counts}).to_csv(OUT / 'zero_proposal_counts.csv', index=False)

    # Quantify similar behavior, excluding genuinely zero bills and uniform fallbacks.
    all_daily = pq.read_table(RUN / 'full_bill_daily.parquet', columns=['bill_id', 'SubscriptionNumber', 'date_gregorian', 'estimated_consumption', 'method']).to_pandas()
    all_daily.date_gregorian = pd.to_datetime(all_daily.date_gregorian)
    positive_ids = set(rec.loc[(rec.bill_total > 0) & (rec.method == 'cohort_exposure_isd'), 'bill_id'])
    sample = all_daily[(all_daily.date_gregorian >= '2024-12-01') & (all_daily.date_gregorian < '2025-03-01') & all_daily.bill_id.isin(positive_ids)]
    stats = sample.groupby(['bill_id', 'SubscriptionNumber']).estimated_consumption.agg(['size', 'sum', 'max']).reset_index()
    affected = stats[stats['max'] < 1e-10]
    affected.merge(rec[['bill_id', 'bill_total']], on='bill_id').to_csv(OUT / 'near_zero_winter_positive_bills.csv', index=False)
    summary = dict(customer=CUSTOMER, bill_total=229, bill_days=190,
        uniform_daily=229/190, uniform_winter_total=229/190*90,
        observed_winter_total=math.fsum(target.loc[target.date_gregorian.between('2024-12-01', '2025-02-28'), 'estimated_consumption']),
        observed_february_total=math.fsum(feb.estimated_consumption),
        theoretical_decay_floor=229/190*(1-cfg.alpha)**(cfg.n_lr_models*cfg.n_disagg_cycles),
        replay_exact_all_allocations=True, sweeps=len(trace),
        feb_zero_proposal_sweeps_min=int(zero_counts[feb_mask].min()), feb_zero_proposal_sweeps_max=int(zero_counts[feb_mask].max()),
        positive_modeled_winter_bills=len(stats), near_zero_winter_bills=len(affected),
        affected_customers=int(affected.SubscriptionNumber.nunique()),
        positive_bill_winter_days=len(sample), near_zero_positive_bill_winter_days=int((sample.estimated_consumption < 1e-10).sum()),
        source_file_hash_verified=True, csv_parquet_exact_match=True,
        source_manifest_sha256=sha256(RUN / 'run_manifest.json'))
    (OUT / 'study_summary.json').write_text(json.dumps(summary, indent=2))
    plot_saved_study()
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    if '--plot-only' in sys.argv:
        plot_saved_study()
    else:
        main()
