import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from isd.city_reports import customer_blocks, export_city_reports, report_windows
from isd.data import sha256, jalali_date, date_ordinal


def saved_run(tmp_path, no_complete=False):
    run = tmp_path/'run'; run.mkdir()
    cfg = {'target_start': '2025-02-10', 'target_end_exclusive': '2025-02-13', 'consumption_unit': 'm3'}
    (run/'run_manifest.json').write_text(json.dumps({'configuration': cfg}))
    inputs = [('001', [0., 5., 5.]), ('002', [100., None, 3.]), ('003', [None]*3), ('004', [0.]*3)]
    if no_complete:
        inputs = [('001', [0., None, 5.]), ('002', [None, 100., None])]
    rows = []; bills = []
    for ident, values in inputs:
        bills.append(dict(SubscriptionNumber=ident, ConsumptionType='40', record_status='accepted',
                          exclusion_reason=None, floor_source='insufficient_summer_fallback',
                          floor_feasibility_adjusted=False, bill_id=ident, Consumption=sum(x or 0 for x in values), day_count=3))
        for offset, value in enumerate(values):
            day = date(2025, 2, 10+offset)
            rows.append(dict(SubscriptionNumber=ident, date_gregorian=day,
                             date_jalali=jalali_date(date_ordinal(str(day))), estimated_consumption=value,
                             coverage_class='full' if all(x is not None for x in values) else 'partial',
                             bill_id=ident if value is not None else None, method='fixture',
                             estimate_status='unavailable' if value is None else 'estimated', reason='gap' if value is None else 'none'))
    pd.DataFrame(rows).to_parquet(run/'target_customer_daily.parquet', row_group_size=2, index=False)
    pd.DataFrame(bills).to_parquet(run/'normalized_bills.parquet', index=False)
    return run, cfg


def settings():
    return dict(include_all_saved=True, requested_dates=['2025-02-10', '2025-02-12'],
                windows={'short': ['2025-02-11', '2025-02-13']}, profile_customers=['001'],
                profile_sample_count=2, profile_seed=7)


def test_city_reports_peaks_dates_missing_zero_and_source_unchanged(tmp_path):
    run, cfg = saved_run(tmp_path)
    before = {p.name: sha256(p) for p in run.iterdir()}
    output = tmp_path/'reports'
    result = export_city_reports(run, output, settings())
    assert result['windows']['all_saved']['modeled_peak_date'] == '2025-02-11'
    assert result['windows']['all_saved']['cohort_customers'] == 2
    assert result['windows']['all_saved']['modeled_peak_m3'] == 5
    peaks = pd.read_csv(output/'all_saved/individual_customer_peaks.csv', dtype={'SubscriptionNumber': str})
    assert peaks.SubscriptionNumber.tolist() == ['001', '002', '003', '004']
    assert peaks.peak_date_gregorian.iloc[0] == '2025-02-11'  # first tied day
    assert peaks.peak_consumption_m3.iloc[1] == 100
    assert peaks.available_days.tolist() == [3, 2, 0, 3]
    assert np.isnan(peaks.peak_consumption_m3.iloc[2])
    assert peaks.peak_consumption_m3.iloc[3] == 0
    chosen = pd.read_csv(output/'customers_on_2025-02-10.csv', dtype={'SubscriptionNumber': str})
    assert chosen.estimated_consumption.fillna(-1).tolist() == [0, 100, -1, 0]
    cohort = pd.read_csv(output/'all_saved/customers_on_modeled_peak.csv')
    assert cohort.in_peak_selection_population.tolist() == [True, False, False, True]
    assert cohort.loc[cohort.in_peak_selection_population, 'estimated_consumption'].sum() == 5
    assert result['metrics']['status'] == 'unavailable'
    assert (output/'customer_profiles_01.png').exists()
    assert (output/'completion.json').exists()
    assert before == {p.name: sha256(p) for p in run.iterdir()}
    blocks = list(customer_blocks(run/'target_customer_daily.parquet', cfg, batch_size=2))
    assert sum(len(ids) for _, ids, _ in blocks) == 4
    with pytest.raises(ValueError, match='empty report'):
        export_city_reports(run, output, settings())


def test_no_cohort_still_exports_individual_and_requested_dates(tmp_path):
    run, _ = saved_run(tmp_path, no_complete=True)
    s = settings(); s['profile_sample_count'] = 0
    result = export_city_reports(run, tmp_path/'reports', s)
    assert result['windows']['all_saved']['modeled_peak_date'] is None
    assert result['windows']['all_saved']['status'] == 'no_complete_coverage_customers'
    assert (tmp_path/'reports/all_saved/individual_customer_peaks.csv').exists()
    assert (tmp_path/'reports/customers_on_2025-02-12.csv').exists()
    assert not (tmp_path/'reports/all_saved/customers_on_modeled_peak.csv').exists()


def test_reports_validate_grid_and_dates(tmp_path):
    run, cfg = saved_run(tmp_path)
    s = settings(); s['requested_dates'] = ['2025-02-25']
    with pytest.raises(ValueError, match='outside'):
        export_city_reports(run, tmp_path/'reports', s)
    assert not (tmp_path/'reports').exists()
    data = pd.read_parquet(run/'target_customer_daily.parquet')
    data.loc[1, 'date_gregorian'] = data.loc[0, 'date_gregorian']
    data.to_parquet(run/'target_customer_daily.parquet', index=False)
    with pytest.raises(ValueError, match='customer dates'):
        list(customer_blocks(run/'target_customer_daily.parquet', cfg))
    with pytest.raises(ValueError, match='Unknown report'):
        report_windows({'windwos': {}}, cfg)


def test_optional_city_metrics_pairing_and_coverage_filter(tmp_path):
    run, _ = saved_run(tmp_path)
    truth = tmp_path/'measured.csv'
    pd.DataFrame({'date_gregorian': ['2025-02-10', '2025-02-11', '2025-02-12'],
                  'consumption_m3': [100, 5, 8]}).to_csv(truth, index=False)
    s = settings(); s.update(measured_city_daily_csv=str(truth), metric_min_coverage_fraction=.75,
                              truth_scales=[1.0], excluded_metric_dates=['2025-02-12'])
    result = export_city_reports(run, tmp_path/'reports', s)
    scores = {x['window']: x for x in result['metrics']['rows']}
    assert scores['all_saved']['matched_days'] == 1
    assert scores['all_saved']['mape_percent'] == 0
    pairs = pd.read_csv(tmp_path/'reports/metric_daily_pairs.csv')
    assert pairs.metric_include_all_saved.tolist() == [True, False, False]


def test_city_configuration_preserves_g013_scientific_settings():
    from scripts.city_workflow import ROOT, load_settings
    settings, cfg = load_settings(ROOT/'configs/city_final.json')
    assert (cfg.alpha, cfg.n_lr_models, cfg.n_disagg_cycles) == (1e-5, 5, 3)
    assert cfg.individual_reference_strength == .1
    assert cfg.summer_min_covered_days == 10
    assert cfg.tbs_path is None and cfg.max_customers is None
    assert cfg.consumption_types == ['40']
    assert cfg.target_start == cfg.simulation_start == '2024-06-01'
    assert cfg.target_end_exclusive == cfg.simulation_end_exclusive == '2025-03-16'
    assert settings['reports']['requested_dates'] == ['2025-02-10', '2025-02-25']


def test_type_filter_preserves_physical_row_identity_and_header_mapping(tmp_path):
    from isd.config import Config
    from isd.data import read_bills
    from dataclasses import replace
    path = tmp_path/'bills.csv'
    path.write_text('SubscriptionNumber,FromDate,ToDate,Consumption,Capacity,ConsumptionType,UnitCount\n'
                    '15000000001,2025-02-01,2025-02-28,280,1000,91,1\n'
                    '15000000002,2025-02-01,2025-02-28,56,6,40,2\n'
                    '15000000003,2025-02-01,2025-02-28,84,10,40,3\n')
    cfg = Config(consumption_types=['40'], ingestion_chunk_size=2)
    selected, audit = read_bills(path, cfg)
    assert selected.SubscriptionNumber.tolist() == ['15000000002', '15000000003']
    assert selected.source_row.tolist() == [3, 4]
    assert selected.Capacity.tolist() == [6, 10]
    assert selected.UnitCount.tolist() == [2, 3]
    assert audit['excluded_consumption_type_rows'] == 1
    full, _ = read_bills(path, replace(cfg, consumption_types=None))
    assert selected.bill_id.tolist() == full.bill_id.tolist()[1:]
    with pytest.raises(ValueError, match='No bills match'):
        read_bills(path, replace(cfg, consumption_types=['99']))
