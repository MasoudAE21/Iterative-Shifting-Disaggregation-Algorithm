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


@pytest.mark.parametrize('policy', ['exclude', 'prorate', 'clip_preserve_total'])
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
    assert first.window_action == {'exclude': 'excluded', 'prorate': 'prorated', 'clip_preserve_total': 'clipped_preserved_total'}[policy]
    if policy == 'clip_preserve_total':
        total = reconciliation.loc[reconciliation.SubscriptionNumber == '00000000001', 'bill_total'].iloc[0]
        assert total == 10000
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


def test_duration_limit_before_proration():
    raw = pd.DataFrame([
        ['00000000001', '2024-12-01', '2025-03-10', '1000', '40', '1', '6'],
        ['00000000002', '2024-11-30', '2025-03-10', '1010', '40', '1', '6'],
    ], columns=COLUMNS)
    source, _ = audit_normalized(normalize_frame(raw))
    result, audit = apply_bill_window(source, Config(bill_boundary_policy='prorate', max_bill_days=100),
                                     date_ordinal('2025-03-01'), date_ordinal('2025-03-11'))
    assert result.loc[0, 'Consumption'] == 100
    assert result.loc[1, 'window_action'] == 'excluded_duration'
    assert audit['excluded_duration_bills'] == 1
    assert audit['removed_consumption'] == 1910


def test_clip_preserves_full_total():
    raw = pd.DataFrame([
        ['00000000001', '2024-12-01', '2025-03-10', '1000', '40', '1', '6'],
        ['00000000002', '2025-03-01', '2025-03-10', '50', '40', '1', '6'],
        ['00000000003', '2024-11-30', '2025-03-10', '1010', '40', '1', '6'],
    ], columns=COLUMNS)
    source, _ = audit_normalized(normalize_frame(raw))
    result, audit = apply_bill_window(source, Config(bill_boundary_policy='clip_preserve_total', max_bill_days=100),
                                     date_ordinal('2025-01-02'), date_ordinal('2025-03-01'))
    assert result.loc[0, 'Consumption'] == 1000
    assert result.loc[0, 'day_count'] == 58
    assert result.loc[0, 'retained_fraction'] == 1
    assert result.loc[0, 'raw_FromDate'] == '2024-12-01'
    assert result.loc[1, 'window_action'] == 'excluded'
    assert result.loc[2, 'window_action'] == 'excluded_duration'
    assert audit['retained_consumption'] == 1000
    assert audit['clipped_preserved_total_bills'] == 1


@pytest.mark.parametrize('bill_start,bill_end,total,expected', [
    ('2024-11-01', '2025-02-28', 1000, 1000 * 58 / (30*.55+31*.8+31+28)),
    ('2025-02-01', '2025-03-31', 1000, 1000 * 28 / (28+31*.57)),
    ('2025-01-02', '2025-02-28', 1000, 1000),
    ('2025-01-01', '2025-01-02', 100, 50),
    ('2024-10-01', '2025-01-02', 1000, 1000 / (31*.2+30*.55+31*.8+2)),
])
def test_monthly_weighted(bill_start, bill_end, total, expected):
    raw = pd.DataFrame([['00000000001', bill_start, bill_end, str(total), '40', '1', '6']], columns=COLUMNS)
    source, _ = audit_normalized(normalize_frame(raw))
    result, _ = apply_bill_window(source, Config(bill_boundary_policy='monthly_weighted', bill_window='target'),
                                 date_ordinal('2025-01-02'), date_ordinal('2025-03-01'))
    assert result.loc[0, 'Consumption'] == pytest.approx(expected)
    assert result.loc[0, 'original_consumption'] == total
    assert result.loc[0, 'retained_fraction'] == pytest.approx(expected / total)

def test_other_month_weight():
    from isd.bill_window import bill_weight_sum
    assert bill_weight_sum(date_ordinal('2024-04-01'), date_ordinal('2024-05-01')) == pytest.approx(3)


def test_boundary_only_duration_and_weighted_summer_conservation():
    raw = pd.DataFrame([
        ['00000000001','2024-01-01','2024-12-31','366','40','1','6'],
        ['00000000002','2023-12-01','2024-05-31','183','40','1','6'],
        ['00000000003','2024-12-01','2025-04-29','150','40','1','6'],
        ['00000000004','2024-12-01','2025-04-30','151','40','1','6'],
        ['00000000005','2025-01-01','2025-01-02','2','40','1','6'],
    ], columns=COLUMNS)
    source = normalize_frame(raw)
    cfg = Config(bill_boundary_policy='monthly_weighted', bill_window='target',
                 max_bill_days=150, bill_duration_scope='boundary')
    result, ledger = apply_bill_window(source, cfg, date_ordinal('2024-01-01'), date_ordinal('2025-01-01'))
    assert result.window_action.tolist() == ['unchanged','excluded_duration','monthly_weighted','excluded_duration','excluded']
    assert result.loc[0,'Consumption'] == 366
    assert result.loc[2,'Consumption'] == pytest.approx(150*(31*.8)/(31*.8+31+28+31*.57+29*.1))
    assert ledger['excluded_duration_bills'] == 2
    # Complementary summer windows must sum to the original observed bill.
    summer = normalize_frame(pd.DataFrame([['00000000001','2024-03-01','2024-04-30','610','40','1','6']], columns=COLUMNS))
    march, _ = apply_bill_window(summer, cfg, date_ordinal('2024-03-01'),date_ordinal('2024-04-01'))
    april, _ = apply_bill_window(summer, cfg, date_ordinal('2024-04-01'),date_ordinal('2024-05-01'))
    assert march.Consumption.iloc[0] + april.Consumption.iloc[0] == pytest.approx(610)
    assert april.Consumption.iloc[0] == pytest.approx(610*3/(31*.57+3))


def test_reordered_us_bill_export_preserves_raw_provenance(tmp_path):
    from isd.data import read_bills
    path = tmp_path / 'bills.csv'
    path.write_text('SubscriptionNumber,FromDate,ToDate,Consumption,Capacity,ConsumptionType,UnitCount\n'
                    '00000000001,12/1/2023,1/15/2024,460,6,40,1\n')
    result, audit = read_bills(path, Config(bill_date_format='%m/%d/%Y'))
    assert audit['record_status_counts'] == {'accepted': 1}
    assert result.FromDate.iloc[0] == '2023-12-01'
    assert result.raw_FromDate.iloc[0] == '12/1/2023'
    assert result.day_count.iloc[0] == 46
    assert result.Capacity.iloc[0] == 6
    assert result.UnitCount.iloc[0] == 1
