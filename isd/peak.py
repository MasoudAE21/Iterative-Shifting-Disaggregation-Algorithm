"""Fixed complete-coverage population peak and same-day customer export."""
from collections import Counter
from datetime import date, timedelta
import csv, json, math
import numpy as np
import pyarrow.parquet as pq

def choose_peak(dates, totals):
    if len(dates) == 0 or not np.isfinite(totals).all() or np.any(np.asarray(totals) < 0):
        raise ValueError('No valid peak totals')
    return min(range(len(dates)), key=lambda day_index: (-totals[day_index], dates[day_index]))

def export_peak(out, classes, cfg):
    """Export either same-day population values or individual customer peaks."""
    if cfg.peak_mode == 'individual':
        return export_individual_peaks(out, classes, cfg)
    if cfg.peak_mode != 'population':
        raise ValueError('Unknown peak mode')
    dates = [date.fromisoformat(cfg.target_start) + timedelta(days=day_index) for day_index in range((date.fromisoformat(cfg.target_end_exclusive) - date.fromisoformat(cfg.target_start)).days)]
    population = {str(c) for c, (kind, _) in classes.items() if kind == 'full'}
    if not population:
        raise ValueError('No complete-coverage customers for peak selection')
    totals = np.zeros(len(dates))
    compensation = np.zeros(len(dates))
    counts = np.zeros(len(dates), dtype=np.int64)
    index = {d: day_index for day_index, d in enumerate(dates)}
    path = out / 'target_customer_daily.parquet'
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=['SubscriptionNumber', 'date_gregorian', 'estimated_consumption']):
        rows = batch.to_pydict()
        for customer_id, day, value in zip(*rows.values()):
            if customer_id not in population:
                continue
            if value is None or not math.isfinite(value) or value < 0:
                raise ArithmeticError('Invalid peak population estimate')
            day_index = index[day]
            adjusted_value = value - compensation[day_index]
            next_total = totals[day_index] + adjusted_value
            compensation[day_index] = next_total - totals[day_index] - adjusted_value
            totals[day_index] = next_total
            counts[day_index] += 1
    if not np.all(counts == len(population)):
        raise ArithmeticError('Peak population coverage mismatch')
    peak_index = choose_peak(dates, totals)
    peak_day = dates[peak_index]
    with (out / 'peak_daily_totals.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'estimated_daily_total', 'peak_selection_customers'])
        writer.writerows(((d.isoformat(), repr(float(next_total)), len(population)) for d, next_total in zip(dates, totals)))
    selected = pq.read_table(path, filters=[('date_gregorian', '=', peak_day)], columns=['SubscriptionNumber', 'estimated_consumption', 'reason']).to_pydict()
    customer_ids = selected['SubscriptionNumber']
    values = selected['estimated_consumption']
    if len(customer_ids) != len(classes) or len(set(customer_ids)) != len(customer_ids) or set(customer_ids) != set(classes):
        raise ArithmeticError('Peak export customer identity mismatch')
    reasons = Counter()
    peak_values = []
    available_count = zero_count = 0
    with (out / 'customer_peak_consumption.csv').open('w', newline='', encoding='utf-8') as f, (out / 'peak_missing_reasons.csv').open('w', newline='', encoding='utf-8') as missing:
        writer = csv.writer(f)
        writer.writerow(['SubscriptionNumber', 'peakCosumptionValue'])
        missing_writer = csv.writer(missing)
        missing_writer.writerow(['SubscriptionNumber', 'reason'])
        for customer_id, value, reason in zip(customer_ids, values, selected['reason']):
            if value is None:
                reasons[reason] += 1
                missing_writer.writerow([customer_id, reason])
                text = ''
            else:
                if not math.isfinite(value) or value < 0:
                    raise ArithmeticError('Invalid peak output value')
                text = repr(float(value))
                available_count += 1
                zero_count += value == 0
                if customer_id in population:
                    peak_values.append(float(text))
            writer.writerow([customer_id, text])
    reconciled = math.fsum(peak_values)
    if not math.isclose(reconciled, float(totals[peak_index]), rel_tol=1e-14, abs_tol=1e-08):
        raise ArithmeticError('Peak CSV reconciliation')
    with (out / 'customer_peak_consumption.csv').open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ['SubscriptionNumber', 'peakCosumptionValue']:
            raise ArithmeticError('Peak CSV header')
        exported = list(reader)
    if [r['SubscriptionNumber'] for r in exported] != customer_ids:
        raise ArithmeticError('CSV ID roundtrip')
    for row, value in zip(exported, values):
        if row['peakCosumptionValue'] == '' if value is None else float(row['peakCosumptionValue']) == value:
            continue
        raise ArithmeticError('CSV value roundtrip')
    return {
        'date': peak_day.isoformat(),
        'total': float(totals[peak_index]),
        'population_customers': len(population),
        'output_customers': len(customer_ids),
        'available_values': available_count,
        'valid_zeros': int(zero_count),
        'missing_values': sum(reasons.values()),
        'missing_reasons': dict(reasons),
        'top_five': [{'date': dates[day_index].isoformat(), 'total': float(totals[day_index])} for day_index in sorted(range(len(dates)), key=lambda day_index: (-totals[day_index], dates[day_index]))[:5]],
        'csv_population_sum': reconciled,
        'csv_integrity_passed': True,
        'rounding': 'Shortest round-trip float64 decimal (Python repr); no fixed decimal rounding. Compensated float64 totals select the peak before export.',
        'policy': 'Fixed full-target valid-billing population; exact ties choose earliest date. All output customers use that same date.',
    }

def write_peak_summary(out, manifest):
    if manifest['configuration'].get('peak_mode', 'population') == 'individual':
        write_individual_peak_summary(out, manifest)
        return
    peak = manifest['peak']
    configuration = manifest['configuration']
    source_audit = manifest['source_audit']
    export_audit = manifest['export']
    lines = [
        '# Modeled population daily peak',
        '',
        f"Target: {configuration['target_start']} through {date.fromisoformat(configuration['target_end_exclusive']) - timedelta(days=1)}, inclusive; Asia/Tehran civil days.",
        f"Selected date: **{peak['date']}**. Units: **{configuration['consumption_unit']} per day**, preserving original bill totals without conversion.",
        f"Input: {source_audit['customers']:,} distinct customers, {source_audit['rows']:,} bills. Selected output: {peak['output_customers']:,} customers; accepted/fully reconciled bills: {export_audit['bill_reconciliation_passed']:,}.",
        f"Fixed peak-selection population: {peak['population_customers']:,} fully covered customers. Source coverage: {manifest['selection']['source_coverage_counts']}. This is a modeled population peak, not a full-city peak.",
        f"Peak total: {peak['total']!r}. Exported population sum: {peak['csv_population_sum']!r}.",
        '',
        '## Highest five daily totals',
        '',
    ]
    lines += [f"- {entry['date']}: {entry['total']!r}" for entry in peak['top_five']]
    lines += [
        '',
        f"Missing output values: {peak['missing_values']:,}; reasons: {peak['missing_reasons']}. Customer-level reasons are in peak_missing_reasons.csv. Available: {peak['available_values']:,}; retained zeros: {peak['valid_zeros']:,}.",
        peak['policy'],
        peak['rounding'],
        '',
        '## Verification and review',
        f"Full-bill reconciliation passed: {export_audit['bill_reconciliation_passed']:,}; maximum absolute discrepancy: {export_audit['max_bill_abs_discrepancy']!r}. Full/target identities passed: {export_audit['full_target_export_identities_passed']}. CSV identity, unique row, finite nonnegative value and round-trip reconciliation checks passed: {peak['csv_integrity_passed']}.",
        'Review F1: narrowly classified availability fallback; operational/checkpoint/configuration errors propagate. F2: advancing bill cursor replaces retained customer DataFrames. F3: reject blank/whitespace and multiline physical CSV records before normalization. See handoff/peak_review_resolutions.md and verification artifacts.',
        'Optional O1–O3 are deferred: the current target remains 1403, metadata remains provisional and RSS measurement is available locally.',
        'No measured daily accuracy is claimed. Existing cohort ISD, exposure adaptation, uniform full-bill fallback and missing-value policies remain unchanged. Physical units, billing semantics, weather representativeness and customer daily accuracy remain unconfirmed. No hourly conversion, external data or city scaling was applied.',
        '',
        '## Runtime and reproducibility',
        f"Wall seconds: {manifest['wall_seconds']:.6f}; peak process RSS bytes: {manifest['peak_rss_bytes']:,}.",
        f"Stage times: {manifest['stage_wall_seconds']}",
        'Run from the IDE with run_pipeline.py; defaults select all available input customers. production=False retains the provisional semantic gates.',
        'Configuration and hashes (SHA256):',
        '```json',
        json.dumps({
            'configuration': configuration,
            'inputs': manifest['inputs'],
            'source': manifest['code'],
            'dependencies': manifest['dependencies'],
        }, indent=2),
        '```',
    ]
    (out / 'peak_summary.md').write_text('\n\n'.join(lines) + '\n', encoding='utf-8')


def export_individual_peaks(out, classes, cfg):
    """Select each customer's maximum available target-day value, earliest on ties."""
    start = date.fromisoformat(cfg.target_start)
    end = date.fromisoformat(cfg.target_end_exclusive)
    n_days = (end - start).days
    if n_days <= 0:
        raise ValueError('Empty peak target window')
    seen = {str(customer_id): 0 for customer_id in classes}
    best = {}
    missing_reasons = {}
    columns = ['SubscriptionNumber', 'date_gregorian', 'estimated_consumption', 'reason']
    path = out / 'target_customer_daily.parquet'
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=columns):
        rows = batch.to_pydict()
        for customer_id, day, value, reason in zip(*(rows[column] for column in columns)):
            if customer_id not in seen or day is None or not start <= day < end:
                raise ArithmeticError('Individual peak customer/date mismatch')
            day_bit = 1 << (day - start).days
            if seen[customer_id] & day_bit:
                raise ArithmeticError('Duplicate individual peak customer day')
            seen[customer_id] |= day_bit
            if value is None:
                previous = missing_reasons.get(customer_id)
                if previous is None or day < previous[0]:
                    missing_reasons[customer_id] = (day, reason)
                continue
            if not math.isfinite(value) or value < 0:
                raise ArithmeticError('Invalid individual peak estimate')
            previous = best.get(customer_id)
            if previous is None or value > previous[1] or (value == previous[1] and day < previous[0]):
                best[customer_id] = (day, value)
    expected_days = (1 << n_days) - 1
    if any(days != expected_days for days in seen.values()):
        raise ArithmeticError('Individual peak target coverage mismatch')

    headers = ['SubscriptionNumber', 'peakCosumptionValue', 'peakDate']
    reasons = Counter()
    zero_count = 0
    with (out / 'customer_peak_consumption.csv').open('w', newline='', encoding='utf-8') as output_file, (out / 'peak_missing_reasons.csv').open('w', newline='', encoding='utf-8') as missing_file:
        writer = csv.writer(output_file)
        writer.writerow(headers)
        missing_writer = csv.writer(missing_file)
        missing_writer.writerow(['SubscriptionNumber', 'reason'])
        for customer_id in sorted(seen):
            if customer_id in best:
                day, value = best[customer_id]
                writer.writerow([customer_id, repr(float(value)), day.isoformat()])
                zero_count += value == 0
            else:
                reason = missing_reasons[customer_id][1]
                reasons[reason] += 1
                writer.writerow([customer_id, '', ''])
                missing_writer.writerow([customer_id, reason])

    # Verify serialized IDs, values, and dates without loading the CSV into memory.
    with (out / 'customer_peak_consumption.csv').open(newline='', encoding='utf-8') as output_file:
        reader = csv.DictReader(output_file)
        if reader.fieldnames != headers:
            raise ArithmeticError('Individual peak CSV header')
        for customer_id in sorted(seen):
            row = next(reader, None)
            if row is None or row['SubscriptionNumber'] != customer_id:
                raise ArithmeticError('Individual peak CSV identity')
            if customer_id in best:
                day, value = best[customer_id]
                if float(row['peakCosumptionValue']) != value or row['peakDate'] != day.isoformat():
                    raise ArithmeticError('Individual peak CSV value/date roundtrip')
            elif row['peakCosumptionValue'] != '' or row['peakDate'] != '':
                raise ArithmeticError('Individual peak CSV missing value')
        if next(reader, None) is not None:
            raise ArithmeticError('Individual peak CSV extra rows')
    # This report belongs only to population mode; remove a stale previous copy.
    (out / 'peak_daily_totals.csv').unlink(missing_ok=True)
    return {
        'mode': 'individual',
        'output_customers': len(seen),
        'available_values': len(best),
        'valid_zeros': int(zero_count),
        'missing_values': len(seen) - len(best),
        'missing_reasons': dict(reasons),
        'csv_integrity_passed': True,
        'policy': 'Each customer uses their maximum available target-day estimate; exact ties choose the earliest date. Partial coverage uses available days. No available estimate leaves both value and date blank.',
        'rounding': 'Shortest round-trip float64 decimal (Python repr); no fixed decimal rounding.',
    }


def write_individual_peak_summary(out, manifest):
    """Describe individual maxima without implying a shared population peak."""
    peak = manifest['peak']
    cfg = manifest['configuration']
    lines = [
        '# Individual customer daily peaks',
        f"Target: {cfg['target_start']} through {date.fromisoformat(cfg['target_end_exclusive']) - timedelta(days=1)}, inclusive; timezone: {cfg['timezone']}.",
        f"Units: {cfg['consumption_unit']} per day.",
        peak['policy'],
        'customer_peak_consumption.csv includes SubscriptionNumber, peakCosumptionValue, and peakDate (Gregorian YYYY-MM-DD). Dates can differ between customers; these maxima do not represent a simultaneous population total.',
        f"Customers: {peak['output_customers']}; available: {peak['available_values']}; valid zeros: {peak['valid_zeros']}; missing: {peak['missing_values']}.",
        f"Missing reasons: {peak['missing_reasons']}. See peak_missing_reasons.csv.",
        f"CSV identity and value/date round-trip checks passed: {peak['csv_integrity_passed']}.",
        peak['rounding'],
        'Partial-coverage peaks describe available days only. These are estimated daily values, not independently measured daily peaks.',
        f"Wall seconds: {manifest['wall_seconds']:.6f}; peak process RSS bytes: {manifest['peak_rss_bytes']:,}.",
        'Configuration and hashes (SHA256):',
        '```json',
        json.dumps({key: manifest[key] for key in ['configuration', 'inputs', 'code', 'dependencies']}, indent=2),
        '```',
    ]
    (out / 'peak_summary.md').write_text('\n\n'.join(lines) + '\n', encoding='utf-8')
