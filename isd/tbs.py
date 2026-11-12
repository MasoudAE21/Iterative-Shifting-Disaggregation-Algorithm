"""Compare modeled customer support with station measurements, without adjustment."""
import numpy as np
import pandas as pd
from .data import sha256

def export_simulation_comparison(run, out, cfg):
    """Export saved modeled totals without requiring station observations."""
    modeled = pd.read_csv(run / 'aggregate_daily_summary.csv', parse_dates=['date_gregorian'])
    dates = pd.DataFrame({'date_gregorian': pd.date_range(
        cfg.target_start if cfg.bill_window == 'target' else cfg.simulation_start,
        cfg.target_end_exclusive if cfg.bill_window == 'target' else cfg.simulation_end_exclusive,
        inclusive='left')})
    if 'total_floor_consumption_m3' not in modeled:
        modeled['total_floor_consumption_m3'] = np.nan
    columns = {'uniform_baseline_sum': 'total_uniform_consumption_m3',
               'combined_observed_support_sum': 'final_algorithm_consumption_m3',
               'coverage_fraction': 'included_customer_fraction',
               'total_floor_consumption_m3': 'total_floor_consumption_m3'}
    comparison = dates.merge(modeled[['date_gregorian', *columns]],
                             on='date_gregorian', how='left', validate='one_to_one').rename(columns=columns)
    comparison.to_csv(out / 'simulation_daily_comparison.csv', index=False)
    return comparison

def compare_tbs(path, out, cfg, *, roster_path=None):
    station = pd.read_csv(path, parse_dates=['date_gregorian'])
    station = station[['date_gregorian', 'consumption_m3']]
    if station.date_gregorian.duplicated().any():
        raise ValueError('Duplicate TBS dates')
    station['consumption_m3'] = pd.to_numeric(station.consumption_m3, errors='raise')
    if np.isinf(station.consumption_m3.to_numpy(dtype=float)).any():
        raise ValueError('Infinite TBS consumption')
    # Blank measurements stay missing and are excluded from paired metrics.
    modeled = pd.read_csv(out / 'aggregate_daily_summary.csv', parse_dates=['date_gregorian'])
    if 'total_floor_consumption_m3' not in modeled:
        modeled['total_floor_consumption_m3'] = np.nan
    # Include supported zero-use customers and uniform fallback customers.
    # A roster denominator also accounts for customers with no source bills.
    roster_count = None
    if roster_path is not None:
        roster = pd.read_csv(roster_path, dtype={'SubscriptionNumber': str})
        roster_count = roster.SubscriptionNumber.dropna().nunique()
        if not roster_count:
            raise ValueError('Customer roster is empty')
        modeled['included_customer_fraction'] = modeled.n_customers_covered / roster_count
    else:
        modeled['included_customer_fraction'] = modeled.coverage_fraction
    if not modeled.included_customer_fraction.between(0, 1).all():
        raise ValueError('Included customer fraction must be between zero and one')
    simulation_dates = pd.DataFrame({'date_gregorian': pd.date_range(
        cfg.target_start if cfg.bill_window == 'target' else cfg.simulation_start,
        cfg.target_end_exclusive if cfg.bill_window == 'target' else cfg.simulation_end_exclusive, inclusive='left')})
    simulation = simulation_dates.merge(
        modeled[['date_gregorian', 'uniform_baseline_sum', 'combined_observed_support_sum', 'included_customer_fraction', 'total_floor_consumption_m3']],
        on='date_gregorian', how='left', validate='one_to_one',
    ).merge(station, on='date_gregorian', how='left', validate='one_to_one')
    simulation = simulation.rename(columns={
        'consumption_m3': 'tbs_daily_m3',
        'uniform_baseline_sum': 'total_uniform_consumption_m3',
        'combined_observed_support_sum': 'final_algorithm_consumption_m3',
    })
    simulation[['date_gregorian', 'tbs_daily_m3', 'total_uniform_consumption_m3',
                'final_algorithm_consumption_m3', 'included_customer_fraction', 'total_floor_consumption_m3']].to_csv(out / 'simulation_daily_comparison.csv', index=False)
    dates = pd.DataFrame({'date_gregorian': pd.date_range(cfg.target_start, cfg.target_end_exclusive, inclusive='left')})
    comparison = dates.merge(modeled, on='date_gregorian', how='left', validate='one_to_one').merge(station, on='date_gregorian', how='left', validate='one_to_one')
    comparison['difference_m3'] = (np.nan if cfg.divide_consumption_by_unit_count else
                                   comparison.combined_observed_support_sum - comparison.consumption_m3)
    comparison.to_csv(out / 'tbs_daily_comparison.csv', index=False)
    paired = comparison.dropna(subset=['difference_m3'])
    return {
        'modeled_consumption_basis': 'sum_of_bill_consumption_per_unit' if cfg.divide_consumption_by_unit_count else 'customer_total',
        'station_metrics_comparable': not cfg.divide_consumption_by_unit_count,
        'path': str(path), 'sha256': sha256(path),
        'customer_fraction_denominator': 'roster' if roster_path is not None else 'selected_run_population',
        'customer_roster_count': roster_count,
        'customer_roster_sha256': sha256(roster_path) if roster_path is not None else None,
        'comparison_days': len(comparison), 'matched_days': len(paired),
        'missing_tbs_days': int(comparison.consumption_m3.isna().sum()),
        'missing_tbs_dates': comparison.loc[comparison.consumption_m3.isna(), 'date_gregorian'].dt.strftime('%Y-%m-%d').tolist(),
        'modeled_total_matched_m3': float(paired.combined_observed_support_sum.sum()) if len(paired) else None,
        'tbs_total_matched_m3': float(paired.consumption_m3.sum()) if len(paired) else None,
        'bias_m3': float(paired.difference_m3.mean()) if len(paired) else None,
        'mae_m3': float(paired.difference_m3.abs().mean()) if len(paired) else None,
        'rmse_m3': float(np.sqrt((paired.difference_m3 ** 2).mean())) if len(paired) else None,
        'scope': 'Available customer support, including uniform fallback; missing customer days are not measured zeros. Station and customer coverage may differ.',
    }
