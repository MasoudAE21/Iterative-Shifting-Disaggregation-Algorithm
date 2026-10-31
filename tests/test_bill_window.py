from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from isd.bill_window import apply_bill_window, resolve_window
from isd.config import Config
from isd.data import COLUMNS, normalize_frame, audit_normalized, date_ordinal
from isd.pipeline import run


@pytest.mark.parametrize('policy', ['exclude', 'prorate'])
def test_boundaries_and_proration(policy):
    raw = pd.DataFrame([
        ['00000000001', '2024-12-01', '2025-03-10', '1000', '40', '1', '6'],
        ['00000000002', '2025-03-01', '2025-03-10', '50', '40', '1', '6'],
        ['00000000003', '2025-03-11', '2025-03-20', '50', '40', '1', '6'],
        ['00000000004', '2025-02-20', '2025-03-20', '0', '40', '1', '6'],
    ], columns=COLUMNS)
    source, _ = audit_normalized(normalize_frame(raw))
    result, audit = apply_bill_window(source, Config(bill_boundary_policy=policy),
                                     date_ordinal('2025-03-01'), date_ordinal('2025-03-11'))
    assert result.loc[1, 'window_action'] == 'unchanged'
    assert result.loc[2, 'record_status'] == 'excluded_window'
    assert source.loc[0, 'Consumption'] == 1000
    assert result.bill_id.equals(source.bill_id)
    if policy == 'prorate':
        assert result.loc[0, 'Consumption'] == 100  # 10 of 100 inclusive bill days
        assert result.loc[0, 'day_count'] == 10
        assert result.loc[0, 'FromDate'] == '2025-03-01'
        assert result.loc[0, 'raw_FromDate'] == '2024-12-01'
        assert result.loc[3, 'Consumption'] == 0
        assert audit['prorated_bills'] == 2
    else:
        assert audit['excluded_bills'] == 3
    assert audit['retained_consumption'] + audit['removed_consumption'] == 1100


def test_weather_window_uses_complete_local_days_and_rejects_gaps():
    seconds = datetime(2025, 1, 19, tzinfo=timezone.utc).timestamp() + np.arange(100) * 3600
    values = np.tile([5., 3., 10.], (len(seconds), 1))
    cfg = Config(bill_window='target')
    start, end = resolve_window(seconds, values, cfg)
    assert start == date_ordinal('2025-01-20')
    assert end == date_ordinal('2025-01-23')
    with pytest.raises(ValueError, match='internal gaps'):
        resolve_window(np.delete(seconds, 50), np.delete(values, 50, axis=0), cfg)


@pytest.mark.parametrize('policy', ['exclude', 'prorate'])
def test_pipeline_does_not_expand_to_long_bill(tmp_path, policy):
    data = tmp_path / 'data' / 'prepared'
    data.mkdir(parents=True)
    pd.DataFrame([
        ['00000000001', '2021-01-01', '2025-04-01', '10000', '40', '1', '6'],
        ['00000000002', '2025-01-20', '2025-03-20', '120', '40', '1', '6'],
    ], columns=COLUMNS).to_csv(data / 'bill_Customers_Town_Q.csv', index=False)
    with (data / 'open-meteo-fixture.csv').open('w', encoding='utf-8') as f:
        f.write('latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n34,50,1435,0,GMT,GMT\n\ntime,temperature_2m (°C),apparent_temperature (°C),wind_speed_10m (km/h)\n')
        for i in range(1600):
            dt = datetime(2025, 1, 19) + timedelta(hours=i)
            f.write(f'{dt:%Y-%m-%dT%H:%M},{5+np.sin(i/40)},{3+np.sin(i/40)},10\n')
    cfg = Config(bill_boundary_policy=policy, bill_window='target', max_customers=None,
                 n_lr_models=1, n_disagg_cycles=1, checkpoint=False)
    out = tmp_path / 'out'
    manifest = run(tmp_path, cfg, out)
    assert manifest['date_domain_half_open'] == ['2025-01-20', '2025-03-21']
    assert manifest['model_diagnostics']['fallback_reason'] is None
    reconciliation = pd.read_parquet(out / 'bill_reconciliation.parquet')
    assert reconciliation.passed.all()
    normalized = pd.read_parquet(out / 'normalized_bills.parquet')
    first = normalized[normalized.SubscriptionNumber == '00000000001'].iloc[0]
    assert first.raw_Consumption == '10000'
    assert first.window_action == ('excluded' if policy == 'exclude' else 'prorated')
    if policy == 'prorate':
        total = reconciliation.loc[reconciliation.SubscriptionNumber == '00000000001', 'bill_total'].iloc[0]
        assert total == pytest.approx(10000 * 60 / first.original_day_count)
    # No accepted bills keeps the bounded domain; population peak is undefined.
    if policy == 'exclude':
        raw = pd.read_csv(data / 'bill_Customers_Town_Q.csv', dtype=str).iloc[:1]
        raw.to_csv(data / 'bill_Customers_Town_Q.csv', index=False)
        with pytest.raises(ValueError, match='No complete-coverage customers'):
            run(tmp_path, cfg, tmp_path / 'empty')
        assert len(pd.read_parquet(tmp_path / 'empty/daily_weather.parquet')) == 60


def test_invalid_configuration():
    with pytest.raises(ValueError, match='boundary policy'):
        replace(Config(), bill_boundary_policy='invalid').validate()
    with pytest.raises(ValueError, match='bill window'):
        replace(Config(), bill_window='invalid').validate()
