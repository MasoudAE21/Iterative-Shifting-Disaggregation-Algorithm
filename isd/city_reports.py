"""Bounded-memory reports from the pipeline's sorted, complete customer-day grid.

Report windows are half-open. A window's modeled peak uses only customers with
finite estimates on EVERY day of that window, never a changing population.
"""
from contextlib import ExitStack
from datetime import date
import csv
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont

from .data import date_ordinal, jalali_date, sha256


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def report_windows(settings, cfg):
    allowed = {'automatic_after_simulation', 'windows', 'include_all_saved', 'requested_dates',
               'requested_date_role', 'profile_customers', 'profile_sample_count', 'profile_seed',
               'export_monthly_daily_csv', 'measured_city_daily_csv', 'truth_scales',
               'excluded_metric_dates', 'metric_min_coverage_fraction', 'minimum_peak_cohort_fraction'}
    if set(settings)-allowed:
        raise ValueError(f'Unknown report settings: {sorted(set(settings)-allowed)}')
    for key in ['automatic_after_simulation', 'include_all_saved', 'export_monthly_daily_csv']:
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f'{key} must be boolean')
    windows = dict(settings.get('windows', {}))
    if settings.get('include_all_saved', True):
        windows['all_saved'] = [cfg['target_start'], cfg['target_end_exclusive']]
    if not windows:
        raise ValueError('At least one report window is required')
    for name, bounds in windows.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Window names must contain only letters, digits, underscores or hyphens')
        if name == 'customer_daily_csv':
            raise ValueError('Window name customer_daily_csv is reserved for monthly exports')
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f'{name}: expected [start, end_exclusive]')
        start, end = bounds
        date_ordinal(start); date_ordinal(end)
        if not cfg['target_start'] <= start < end <= cfg['target_end_exclusive']:
            raise ValueError(f'{name}: window outside saved target dates')
    for day in settings.get('requested_dates', []):
        date_ordinal(day)
        if not cfg['target_start'] <= day < cfg['target_end_exclusive']:
            raise ValueError(f'Requested date {day} outside saved target dates')
    count = settings.get('profile_sample_count', 12)
    if type(count) is not int or count < 0:
        raise ValueError('profile_sample_count must be a nonnegative integer')
    if any(not isinstance(x, str) for x in settings.get('profile_customers', [])):
        raise ValueError('profile_customers must be quoted string IDs')
    if not settings.get('truth_scales', [1.0]):
        raise ValueError('truth_scales cannot be empty')
    for scale in settings.get('truth_scales', [1.0]):
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not np.isfinite(scale) or scale <= 0:
            raise ValueError('truth_scales must be finite positive numbers')
    threshold = settings.get('metric_min_coverage_fraction', 1.0)
    if not isinstance(threshold, (int, float)) or not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('metric_min_coverage_fraction must be between 0 and 1')
    fraction = settings.get('minimum_peak_cohort_fraction', .8)
    if not isinstance(fraction, (int, float)) or not np.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError('minimum_peak_cohort_fraction must be between 0 and 1')
    return windows


def customer_blocks(source, cfg, batch_size=65536):
    """Yield whole-customer blocks; validate IDs, order and every saved date.

    Memory depends on a Parquet batch plus one customer, not the full city grid.
    Pipeline exports have a fixed date grid in sorted customer/date order.
    """
    expected = pd.date_range(cfg['target_start'], cfg['target_end_exclusive'], inclusive='left')
    days = len(expected)
    if days < 1:
        raise ValueError('Empty saved target grid')
    columns = ['SubscriptionNumber', 'date_gregorian', 'date_jalali',
               'estimated_consumption', 'bill_id', 'coverage_class', 'method',
               'estimate_status', 'reason']
    carry = pd.DataFrame()
    last_id = None
    for batch in pq.ParquetFile(source).iter_batches(batch_size=batch_size, columns=columns):
        frame = pd.concat([carry, batch.to_pandas()], ignore_index=True)
        take = len(frame) // days * days
        carry = frame.iloc[take:].copy()
        if not take:
            continue
        frame = frame.iloc[:take].copy()
        ids = frame.SubscriptionNumber.to_numpy().reshape(-1, days)
        if not (ids == ids[:, :1]).all():
            raise ValueError('Incomplete or unsorted customer grid')
        unique = ids[:, 0]
        if (last_id is not None and unique[0] <= last_id) or any(a >= b for a, b in zip(unique[:-1], unique[1:])):
            raise ValueError('Duplicate or unordered customer IDs')
        last_id = unique[-1]
        dates = pd.to_datetime(frame.date_gregorian).to_numpy(dtype='datetime64[D]').reshape(-1, days)
        if not (dates == expected.to_numpy(dtype='datetime64[D]')).all():
            raise ValueError('Missing, duplicate or unordered customer dates')
        values = frame.estimated_consumption.to_numpy(dtype=float).reshape(-1, days)
        if np.isinf(values).any() or (values < 0).any():
            raise ValueError('Nonfinite or negative daily allocation')
        yield frame, unique, values
    if len(carry):
        raise ValueError('Truncated customer grid')


def chart(path, title, x, series, unit):
    """Standalone PNG with explicit units; used for presentation line figures."""
    canvas = Image.new('RGB', (1500, 650), 'white')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=17)
    draw.text((30, 20), title, fill='black', font=font)
    draw.text((30, 58), unit, fill='#555555', font=small)
    left, top, width, height = 125, 115, 1300, 390
    all_values = np.concatenate([np.asarray(values, float) for _, values in series])
    finite = all_values[np.isfinite(all_values)]
    ymax = max(float(finite.max()) if len(finite) else 0, 1)
    for tick in range(5):
        yy = top + height * (1 - tick / 4)
        draw.line((left, yy, left + width, yy), fill='#dddddd')
        draw.text((5, yy - 8), f'{ymax*tick/4:,.0f}', fill='black', font=small)
    for i in np.linspace(0, len(x)-1, min(5, len(x)), dtype=int):
        draw.text((left + width*i/max(1, len(x)-1)-40, top+height+12), str(x[i])[:10], fill='black', font=small)
    colors = ['#245cb3', '#d15b20', '#338866', '#963db3']
    for k, (label, values) in enumerate(series):
        draw.text((left, 555 + 24*k), label, fill=colors[k % 4], font=small)
        previous = None
        for i, value in enumerate(values):
            if not np.isfinite(value):
                previous = None
                continue
            point = (left + width*i/max(1, len(x)-1), top+height*(1-value/ymax))
            if previous is not None:
                draw.line([previous, point], fill=colors[k % 4], width=2)
            previous = point
    canvas.save(path)


def ledger_metadata(run):
    columns = ['SubscriptionNumber', 'ConsumptionType', 'record_status', 'exclusion_reason',
               'floor_source', 'floor_feasibility_adjusted']
    frame = pq.read_table(run/'normalized_bills.parquet', columns=columns).to_pandas()
    types = frame.groupby('SubscriptionNumber').ConsumptionType.agg(lambda s: '|'.join(sorted(set(s.dropna().astype(str)))))
    counts = frame.record_status.value_counts().to_dict()
    accepted = frame[frame.record_status == 'accepted']
    floors = accepted[['SubscriptionNumber', 'floor_source']].drop_duplicates().floor_source.value_counts().to_dict()
    return types, {'bill_status_counts': {str(k): int(v) for k, v in counts.items()},
                   'exclusion_reasons': {str(k): int(v) for k, v in frame.exclusion_reason.value_counts().items()},
                   'floor_source_customer_counts': {str(k): int(v) for k, v in floors.items()},
                   'floor_feasibility_adjusted_bills': int(accepted.floor_feasibility_adjusted.sum())}


def export_city_reports(run_dir, destination, settings):
    """Create a fresh report directory; never modify or refit the source run."""
    run, out = Path(run_dir).resolve(), Path(destination).resolve()
    if out == run or run.is_relative_to(out):
        raise ValueError('Report directory must not replace the source run or its parent')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new empty report destination')
    source = run/'target_customer_daily.parquet'
    manifest = json.loads((run/'run_manifest.json').read_text(encoding='utf-8'))
    cfg = manifest['configuration']
    windows = report_windows(settings, cfg)
    dates = pd.date_range(cfg['target_start'], cfg['target_end_exclusive'], inclusive='left')
    days = len(dates)
    jalali_by_day = {day.strftime('%Y-%m-%d'): jalali_date(date_ordinal(day.strftime('%Y-%m-%d'))) for day in dates}
    requested = sorted(set(settings.get('requested_dates', [])))
    types, quality = ledger_metadata(run)
    absent = sorted(set(settings.get('profile_customers', []))-set(types.index))
    if absent:
        raise ValueError(f'Profile customer IDs absent from run: {absent}')
    out.mkdir(parents=True, exist_ok=True)
    write_json(out/'report_settings.json', settings)
    total = np.zeros(days); counts = np.zeros(days, dtype=np.int64)
    method_counts, reason_counts = {}, {}
    states = {}
    population = 0
    # Store only per-customer summaries, never the full city daily grid.
    summaries = []
    date_fields = ['SubscriptionNumber', 'date_gregorian', 'date_jalali', 'estimated_consumption',
                   'coverage_class', 'method', 'estimate_status', 'reason']
    peak_fields = ['SubscriptionNumber', 'peak_consumption_m3', 'peak_date_gregorian',
                   'peak_date_jalali', 'available_days', 'window_days', 'coverage_status',
                   'ConsumptionType', 'available_consumption_m3']
    with ExitStack() as stack:
        writers = {}
        def writer(key, path, fields):
            handle = stack.enter_context(path.open('w', newline='', encoding='utf-8'))
            writers[key] = csv.writer(handle); writers[key].writerow(fields)
        for day in requested:
            writer(('date', day), out/f'customers_on_{day}.csv', date_fields)
        for name, (start, end) in windows.items():
            folder = out/name; folder.mkdir()
            mask = (dates >= start) & (dates < end)
            states[name] = dict(mask=mask, sums=np.zeros(int(mask.sum())), cohort=0, start=start, end_exclusive=end)
            writer(('window', name), folder/'individual_customer_peaks.csv', peak_fields)
        for frame, ids, values in customer_blocks(source, cfg):
            valid = np.isfinite(values)
            population += len(ids)
            total += np.nansum(values, axis=0)
            counts += valid.sum(axis=0)
            for column, accumulator in [('method', method_counts), ('reason', reason_counts)]:
                for key, count in frame[column].fillna('none').value_counts().items():
                    accumulator[str(key)] = accumulator.get(str(key), 0) + int(count)
            for day in requested:
                offset = (pd.Timestamp(day)-dates[0]).days
                part = frame.iloc[np.arange(len(ids))*days+offset][date_fields]
                writers[('date', day)].writerows(part.astype(object).where(part.notna(), '').itertuples(index=False, name=None))
            for name, state in states.items():
                vals = values[:, state['mask']]
                available = np.isfinite(vals).sum(axis=1)
                full = available == vals.shape[1]
                state['cohort'] += int(full.sum())
                state['sums'] += vals[full].sum(axis=0)
                positions = np.where(np.isfinite(vals), vals, -np.inf).argmax(axis=1)
                peaks = vals[np.arange(len(ids)), positions]
                window_dates = dates[state['mask']]
                records = []
                for i, ident in enumerate(ids):
                    day = window_dates[positions[i]].strftime('%Y-%m-%d') if available[i] else ''
                    records.append([ident, float(peaks[i]) if available[i] else '', day,
                                    jalali_by_day[day] if day else '', int(available[i]), vals.shape[1],
                                    'complete' if full[i] else 'partial' if available[i] else 'unavailable',
                                    types.get(ident, ''), float(np.nansum(vals[i])) if available[i] else ''])
                writers[('window', name)].writerows(records)
            available = valid.sum(axis=1)
            for ident, count, value in zip(ids, available, np.nansum(values, axis=1)):
                summaries.append((ident, int(count), float(value) if count else np.nan, types.get(ident, '')))
    if not population:
        raise ValueError('No customer records in saved run')
    summary = pd.DataFrame(summaries, columns=['SubscriptionNumber', 'available_days', 'available_consumption_m3', 'ConsumptionType'])
    summary['coverage_status'] = np.where(summary.available_days == days, 'complete', np.where(summary.available_days > 0, 'partial', 'unavailable'))
    summary.to_csv(out/'customer_coverage.csv', index=False)
    # Never turn an entirely missing population day into a measured/modelled zero.
    total[counts == 0] = np.nan
    daily = pd.DataFrame({'date_gregorian': dates.strftime('%Y-%m-%d'),
                          'available_customer_sum_m3': total, 'available_customers': counts,
                          'input_customers': population, 'missing_customers': population-counts,
                          'coverage_fraction': counts/population})
    daily.to_csv(out/'daily_totals_and_coverage.csv', index=False)
    if (run/'aggregate_daily_summary.csv').is_file():
        from .config import Config
        from .tbs import export_simulation_comparison
        export_simulation_comparison(run, out, Config(**cfg))
    requested_summary = daily[daily.date_gregorian.isin(requested)].copy()
    requested_summary['date_role'] = settings.get('requested_date_role', 'User-selected comparison dates; not measured city peaks')
    requested_summary.to_csv(out/'requested_date_summary.csv', index=False)
    result = {'source_run': str(run), 'source_manifest_sha256': sha256(run/'run_manifest.json'),
              'source_daily_sha256': sha256(source), 'output_customers': population,
              'units': 'm3/day' if not cfg.get('divide_consumption_by_unit_count') else 'm3/unit/day',
              'requested_date_role': settings.get('requested_date_role', 'User-selected comparison dates; not measured city peaks'),
              'peak_policy': 'Fixed complete-coverage population within each window; earliest date on exact ties. Individual maxima use available days.',
              'missing_policy': 'Blank is unavailable; zero remains a valid numeric estimate.',
              'quality': quality, 'method_customer_days': method_counts, 'reason_customer_days': reason_counts,
              'windows': {}, 'requested_dates': requested}
    modeled_dates = {}
    for name, state in states.items():
        ds = dates[state['mask']]
        peak = int(np.argmax(state['sums'])) if state['cohort'] else None
        peak_day = ds[peak].strftime('%Y-%m-%d') if peak is not None else None
        cohort_values = state['sums'] if state['cohort'] else np.full(len(ds), np.nan)
        pd.DataFrame({'date_gregorian': ds.strftime('%Y-%m-%d'), 'fixed_cohort_sum_m3': cohort_values,
                      'fixed_cohort_customers': state['cohort']}).to_csv(out/name/'fixed_cohort_daily_totals.csv', index=False)
        result['windows'][name] = {'start': state['start'], 'end_exclusive': state['end_exclusive'],
                                   'cohort_customers': state['cohort'], 'modeled_peak_date': peak_day,
                                   'cohort_fraction_of_input': state['cohort']/population,
                                   'coverage_note': ('No complete-window customers' if not state['cohort'] else
                                      'Limited cohort: do not generalize to the whole city' if state['cohort']/population < settings.get('minimum_peak_cohort_fraction', .8) else
                                      'Fixed-window cohort; still not measured city demand'),
                                   'modeled_peak_m3': float(state['sums'][peak]) if peak is not None else None,
                                   'status': 'available' if peak is not None else 'no_complete_coverage_customers'}
        if peak_day:
            modeled_dates[name] = peak_day
        chart(out/name/'fixed_cohort_daily_totals.png', f'{name}: fixed-population modeled demand', ds.strftime('%Y-%m-%d'), [('Complete-window cohort', cohort_values)], result['units'])
        peaks = pd.read_csv(out/name/'individual_customer_peaks.csv', dtype={'SubscriptionNumber': str})
        histogram = peaks.peak_date_gregorian.value_counts().sort_index().rename_axis('date').reset_index(name='customers')
        histogram.to_csv(out/name/'individual_peak_date_counts.csv', index=False)
        if len(histogram):
            chart(out/name/'individual_peak_dates.png', f'{name}: individual peak dates', histogram.date.tolist(), [('Customers', histogram.customers)], 'Customers (earliest date on ties)')
        values = peaks.peak_consumption_m3.dropna()
        if len(values):
            frequencies, edges = np.histogram(values, bins=30)
            pd.DataFrame({'lower_m3': edges[:-1], 'upper_m3': edges[1:], 'customers': frequencies}).to_csv(out/name/'individual_peak_distribution.csv', index=False)
            chart(out/name/'individual_peak_distribution.png', f'{name}: individual peak magnitude distribution', [f'{x:.1f}' for x in edges[:-1]], [('Customers per bin', frequencies)], 'Customer count; x-axis peak '+result['units'])
        result['windows'][name]['individual_available'] = int(peaks.peak_consumption_m3.notna().sum())
    # One additional sequential pass exports every customer's value on each modeled
    # date and membership in the exact cohort used to select that window's peak.
    with ExitStack() as stack:
        writers = {}
        for name in modeled_dates:
            writers[name] = csv.writer(stack.enter_context((out/name/'customers_on_modeled_peak.csv').open('w', newline='', encoding='utf-8')))
            writers[name].writerow(date_fields+['in_peak_selection_population'])
        if writers:
            for frame, ids, values in customer_blocks(source, cfg):
                for name, day in modeled_dates.items():
                    offsets = np.arange(len(ids))*days + (pd.Timestamp(day)-dates[0]).days
                    part = frame.iloc[offsets][date_fields].copy()
                    part['in_peak_selection_population'] = np.isfinite(values[:, states[name]['mask']]).all(axis=1)
                    writers[name].writerows(part.astype(object).where(part.notna(), '').itertuples(index=False, name=None))
    chart(out/'daily_demand.png', 'Available-customer demand (population may vary)', dates.strftime('%Y-%m-%d'), [('Available-customer sum', total)], result['units'])
    chart(out/'daily_coverage.png', 'Daily customer coverage', dates.strftime('%Y-%m-%d'), [('Available customers', counts), ('Missing customers', population-counts)], 'Customers')
    result['profiles'] = export_profiles(run, out, settings, summary, cfg)
    result['metrics'] = export_metrics(out, settings, daily, windows)
    if settings.get('export_monthly_daily_csv', False):
        from .customer_reports import export_daily_csv
        result['monthly_daily_csv'] = export_daily_csv(source, out/'customer_daily_csv')
    quality['available_customer_days'] = int(counts.sum())
    quality['missing_customer_days'] = int(population*days-counts.sum())
    quality_rows = [{'metric': 'input_customers', 'value': population},
                    {'metric': 'saved_customer_days', 'value': population*days},
                    {'metric': 'available_customer_days', 'value': int(counts.sum())},
                    {'metric': 'missing_customer_days', 'value': int(population*days-counts.sum())},
                    {'metric': 'available_customer_day_fraction', 'value': float(counts.sum()/(population*days))}]
    for key in ['bill_status_counts', 'floor_source_customer_counts']:
        quality_rows += [{'metric': key+'.'+str(name), 'value': value} for name, value in quality[key].items()]
    validation_path = run/'validation.json'
    if validation_path.exists():
        validation = json.loads(validation_path.read_text(encoding='utf-8'))
        if isinstance(validation, dict):
            result['simulation_validation'] = validation
            quality_rows += [{'metric': 'validation.'+key, 'value': value} for key, value in validation.items()
                             if isinstance(value, (float, int))]
    pd.DataFrame(quality_rows).to_csv(out/'quality_metrics.csv', index=False)
    write_json(out/'report_manifest.json', result)
    write_summary(out, result)
    write_json(out/'completion.json', {'status': 'complete', 'source_run': str(run), 'customers': population})
    return result


def export_profiles(run, out, settings, summary, cfg):
    from scripts.run_hyperparameter_experiments import add_uniform_allocations, plot_profiles
    fixed = list(dict.fromkeys(settings.get('profile_customers', [])))
    missing = sorted(set(fixed)-set(summary.SubscriptionNumber))
    if missing:
        raise ValueError(f'Profile customer IDs absent from run: {missing}')
    count = settings.get('profile_sample_count', 12)
    seed = settings.get('profile_seed', 20261111)
    candidates = summary[~summary.SubscriptionNumber.isin(fixed)].copy()
    # Deterministic round-robin strata: consumption type, coverage, consumption order of magnitude.
    candidates['magnitude'] = np.floor(np.log10(candidates.available_consumption_m3.fillna(0).clip(lower=1))).astype(int)
    candidates['hash'] = candidates.SubscriptionNumber.map(lambda x: hashlib.sha256(f'{seed}:{x}'.encode()).hexdigest())
    candidates = candidates.sort_values('hash')
    groups = [list(g.SubscriptionNumber) for _, g in candidates.groupby(['ConsumptionType', 'coverage_status', 'magnitude'], sort=True)]
    sample = []
    for i in range(count):
        available = [g for g in groups if g]
        if not available:
            break
        sample.append(available[i % len(available)].pop(0))
    selected = fixed + sample
    write_json(out/'profile_selection.json', {'seed': seed, 'fixed': fixed, 'sampled': sample, 'selected': selected,
               'policy': 'Deterministic sample stratified by type, coverage and available-consumption magnitude; not population-representative.'})
    if not selected:
        return {'customers': 0}
    daily = pq.read_table(run/'target_customer_daily.parquet', filters=[('SubscriptionNumber', 'in', selected)]).to_pandas()
    ledger = pq.read_table(run/'normalized_bills.parquet', filters=[('SubscriptionNumber', 'in', selected)]).to_pandas()
    daily = add_uniform_allocations(daily, ledger).sort_values(['SubscriptionNumber', 'date_gregorian'])
    daily.to_csv(out/'customer_profiles.csv', index=False)
    # Paginate so presentation images remain legible with larger configured samples.
    for page, start in enumerate(range(0, len(selected), 12), 1):
        curves = [(ident, [('Estimated consumption', pd.to_datetime(p.date_gregorian), p.estimated_consumption.to_numpy()),
                           ('Uniform bill allocation', pd.to_datetime(p.date_gregorian), p.uniform_consumption_m3.to_numpy())])
                  for ident in selected[start:start+12] for p in [daily[daily.SubscriptionNumber == ident]]]
        plot_profiles(out/f'customer_profiles_{page:02d}.png', curves, 'Customer daily estimates and uniform bill allocation')
    return {'customers': len(selected), 'selected': selected}


def export_metrics(out, settings, daily, windows):
    from scripts.run_hyperparameter_experiments import metric_reports
    measured = settings.get('measured_city_daily_csv')
    if not measured:
        pd.DataFrame(columns=['window', 'truth_scale', 'mape_percent', 'rmse_m3', 'r2', 'pearson_r', 'matched_days']).to_csv(out/'metrics.csv', index=False)
        return {'status': 'unavailable', 'reason': 'No measured city daily totals supplied; no measured accuracy claimed.'}
    actual = pd.read_csv(measured)
    if not {'date_gregorian', 'consumption_m3'} <= set(actual):
        raise ValueError('Measured city CSV requires date_gregorian,consumption_m3')
    actual['date_gregorian'] = pd.to_datetime(actual.date_gregorian, format='%Y-%m-%d', errors='raise').dt.strftime('%Y-%m-%d')
    if actual.date_gregorian.duplicated().any():
        raise ValueError('Duplicate measured city dates')
    actual['consumption_m3'] = pd.to_numeric(actual.consumption_m3, errors='raise')
    if np.isinf(actual.consumption_m3).any() or (actual.consumption_m3 < 0).any():
        raise ValueError('Invalid measured city consumption')
    threshold = settings.get('metric_min_coverage_fraction', 1.0)
    if not 0 <= threshold <= 1:
        raise ValueError('metric_min_coverage_fraction must be between 0 and 1')
    pairs = daily.merge(actual[['date_gregorian', 'consumption_m3']], on='date_gregorian', how='left')
    pairs['final_algorithm_consumption_m3'] = pairs.available_customer_sum_m3.where(pairs.coverage_fraction >= threshold)
    pairs['tbs_daily_m3'] = pairs.consumption_m3
    bounds = {name: [start, (pd.Timestamp(end)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')] for name, (start, end) in windows.items()}
    scores, masks = metric_reports(pairs, bounds, settings.get('excluded_metric_dates', []), settings.get('truth_scales', [1.0]))
    for name, mask in masks.items():
        pairs['metric_include_'+name] = mask & pairs.final_algorithm_consumption_m3.notna() & pairs.tbs_daily_m3.notna()
    pairs.to_csv(out/'metric_daily_pairs.csv', index=False)
    pd.DataFrame(scores).to_csv(out/'metrics.csv', index=False)
    chart(out/'measured_city_comparison.png', 'City totals: modeled and measured', pairs.date_gregorian.tolist(), [('Available-customer sum', pairs.available_customer_sum_m3), ('Measured city total', pairs.consumption_m3)], 'm3/day; scoring coverage threshold shown in manifest')
    return {'status': 'evaluated', 'measured_sha256': sha256(measured), 'minimum_coverage_fraction': threshold,
            'population_note': 'User must ensure measured and modeled city populations correspond.', 'rows': scores}


def write_summary(out, result):
    rows = ['# City report', '', 'Retrospective estimated customer consumption; not measured customer daily truth.', '',
            f"Input customers: {result['output_customers']:,}. Units: {result['units']}.", '',
            result['peak_policy'], '', result['missing_policy'], '',
            'Requested dates: '+', '.join(result['requested_dates'])+'. '+result['requested_date_role'], '',
            '| Window | Fixed cohort | Input coverage | Modeled peak date | Modeled peak |', '|---|---:|---:|---|---:|']
    for name, value in result['windows'].items():
        rows.append(f"| {name} | {value['cohort_customers']} | {value['cohort_fraction_of_input']:.1%} | {value['modeled_peak_date'] or 'Unavailable'} | {value['modeled_peak_m3'] if value['modeled_peak_m3'] is not None else 'Unavailable'} |")
    rows += ['', *[f"- {name}: {value['coverage_note']}." for name, value in result['windows'].items()]]
    rows += ['', 'Measured accuracy: '+result['metrics']['status']+'.',
             result['metrics'].get('reason', 'See metrics.csv and metric_daily_pairs.csv for paired dates, coverage filtering and truth scales.'), '',
             'Available-customer sums have a changing population; use the fixed-cohort curves to identify modeled peaks.', '',
             'Individual peaks use available days and may underestimate true peaks for partially covered customers.', '',
             'Profile samples include type, coverage and consumption-magnitude strata; they are illustrative, not representative.', '',
             '![Daily demand](daily_demand.png)', '', '![Coverage](daily_coverage.png)', '',
             'Bill status, floor sources, fallback/missing reasons, units and source hashes are in report_manifest.json.']
    (out/'report.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')
