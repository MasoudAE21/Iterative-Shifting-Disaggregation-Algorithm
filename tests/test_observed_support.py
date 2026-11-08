"""Model valid bill support, without filling gaps or moving bill consumption."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from isd.config import Config
from isd.data import COLUMNS, audit_normalized, coverage_classes, date_ordinal, normalize_frame
from isd.pipeline import allocate_model, canonical, export_outputs


def fixture():
    cfg = Config(coverage_policy='observed_support_isd_v1', checkpoint=False,
                 initialization='seasonal_reference', redistribution_floor=.1,
                 individual_reference_strength=.03, n_lr_models=2, n_disagg_cycles=2)
    rows = [
        ['00000000001', '2025-01-20', '2025-02-18', 90, 40, 1, 6],
        ['00000000001', '2025-02-19', '2025-03-20', 150, 40, 1, 6],
        # Missing only the final target day: the real customer's failure mode.
        ['00000000002', '2025-01-20', '2025-03-19', 118, 40, 1, 6],
        # An internal missing day must not invalidate either supported bill.
        ['00000000003', '2025-01-20', '2025-02-18', 60, 40, 1, 6],
        ['00000000003', '2025-02-20', '2025-03-20', 87, 40, 1, 6],
    ]
    bills, audit = audit_normalized(normalize_frame(pd.DataFrame(rows, columns=COLUMNS)), cfg=cfg)
    origin = date_ordinal(cfg.target_start)
    temperature = 5 + 8 * np.sin(np.arange(60) / 8)
    daily = pd.DataFrame({'date_gregorian': pd.date_range(cfg.target_start, periods=60).date,
                          'weather_status': ['complete'] * 60,
                          'temperature_mean_F': temperature * 1.8 + 32,
                          'apparent_temperature_mean_C': temperature, 'wind_mean_mph': np.ones(60)})
    return cfg, canonical(bills), daily, origin, audit


def test_partial_and_gapped_customers_enter_solver_but_missing_days_stay_blank(tmp_path):
    cfg, bills, daily, origin, audit = fixture()
    assert (bills.record_status == 'accepted').all()
    assert audit['internal_target_gap_customers'] == 1
    assert audit['internal_target_gap_quarantined_customers'] == 0
    classes = coverage_classes(bills, origin, origin + 60)
    modeled, result, lookup, diagnostics, design, mask, exposure = allocate_model(
        bills, classes, daily, origin, cfg, tmp_path)
    assert result is not None and diagnostics['fallback_reason'] is None
    assert len(modeled) == 5 and diagnostics['partial_coverage_modeled_customers'] == 2
    assert mask.all()
    np.testing.assert_allclose(exposure[[29, 30, 31, 59]], [1., 2/3, 1., 2/3])
    export_outputs(bills, classes, daily, origin, cfg, tmp_path, 'support-test',
                   modeled, result, lookup, diagnostics)
    target = pd.read_parquet(tmp_path / 'target_customer_daily.parquet')
    for ident in ['00000000002', '00000000003']:
        part = target[target.SubscriptionNumber == ident]
        supported = part.dropna(subset=['estimated_consumption'])
        assert len(supported) == 59 and supported.method.str.endswith('_isd').all()
        assert supported.estimated_consumption.std() > 0
        assert part.estimated_consumption.isna().sum() == 1
    gap = target[(target.SubscriptionNumber == '00000000003')
                 & (target.date_gregorian == pd.Timestamp('2025-02-19').date())].iloc[0]
    assert pd.isna(gap.estimated_consumption) and gap.reason == 'internal_target_gap'
    saved = pd.read_parquet(tmp_path / 'full_bill_daily.parquet')
    for bill in bills.itertuples():
        part = saved[saved.bill_id == bill.bill_id]
        expected = pd.date_range(bill.FromDate, bill.ToDate).date.tolist()
        assert part.date_gregorian.tolist() == expected
        assert part.estimated_consumption.sum() == pytest.approx(bill.Consumption, abs=1e-10)


def test_existing_balanced_policy_and_conflict_quarantine_are_preserved(tmp_path):
    cfg, bills, daily, origin, _ = fixture()
    balanced = replace(cfg, coverage_policy='balanced_cohort_uniform_elsewhere_v1')
    classes = coverage_classes(bills, origin, origin + 60)
    modeled, *_ = allocate_model(bills, classes, daily, origin, balanced, tmp_path)
    assert set(modeled.SubscriptionNumber) == {'00000000001'}
    rows = [['00000000004', '2025-01-20', '2025-02-20', 10, 40, 1, 6],
            ['00000000004', '2025-02-01', '2025-03-20', 20, 40, 1, 6]]
    conflicting, _ = audit_normalized(normalize_frame(pd.DataFrame(rows, columns=COLUMNS)), cfg=cfg)
    assert (conflicting.record_status == 'quarantined_customer').all()


def test_observed_support_requires_exposure_scaling():
    with pytest.raises(ValueError, match='requires exposure scaling'):
        Config(coverage_policy='observed_support_isd_v1', exposure_scaled=False).validate()
