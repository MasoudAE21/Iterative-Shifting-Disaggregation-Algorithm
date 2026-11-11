import json
from copy import deepcopy
from itertools import product

import numpy as np
import pandas as pd
import pytest

from scripts.run_hyperparameter_experiments import metric_reports, metric_scores, select_customers, validate_allocations, update_tbs_summary, add_uniform_allocations
from scripts.run_hyperparameter_experiments import expand_model_grid, main


def test_summer_grid_uses_new_implementation_and_preserves_report_settings():
    from scripts.run_hyperparameter_experiments import ROOT
    settings = json.loads((ROOT / 'configs/summer_floor_grid.json').read_text(encoding='utf-8-sig'))
    runs = expand_model_grid(settings)
    assert len(runs) == 6
    for model in runs:
        assert model['source'] == 'working_tree'
        p = model['parameters']
        assert p['customer_summer_floor'] is True
        assert p['summer_floor_fraction'] == .95
        assert p['summer_min_covered_days'] == 30
        assert p['summer_fallback_fraction'] == .1
        assert p['divide_consumption_by_unit_count'] is False
        assert p['max_customers'] is None
    assert len(settings['customers']) == 12
    assert settings['random_customer_count'] == 5


def test_working_snapshot_freezes_uncommitted_and_new_source(tmp_path, monkeypatch):
    import hashlib
    import scripts.run_hyperparameter_experiments as runner
    root = tmp_path / 'repo'
    (root / 'isd').mkdir(parents=True)
    (root / 'isd/config.py').write_text('changed settings')
    (root / 'isd/customer_floor.py').write_text('new floor implementation')
    monkeypatch.setattr(runner, 'ROOT', root)
    def git(args, **kwargs):
        if args[1] == 'branch':
            return 'codex/test\n'
        if args[1] == 'rev-parse':
            return 'basecommit\n'
        return b'isd/config.py\0isd/customer_floor.py\0isd/deleted.py\0'
    monkeypatch.setattr(runner.subprocess, 'check_output', git)
    destination = tmp_path / 'snapshot'
    assert runner.snapshot_working_tree('codex/test', destination) == 'basecommit'
    manifest = json.loads((destination / 'working_tree_snapshot.json').read_text())
    assert manifest['files']['isd/customer_floor.py'] == hashlib.sha256(b'new floor implementation').hexdigest()
    (root / 'isd/customer_floor.py').write_text('later edit')
    assert (destination / 'isd/customer_floor.py').read_text() == 'new floor implementation'
    assert not (destination / 'isd/deleted.py').exists()
    with pytest.raises(ValueError, match='current branch'):
        runner.snapshot_working_tree('other', destination)


def test_scores_use_tbs_as_reference_and_report_missing_and_zero_days():
    frame = pd.DataFrame({'tbs_daily_m3': [1., 2., 0., np.nan, 4.],
                          'final_algorithm_consumption_m3': [2., 2., 1., 10., np.nan]})
    scores = metric_scores(frame)
    assert scores['matched_days'] == 3
    assert scores['missing_pair_days'] == 2
    assert scores['mape_days'] == 2 and scores['zero_tbs_days'] == 1
    assert scores['mape_percent'] == pytest.approx(50.)
    assert scores['rmse_m3'] == pytest.approx(np.sqrt(2 / 3))
    assert scores['r2'] == pytest.approx(0.)


def test_windows_include_endpoints_and_ignore_april_29_and_30():
    dates = ['2024-11-14', '2024-11-15', '2025-03-15', '2025-03-16',
             '2025-04-28', '2025-04-29', '2025-04-30']
    frame = pd.DataFrame({'date_gregorian': dates, 'tbs_daily_m3': np.arange(1., 8.),
                          'final_algorithm_consumption_m3': [1., 2., 3., 4., 5., 999., 999.]})
    rows, masks = metric_reports(frame, {'winter': ['2024-11-15', '2025-03-15'], 'all': None},
                                 ['2025-04-29', '2025-04-30'])
    assert len(rows) == 4
    rows = [row for row in rows if row['truth_scale'] == 1.0]
    assert rows[0]['matched_days'] == 2 and rows[0]['rmse_m3'] == 0
    assert rows[1]['matched_days'] == 5 and rows[1]['excluded_days'] == 2
    assert rows[1]['r2'] == 1 and rows[1]['mape_percent'] == 0
    assert masks['winter'].tolist() == [False, True, True, False, False, False, False]


def test_undefined_metrics_do_not_invent_scores():
    scores = metric_scores(pd.DataFrame({'tbs_daily_m3': [0., 0.],
                                         'final_algorithm_consumption_m3': [0., 1.]}))
    assert scores['mape_percent'] is None and scores['r2'] is None
    assert scores['pearson_r'] is None


def test_random_customers_are_additional_unique_and_reproducible():
    chosen = select_customers(map(str, range(20)), ['1', '3'], 5, 123)
    assert chosen == select_customers(map(str, range(20)), ['1', '3'], 5, 123)
    assert chosen[:2] == ['1', '3'] and len(set(chosen)) == 7
    with pytest.raises(ValueError, match='absent'):
        select_customers(['1'], ['2'], 0, 123)


def test_saved_allocation_validation_rejects_lost_bill_volume(tmp_path):
    manifest = {'configuration': {'reconciliation_atol': 1e-8, 'reconciliation_rtol': 1e-10,
                                  'redistribution_floor': .1},
                'wall_seconds': 1., 'model_diagnostics': {'fallback_reason': None}}
    (tmp_path / 'run_manifest.json').write_text(json.dumps(manifest))
    pd.DataFrame({'bill_id': ['a'], 'record_status': ['accepted'], 'SubscriptionNumber': ['1'],
                  'start_ordinal': [0], 'end_ordinal': [2], 'day_count': [2],
                  'Consumption': [10.]}).to_parquet(tmp_path / 'normalized_bills.parquet')
    pd.DataFrame({'bill_id': ['a', 'a'], 'SubscriptionNumber': ['1', '1'],
                  'date_gregorian': pd.to_datetime(['1970-01-01', '1970-01-02']),
                  'estimated_consumption': [4., 6.]}).to_parquet(
        tmp_path / 'full_bill_daily.parquet')
    pd.DataFrame({'estimated_consumption': [4., 6., np.nan]}).to_parquet(
        tmp_path / 'target_customer_daily.parquet')
    result = validate_allocations(tmp_path)
    assert result['max_bill_error'] == 0 and result['null_customer_days'] == 1
    pd.DataFrame({'bill_id': ['a', 'a'], 'SubscriptionNumber': ['1', '1'],
                  'date_gregorian': pd.to_datetime(['1970-01-01', '1970-01-02']),
                  'estimated_consumption': [4., 5.]}).to_parquet(
        tmp_path / 'full_bill_daily.parquet')
    with pytest.raises(ValueError, match='conserve'):
        validate_allocations(tmp_path)


@pytest.mark.parametrize('days,owner,message', [
    (['1970-01-01', '1970-01-03'], ['1', '1'], 'outside its bill period'),
    (['1970-01-01', '1970-01-01'], ['1', '1'], 'Duplicate bill-day'),
    (['1970-01-01', '1970-01-02'], ['1', '2'], 'another customer'),
    (['1970-01-01'], ['1'], 'Missing saved bill-days'),
])
def test_audit_rejects_wrong_dates_even_when_bill_total_is_conserved(tmp_path, days, owner, message):
    (tmp_path / 'run_manifest.json').write_text(json.dumps({'configuration': {
        'reconciliation_atol': 1e-8, 'reconciliation_rtol': 1e-10, 'redistribution_floor': 0.}}))
    pd.DataFrame({'bill_id': ['a'], 'record_status': ['accepted'], 'SubscriptionNumber': ['1'],
                  'start_ordinal': [0], 'end_ordinal': [2], 'day_count': [2],
                  'Consumption': [10.]}).to_parquet(tmp_path / 'normalized_bills.parquet')
    pd.DataFrame({'bill_id': ['a'] * len(days), 'SubscriptionNumber': owner,
                  'date_gregorian': pd.to_datetime(days),
                  'estimated_consumption': [10. / len(days)] * len(days)}).to_parquet(
        tmp_path / 'full_bill_daily.parquet')
    with pytest.raises(ValueError, match=message):
        validate_allocations(tmp_path)


def test_audit_checks_original_source_period_even_if_effective_dates_were_shifted(tmp_path):
    (tmp_path / 'run_manifest.json').write_text(json.dumps({'configuration': {
        'reconciliation_atol': 1e-8, 'reconciliation_rtol': 1e-10, 'redistribution_floor': 0.}}))
    pd.DataFrame({'bill_id': ['a'], 'record_status': ['accepted'], 'SubscriptionNumber': ['1'],
                  'start_ordinal': [1], 'end_ordinal': [3], 'day_count': [2],
                  'raw_FromDate': ['1970-01-01'], 'raw_ToDate': ['1970-01-02'],
                  'Consumption': [10.]}).to_parquet(tmp_path / 'normalized_bills.parquet')
    pd.DataFrame({'bill_id': ['a', 'a'], 'SubscriptionNumber': ['1', '1'],
                  'date_gregorian': pd.to_datetime(['1970-01-02', '1970-01-03']),
                  'estimated_consumption': [5., 5.]}).to_parquet(tmp_path / 'full_bill_daily.parquet')
    with pytest.raises(ValueError, match='outside its bill period'):
        validate_allocations(tmp_path)


def test_pipeline_tbs_summary_uses_the_same_excluded_dates(tmp_path):
    path = tmp_path / 'run_manifest.json'
    path.write_text(json.dumps({'tbs_comparison': {'rmse_m3': 999.}}))
    comparison = pd.DataFrame({'date_gregorian': pd.to_datetime(['2025-04-28', '2025-04-29']),
                               'tbs_daily_m3': [10., 1.],
                               'final_algorithm_consumption_m3': [10., 1000.]})
    update_tbs_summary(tmp_path, comparison, ['2025-04-29'])
    result = json.loads(path.read_text())['tbs_comparison']
    assert result['rmse_m3'] == 0 and result['matched_days'] == 1
    assert result['modeled_total_matched_m3'] == 10.
    assert [r['truth_scale'] for r in result['truth_reference_metrics']] == [1., .75]


def test_scaled_truth_changes_errors_and_r2_but_not_predictions_or_pearson():
    frame = pd.DataFrame({'tbs_daily_m3': [2., 4., 6.],
                          'final_algorithm_consumption_m3': [1., 2., 3.]})
    original = frame.copy(deep=True)
    raw, scaled = metric_scores(frame), metric_scores(frame, .75)
    assert raw['mape_percent'] == pytest.approx(50.)
    assert scaled['mape_percent'] == pytest.approx(100 / 3)
    assert raw['rmse_m3'] == pytest.approx(np.sqrt(14 / 3))
    assert scaled['rmse_m3'] == pytest.approx(np.sqrt(3.5 / 3))
    assert raw['r2'] == pytest.approx(-.75)
    assert scaled['r2'] == pytest.approx(1 - 3.5 / 4.5)
    assert raw['pearson_r'] == pytest.approx(1.)
    assert scaled['pearson_r'] == pytest.approx(raw['pearson_r'])
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize('actual,predicted,expected', [
    ([1., 2., 3.], [3., 2., 1.], -1.),
    ([1., 2., 3.], [2., 2., 2.], None),
    ([1., 1., 1.], [1., 2., 3.], None),
    ([1., np.nan], [2., 3.], None),
])
def test_pearson_known_values_and_undefined_series(actual, predicted, expected):
    result = metric_scores(pd.DataFrame({'tbs_daily_m3': actual,
                                         'final_algorithm_consumption_m3': predicted}))['pearson_r']
    assert result is None if expected is None else result == pytest.approx(expected)


def test_uniform_uses_effective_bill_totals_and_preserves_uncovered_days():
    ledger = pd.DataFrame({'bill_id': ['a', 'b', 'rejected'],
                           'record_status': ['accepted', 'accepted', 'rejected'],
                           'Consumption': [12., 0., 100.], 'day_count': [3, 2, 1]})
    daily = pd.DataFrame({'bill_id': ['a', 'a', 'b', None],
                          'estimated_consumption': [2., 10., 0., np.nan]})
    result = add_uniform_allocations(daily, ledger)
    np.testing.assert_allclose(result.uniform_consumption_m3, [4., 4., 0., np.nan], equal_nan=True)
    pd.testing.assert_series_equal(result.estimated_consumption, daily.estimated_consumption)
    with pytest.raises(ValueError, match='unknown accepted bill'):
        add_uniform_allocations(pd.DataFrame({'bill_id': ['rejected']}), ledger)


def grid_settings(**shared):
    return {'shared_parameters': {'n_lr_models': 5, 'n_disagg_cycles': 5, 'alpha': .05, **shared},
            'models': [{'name': name, 'branch': f'codex/{name}', 'parameters': {}}
                       for name in ['seasonal', 'fourier']]}


def test_shared_grid_runs_every_combination_on_both_models_without_mutating_config():
    settings = grid_settings(n_lr_models=[5, 10], n_disagg_cycles=[2, 5, 10], alpha=[.01, .05])
    original = deepcopy(settings)
    runs = expand_model_grid(settings)
    assert len(runs) == 24 and len({run['name'] for run in runs}) == 24
    for base in ['seasonal', 'fourier']:
        chosen = [run for run in runs if run['base_model'] == base]
        assert [(r['parameters']['n_lr_models'], r['parameters']['n_disagg_cycles'], r['parameters']['alpha'])
                for r in chosen] == list(product([5, 10], [2, 5, 10], [.01, .05]))
        assert all(r['branch'] == f'codex/{base}' for r in chosen)
    assert settings == original


@pytest.mark.parametrize('singletons', [False, True])
def test_scalar_and_singleton_grid_preserve_existing_names(singletons):
    settings = grid_settings()
    if singletons:
        settings['shared_parameters'] = {k: [v] for k, v in settings['shared_parameters'].items()}
    runs = expand_model_grid(settings)
    assert [r['name'] for r in runs] == ['seasonal', 'fourier']
    assert all(r['parameters'] == {'n_lr_models': 5, 'n_disagg_cycles': 5, 'alpha': .05} for r in runs)


def test_model_overrides_reduce_the_grid_and_duplicate_choices_do_not_repeat_runs():
    settings = grid_settings(n_lr_models=[5, 5, 10], n_disagg_cycles=5, alpha=[.01, .05])
    settings['models'][1]['parameters'] = {'n_lr_models': 10, 'alpha': .05}
    runs = expand_model_grid(settings)
    assert len(runs) == 5
    assert runs[-1]['name'] == 'fourier'
    assert runs[-1]['parameters'] == {'n_lr_models': 10, 'n_disagg_cycles': 5, 'alpha': .05}


@pytest.mark.parametrize('key,value', [
    ('n_lr_models', []), ('n_lr_models', [0, 5]), ('n_lr_models', [True]),
    ('n_disagg_cycles', [1.5]), ('n_disagg_cycles', [-1]),
    ('alpha', [1.01]), ('alpha', [float('nan')]), ('alpha', [False]),
    ('alpha', [[.05]]), ('customer_ridge_penalty', [1., 2.]),
])
def test_invalid_shared_grid_values_fail_before_any_simulation(key, value):
    with pytest.raises(ValueError):
        expand_model_grid(grid_settings(**{key: value}))


def test_lists_in_model_parameters_are_rejected_clearly():
    settings = grid_settings()
    settings['models'][0]['parameters']['alpha'] = [.01, .05]
    with pytest.raises(ValueError, match='put lists in shared_parameters'):
        expand_model_grid(settings)


def test_dry_run_prints_expanded_plan_without_creating_outputs(tmp_path, monkeypatch, capsys):
    settings = grid_settings(n_lr_models=[5, 10], alpha=[.01, .05])
    settings['output_directory'] = str(tmp_path / 'must-not-be-created')
    config = tmp_path / 'grid.json'
    config.write_text(json.dumps(settings))
    monkeypatch.setattr('sys.argv', ['runner', '--config', str(config), '--dry-run'])
    main()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 8 and lines[0].startswith('1/8: seasonal__g001')
    assert lines[-1].startswith('8/8: fourier__g004')
    assert not (tmp_path / 'must-not-be-created').exists()
