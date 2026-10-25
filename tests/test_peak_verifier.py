import csv
import json
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from isd.config import Config
from isd.peak import export_peak
from scripts import verify_peak_outputs as verifier


def fixture_output(tmp_path, mode):
    out = tmp_path / 'outputs'
    out.mkdir()
    (tmp_path / 'handoff').mkdir()
    classes = {'001': ('full', 2), '002': ('full', 2), '003': ('none', 0)}
    target = []
    full = []
    reconciliation = []
    for ident, values in zip(classes, [[9., 1.], [0., 10.], [None, None]]):
        for day, value in zip([date(2025, 1, 20), date(2025, 1, 21)], values):
            target.append({'SubscriptionNumber': ident, 'date_gregorian': day,
                           'estimated_consumption': value, 'coverage_class': classes[ident][0],
                           'reason': 'internal_target_gap' if value is None else 'none'})
            if value is not None:
                full.append({'bill_id': ident, 'estimated_consumption': value})
        if values[0] is not None:
            reconciliation.append({'bill_id': ident, 'bill_total': sum(values),
                                   'target_daily_sum': sum(values), 'outside_target_sum': 0.})
    for filename, rows in [('target_customer_daily', target), ('full_bill_daily', full),
                           ('bill_reconciliation', reconciliation),
                           ('normalized_bills', [{'SubscriptionNumber': ident} for ident in classes])]:
        pq.write_table(pa.Table.from_pylist(rows), out / (filename + '.parquet'))
    cfg = Config(peak_mode=mode, target_end_exclusive='2025-01-22')
    peak = export_peak(out, classes, cfg)
    manifest = {'configuration': cfg.as_dict(), 'peak': peak, 'code': {},
                'source_audit': {'rows': 100, 'customers': 50},
                'export': {'bill_reconciliation_passed': 2}}
    (out / 'run_manifest.json').write_text(json.dumps(manifest))
    return out, classes, manifest


@pytest.mark.parametrize('mode', ['population', 'individual'])
def test_verifier_main_both_modes(tmp_path, monkeypatch, mode):
    out, _, _ = fixture_output(tmp_path, mode)
    monkeypatch.setattr(verifier, 'ROOT', tmp_path)
    monkeypatch.setattr(verifier, 'out', out)
    monkeypatch.setattr(verifier, 'source_fingerprint', lambda root: {})
    verifier.main()
    report = json.loads((tmp_path / 'handoff/peak_final_verification.json').read_text())
    assert report['passed'] and report['peak_mode'] == mode
    assert report['distinct_input_and_csv_customers'] == 3
    assert ('peak_daily_totals.csv' in report['artifact_sha256']) == (mode == 'population')


@pytest.mark.parametrize('column,bad_value', [('peakDate', '2025-01-21'),
                                            ('peakCosumptionValue', '8.0')])
def test_individual_verifier_rejects_corrupt_csv(tmp_path, column, bad_value):
    out, classes, manifest = fixture_output(tmp_path, 'individual')
    path = out / 'customer_peak_consumption.csv'
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        rows = list(reader)
    rows[0][column] = bad_value
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(AssertionError, match='Incorrect peak'):
        verifier.verify_individual(out, set(classes), manifest['configuration'], manifest['peak'])
