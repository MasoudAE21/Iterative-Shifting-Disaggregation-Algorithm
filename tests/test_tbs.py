import pandas as pd
import pytest
from isd.config import Config
from isd.tbs import compare_tbs

def test_comparison_without_station_preserves_zero_and_missing(tmp_path):
    from isd.tbs import export_simulation_comparison
    pd.DataFrame({'date_gregorian': ['2025-02-10', '2025-02-12'],
                  'uniform_baseline_sum': [0, 10], 'combined_observed_support_sum': [0, 12],
                  'coverage_fraction': [.5, .75], 'total_floor_consumption_m3': [0, 3]}).to_csv(
                      tmp_path/'aggregate_daily_summary.csv', index=False)
    cfg = Config(bill_window='target', target_start='2025-02-10', target_end_exclusive='2025-02-13')
    result = export_simulation_comparison(tmp_path, tmp_path, cfg)
    assert list(result.columns) == ['date_gregorian', 'total_uniform_consumption_m3',
        'final_algorithm_consumption_m3', 'included_customer_fraction', 'total_floor_consumption_m3']
    assert result.final_algorithm_consumption_m3.iloc[0] == 0
    assert pd.isna(result.final_algorithm_consumption_m3.iloc[1])
    assert result.final_algorithm_consumption_m3.iloc[2] == 12

@pytest.mark.parametrize('values,matched,missing', [([10, 20, None], 2, 0), ([10, None, 30], 1, 1), ([None, None, 30], 0, 2)])
def test_missing_measurements(tmp_path, values, matched, missing):
    dates = ['2025-01-02', '2025-01-03', '2025-06-07']
    station = tmp_path / 'station.csv'
    pd.DataFrame({'date_gregorian': dates, 'consumption_m3': values}).to_csv(station, index=False)
    pd.DataFrame({'date_gregorian': dates[:2], 'combined_observed_support_sum': [12, 24], 'uniform_baseline_sum': [18, 18], 'coverage_fraction': [1, .5]}).to_csv(tmp_path / 'aggregate_daily_summary.csv', index=False)
    result = compare_tbs(station, tmp_path, Config(target_start='2025-01-02', target_end_exclusive='2025-01-04'))
    assert result['matched_days'] == matched
    assert result['missing_tbs_days'] == missing
    assert result['modeled_total_matched_m3'] == ({2: 36, 1: 12, 0: None}[matched])
    assert len(pd.read_csv(tmp_path / 'tbs_daily_comparison.csv')) == 2


def test_full_simulation_export(tmp_path):
    station = tmp_path / 'station.csv'
    pd.DataFrame({'date_gregorian': ['2024-11-01', '2025-03-31'],
                  'consumption_m3': [10, 30]}).to_csv(station, index=False)
    dates = pd.date_range('2024-11-01', '2025-03-31')
    pd.DataFrame({'date_gregorian': dates, 'uniform_baseline_sum': 15,
                  'combined_observed_support_sum': 20, 'coverage_fraction': .75,
                  'total_floor_consumption_m3': 7}).to_csv(tmp_path / 'aggregate_daily_summary.csv', index=False)
    compare_tbs(station, tmp_path, Config())
    result = pd.read_csv(tmp_path / 'simulation_daily_comparison.csv')
    assert len(result) == 151
    assert result.date_gregorian.iloc[0] == '2024-11-01'
    assert result.date_gregorian.iloc[-1] == '2025-03-31'
    assert result.total_uniform_consumption_m3.sum() == 151 * 15
    assert result.final_algorithm_consumption_m3.sum() == 151 * 20
    assert result.tbs_daily_m3.isna().sum() == 149
    assert result.included_customer_fraction.eq(.75).all()
    assert result.total_floor_consumption_m3.eq(7).all()
    metadata = compare_tbs(station, tmp_path, Config(divide_consumption_by_unit_count=True))
    assert metadata['station_metrics_comparable'] is False
    assert metadata['rmse_m3'] is None


def test_customer_fraction_uses_roster_including_customers_without_bills(tmp_path):
    station = tmp_path / 'station.csv'
    roster = tmp_path / 'roster.csv'
    dates = ['2025-01-01', '2025-01-02']
    pd.DataFrame({'date_gregorian': dates, 'consumption_m3': [10, 20]}).to_csv(station, index=False)
    pd.DataFrame({'SubscriptionNumber': ['A','B','C','D','D']}).to_csv(roster, index=False)
    pd.DataFrame({'date_gregorian': dates, 'uniform_baseline_sum': [0, 12],
                  'combined_observed_support_sum': [0, 13], 'n_customers_covered': [2, 3],
                  'coverage_fraction': [2/3, 1]}).to_csv(tmp_path / 'aggregate_daily_summary.csv', index=False)
    cfg = Config(bill_window='target', target_start='2025-01-01', target_end_exclusive='2025-01-03')
    metadata = compare_tbs(station, tmp_path, cfg, roster_path=roster)
    result = pd.read_csv(tmp_path / 'simulation_daily_comparison.csv')
    assert result.included_customer_fraction.tolist() == [.5, .75]
    assert metadata['customer_roster_count'] == 4
    assert metadata['customer_fraction_denominator'] == 'roster'
