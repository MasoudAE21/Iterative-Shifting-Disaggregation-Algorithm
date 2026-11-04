import json
from datetime import date

import pandas as pd
import pytest

from isd.customer_reports import export_daily_csv, export_peak_reports


def test_reports_ties_partial_missing_and_optional_daily(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    rows = []
    for ident, values, coverage in [('001', [2., 5., 5.], 'full'),
                                     ('002', [100., None, 3.], 'partial'),
                                     ('003', [None, None, None], 'excluded')]:
        for offset, value in enumerate(values):
            rows.append(dict(SubscriptionNumber=ident, date_gregorian=date(2025, 1, offset + 1),
                             estimated_consumption=value, coverage_class=coverage,
                             method='fixture', estimate_status='available' if value is not None else 'missing',
                             reason=None if value is not None else 'uncovered'))
    source = run / 'target_customer_daily.parquet'
    pd.DataFrame(rows).to_parquet(source, index=False)
    (run / 'run_manifest.json').write_text(json.dumps({'configuration': {
        'target_start': '2025-01-01', 'target_end_exclusive': '2025-01-04', 'consumption_unit': 'm3'}}))
    output = tmp_path / 'reports'
    report = export_peak_reports(run, output, {'all': ['2025-01-01', '2025-01-04'],
                                             'short': ['2025-01-03', '2025-01-04']})
    assert report['windows']['all']['peak_date'] == '2025-01-02'
    assert report['windows']['short']['peak_date'] == '2025-01-03'
    peaks = pd.read_csv(output / 'all/individual_customer_peaks.csv', dtype={'SubscriptionNumber': str})
    assert peaks.SubscriptionNumber.tolist() == ['001', '002', '003']
    assert peaks.peak_date.iloc[0] == '2025-01-02'
    assert peaks.peak_consumption.iloc[1] == 100
    assert peaks.available_days.tolist() == [3, 2, 0]
    assert pd.isna(peaks.peak_consumption.iloc[2])
    daily = output / 'daily'
    assert export_daily_csv(source, daily, enabled=False) is None
    assert not daily.exists()
    assert export_daily_csv(source, daily)['rows'] == 9
    assert len(pd.read_csv(daily / '2025-01.csv')) == 9
    export_daily_csv(source, daily, enabled=False)
    assert not (daily / '2025-01.csv').exists()
    with pytest.raises(ValueError, match='outside'):
        export_peak_reports(run, output, {'bad': ['2024-12-01', '2025-01-04']})
