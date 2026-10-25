"""Independent readback checks for full bill conservation and final peak CSV."""
from pathlib import Path
import csv, itertools, json, math, shutil, time
import numpy as np
import pyarrow.parquet as pq
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isd.data import sha256
from isd.pipeline import source_fingerprint
ROOT = Path(__file__).resolve().parents[1]
out = ROOT / 'outputs'

def records(path, columns):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=columns):
        data = batch.to_pydict()
        yield from zip(*(data[c] for c in columns))

def main():
    start = time.perf_counter()
    manifest = json.loads((out / 'run_manifest.json').read_text())
    cfg = manifest['configuration']
    bills = records(out / 'bill_reconciliation.parquet', ['bill_id', 'bill_total', 'target_daily_sum', 'outside_target_sum'])
    count = 0
    max_error = 0.0
    zero_bills = 0
    daily = records(out / 'full_bill_daily.parquet', ['bill_id', 'estimated_consumption'])
    for ident, group in itertools.groupby(daily, key=lambda row: row[0]):
        bill, total, target, outside = next(bills)
        assert bill == ident
        values = [v for _, v in group]
        assert all((math.isfinite(v) and v >= 0 for v in values))
        error = abs(math.fsum(values) - total)
        max_error = max(max_error, error)
        assert error <= cfg['reconciliation_atol'] + cfg['reconciliation_rtol'] * abs(total)
        assert math.isclose(math.fsum(values), target + outside, rel_tol=1e-10, abs_tol=1e-08)
        if total == 0:
            assert all((v == 0 for v in values))
            zero_bills += 1
        count += 1
    assert next(bills, None) is None and count == manifest['export']['bill_reconciliation_passed']
    normalized = pq.read_table(out / 'normalized_bills.parquet', columns=['SubscriptionNumber']).column(0).to_pylist()
    source_ids = {ident for ident in normalized if ident is not None}
    del normalized
    peak_mode = cfg.get('peak_mode', 'population')
    if peak_mode == 'individual':
        peak_report = verify_individual(out, source_ids, cfg, manifest['peak'])
        ids = source_ids
        missing = peak_report['missing_values']
        zeros = peak_report['retained_zero_values']
    elif peak_mode == 'population':
        values_by_day = {}
        population = set()
        for ident, day, value, coverage in records(out / 'target_customer_daily.parquet', ['SubscriptionNumber', 'date_gregorian', 'estimated_consumption', 'coverage_class']):
            if coverage == 'full':
                population.add(ident)
                values_by_day.setdefault(day, []).append(value)
        totals = {day: math.fsum(values) for day, values in values_by_day.items()}
        assert all((len(values) == len(population) for values in values_by_day.values()))
        del values_by_day
        peak = min(totals, key=lambda d: (-totals[d], d))
        assert str(peak) == manifest['peak']['date']
        same_day = pq.read_table(out / 'target_customer_daily.parquet', filters=[('date_gregorian', '=', peak)], columns=['SubscriptionNumber', 'estimated_consumption']).to_pydict()
        expected = dict(zip(same_day['SubscriptionNumber'], same_day['estimated_consumption']))
        ids = set()
        missing = zeros = 0
        cohort = []
        with (out / 'customer_peak_consumption.csv').open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == ['SubscriptionNumber', 'peakCosumptionValue']
            for row in reader:
                ident = row['SubscriptionNumber']
                assert ident not in ids
                ids.add(ident)
                text = row['peakCosumptionValue']
                value = None if text == '' else float(text)
                assert value == expected[ident]
                if value is None:
                    missing += 1
                else:
                    assert math.isfinite(value) and value >= 0
                    zeros += value == 0
                    if ident in population:
                        cohort.append(value)
        assert ids == source_ids
        assert math.isclose(math.fsum(cohort), totals[peak], rel_tol=1e-14, abs_tol=1e-08)
        peak_report = {'same_day_values_exactly_match': True, 'independent_math_fsum_peak_date': str(peak), 'independent_math_fsum_peak_total': totals[peak], 'fixed_population_customers': len(population)}
    else:
        raise ValueError('Unknown peak mode')
    assert source_fingerprint(ROOT) == manifest['code']
    artifact_names = ['customer_peak_consumption.csv', 'peak_missing_reasons.csv', 'run_manifest.json']
    if peak_mode == 'population':
        artifact_names.append('peak_daily_totals.csv')
    report = {
        'passed': True,
        'peak_mode': peak_mode,
        'full_bill_rows_reconciled_from_daily_parquet': count,
        'maximum_bill_error': max_error,
        'zero_bills_checked': zero_bills,
        'distinct_input_and_csv_customers': len(ids),
        'missing_values': missing,
        'retained_zero_values': zeros,
        **peak_report,
        'source_hashes_match_final_run': True,
        'artifact_sha256': {name: sha256(out / name) for name in artifact_names},
        'output_sizes_bytes': {p.name: p.stat().st_size for p in out.iterdir() if p.is_file()},
        'available_disk_bytes': shutil.disk_usage(ROOT).free,
        'verification_seconds': time.perf_counter() - start,
    }
    (ROOT / 'handoff/peak_final_verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def verify_individual(output_dir, customer_ids, cfg, peak_metadata):
    """Independently recompute maxima and verify exported customer values/dates."""
    from collections import Counter
    from datetime import date

    start = date.fromisoformat(cfg['target_start'])
    end = date.fromisoformat(cfg['target_end_exclusive'])
    n_days = (end - start).days
    if n_days <= 0:
        raise ValueError('Empty target window')
    seen_days = {ident: 0 for ident in customer_ids}
    maxima = {}
    earliest_missing = {}
    columns = ['SubscriptionNumber', 'date_gregorian', 'estimated_consumption', 'reason']
    for ident, day, value, reason in records(output_dir / 'target_customer_daily.parquet', columns):
        assert ident in customer_ids and day is not None and start <= day < end, 'Customer/date mismatch'
        bit = 1 << (day - start).days
        assert not seen_days[ident] & bit, 'Duplicate customer day'
        seen_days[ident] |= bit
        if value is None:
            if ident not in earliest_missing or day < earliest_missing[ident][0]:
                earliest_missing[ident] = (day, reason)
            continue
        assert math.isfinite(value) and value >= 0, 'Invalid daily estimate'
        # Sorting this pair selects highest value, then earliest date.
        candidate = (-value, day)
        if ident not in maxima or candidate < maxima[ident]:
            maxima[ident] = candidate
    assert all(bits == (1 << n_days) - 1 for bits in seen_days.values()), 'Incomplete target rows'

    exported_ids = set()
    missing = zeros = 0
    with (output_dir / 'customer_peak_consumption.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ['SubscriptionNumber', 'peakCosumptionValue', 'peakDate'], 'CSV header'
        for row in reader:
            ident = row['SubscriptionNumber']
            assert ident in customer_ids and ident not in exported_ids, 'CSV customer mismatch'
            exported_ids.add(ident)
            if ident in maxima:
                negative_value, day = maxima[ident]
                assert row['peakCosumptionValue'] != '', 'Missing peak value'
                assert float(row['peakCosumptionValue']) == -negative_value, 'Incorrect peak value'
                assert row['peakDate'] == day.isoformat(), 'Incorrect peak date'
                zeros += negative_value == 0
            else:
                assert row['peakCosumptionValue'] == row['peakDate'] == '', 'Missing peak must have blank date/value'
                missing += 1
    assert exported_ids == customer_ids, 'Missing CSV customers'
    expected_reasons = {ident: earliest_missing[ident][1] for ident in customer_ids - maxima.keys()}
    with (output_dir / 'peak_missing_reasons.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ['SubscriptionNumber', 'reason']
        actual_reasons = {}
        for row in reader:
            assert row['SubscriptionNumber'] not in actual_reasons, 'Duplicate missing reason'
            actual_reasons[row['SubscriptionNumber']] = row['reason']
    assert actual_reasons == expected_reasons, 'Missing reasons mismatch'
    assert peak_metadata['mode'] == 'individual'
    assert peak_metadata['output_customers'] == len(customer_ids)
    assert peak_metadata['available_values'] == len(maxima)
    assert peak_metadata['missing_values'] == missing
    assert peak_metadata['valid_zeros'] == zeros
    assert peak_metadata['missing_reasons'] == dict(Counter(expected_reasons.values()))
    return {
        'individual_values_and_dates_exactly_match': True,
        'missing_values': missing,
        'retained_zero_values': zeros,
    }


if __name__ == '__main__':
    main()
