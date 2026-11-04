"""Read-only extraction of customer reports from accepted daily allocations."""
import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .data import sha256

COLUMNS = ['SubscriptionNumber', 'date_gregorian', 'estimated_consumption',
           'coverage_class', 'method', 'estimate_status', 'reason']


def export_daily_csv(source, destination, enabled=True):
    """Stream monthly CSVs, including missing days, without loading the full grid.

    Only files owned by this exporter are removed when disabling or regenerating.
    """
    destination = Path(destination)
    marker = destination / 'daily_export_manifest.json'
    if marker.exists():
        previous = json.loads(marker.read_text(encoding='utf-8'))
        for name in previous['files']:
            if Path(name).name != name or not name.endswith('.csv'):
                raise ValueError('Invalid daily export filename')
            (destination / name).unlink(missing_ok=True)
        marker.unlink()
    if not enabled:
        return None
    destination.mkdir(parents=True, exist_ok=True)
    counts = {}
    for batch in pq.ParquetFile(source).iter_batches(batch_size=65536, columns=COLUMNS):
        frame = batch.to_pandas()
        months = pd.to_datetime(frame.date_gregorian).dt.strftime('%Y-%m')
        for month, group in frame.groupby(months, sort=True):
            name = month + '.csv'
            group.to_csv(destination / name, index=False,
                         mode='a' if name in counts else 'w', header=name not in counts)
            counts[name] = counts.get(name, 0) + len(group)
    report = {'rows': sum(counts.values()), 'files': counts,
              'source_sha256': sha256(source), 'units': 'same as source run',
              'missing_policy': 'Blank consumption means unavailable, not zero.'}
    marker.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def export_peak_reports(run_dir, destination, windows):
    """Use the run's fixed full-target cohort for both peak-search windows.

    Window ends are exclusive. Customer maxima use all available estimates;
    missing customer-days are counted, never filled with zero.
    """
    run_dir, destination = Path(run_dir), Path(destination)
    source = run_dir / 'target_customer_daily.parquet'
    manifest = json.loads((run_dir / 'run_manifest.json').read_text(encoding='utf-8'))
    cfg = manifest['configuration']
    states = {}
    for name, bounds in windows.items():
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('Invalid window name')
        start, end = bounds
        if not cfg['target_start'] <= start < end <= cfg['target_end_exclusive']:
            raise ValueError('Requested window is outside saved customer daily dates')
        states[name] = dict(start=start, end=end, totals={}, counts={}, best={}, available={}, rows={})
    population, customers = set(), set()
    for batch in pq.ParquetFile(source).iter_batches(batch_size=65536, columns=COLUMNS):
        frame = batch.to_pandas()
        customers.update(frame.SubscriptionNumber)
        population.update(frame.loc[frame.coverage_class == 'full', 'SubscriptionNumber'])
        frame['date_gregorian'] = pd.to_datetime(frame.date_gregorian)
        values = frame.estimated_consumption.dropna()
        if not values.map(math.isfinite).all() or (values < 0).any():
            raise ValueError('Invalid daily estimate')
        for state in states.values():
            part = frame[(frame.date_gregorian >= state['start']) & (frame.date_gregorian < state['end'])]
            for ident, count in part.groupby('SubscriptionNumber').size().items():
                state['rows'][ident] = state['rows'].get(ident, 0) + int(count)
            valid = part.dropna(subset=['estimated_consumption'])
            for ident, count in valid.groupby('SubscriptionNumber').size().items():
                state['available'][ident] = state['available'].get(ident, 0) + int(count)
            winners = valid.sort_values(['estimated_consumption', 'date_gregorian'], ascending=[False, True]).drop_duplicates('SubscriptionNumber')
            for row in winners.itertuples(index=False):
                candidate = (float(row.estimated_consumption), row.date_gregorian.strftime('%Y-%m-%d'))
                old = state['best'].get(row.SubscriptionNumber)
                if old is None or (-candidate[0], candidate[1]) < (-old[0], old[1]):
                    state['best'][row.SubscriptionNumber] = candidate
            for day, group in part[part.coverage_class == 'full'].groupby('date_gregorian'):
                if group.estimated_consumption.isna().any():
                    raise ValueError('Missing full-cohort value')
                state['totals'].setdefault(day, []).append(math.fsum(group.estimated_consumption))
                state['counts'][day] = state['counts'].get(day, 0) + len(group)
    summary = {'source_run': str(run_dir.resolve()), 'source_sha256': sha256(source),
               'source_manifest_sha256': sha256(run_dir / 'run_manifest.json'),
               'consumption_unit': cfg['consumption_unit'], 'population_customers': len(population),
               'output_customers': len(customers),
               'policy': 'Fixed full-target coverage cohort from accepted run; earliest date on ties. Individual maxima use available days only.',
               'windows': {}}
    for name, state in states.items():
        days = (pd.Timestamp(state['end']) - pd.Timestamp(state['start'])).days
        if not population or len(state['counts']) != days or any(n != len(population) for n in state['counts'].values()):
            raise ValueError('Incomplete peak-selection population')
        if any(state['rows'].get(ident) != days for ident in customers):
            raise ValueError('Incomplete customer date grid')
        totals = {day: math.fsum(parts) for day, parts in state['totals'].items()}
        peak = min(totals, key=lambda day: (-totals[day], day))
        folder = destination / name
        folder.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{'date_gregorian': day.date(), 'population_consumption': value,
                       'population_customers': len(population)} for day, value in sorted(totals.items())]).to_csv(folder / 'population_daily_totals.csv', index=False)
        same_day = pq.read_table(source, columns=COLUMNS, filters=[('date_gregorian', '=', peak.date())]).to_pandas()
        same_day['in_peak_selection_population'] = same_day.SubscriptionNumber.isin(population)
        same_day.sort_values('SubscriptionNumber').to_csv(folder / 'customers_on_town_peak_day.csv', index=False)
        records = []
        for ident in sorted(customers):
            value, day = state['best'].get(ident, (None, None))
            count = state['available'].get(ident, 0)
            records.append(dict(SubscriptionNumber=ident, peak_date=day, peak_consumption=value,
                                available_days=count, window_days=days,
                                coverage_status='complete' if count == days else 'partial' if count else 'unavailable'))
        pd.DataFrame(records).to_csv(folder / 'individual_customer_peaks.csv', index=False)
        summary['windows'][name] = dict(start=state['start'], end_exclusive=state['end'],
            peak_date=str(peak.date()), population_peak_consumption=totals[peak],
            same_day_available=int(same_day.estimated_consumption.notna().sum()),
            individual_available=len(state['best']))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'report_manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary
