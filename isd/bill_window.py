"""Bound modeled bills without changing source records or hiding adjustments."""
import numpy as np
import pandas as pd

from .data import date_ordinal
from .weather import daily_integral

MONTH_WEIGHTS = {1: 1.0, 2: 1.0, 3: 0.57, 4: 0.1, 5: 0.1, 6: 0.1,
                 7: 0.1, 8: 0.1, 9: 0.1, 10: 0.2, 11: 0.55, 12: 0.8}

def bill_weight_sum(start, end):
    """Sum daily calendar-month weights over an original half-open bill."""
    days = pd.date_range(pd.Timestamp(int(start), unit='D'), periods=int(end - start))
    return float(sum(MONTH_WEIGHTS[month] for month in days.month))



def resolve_window(seconds, values, cfg):
    """Find complete local weather days; never bridge a weather gap."""
    if cfg.bill_window == 'simulation' or cfg.bill_boundary_policy in ('clip_preserve_total', 'monthly_weighted'):
        if cfg.bill_window == 'target':
            start, end = date_ordinal(cfg.target_start), date_ordinal(cfg.target_end_exclusive)
        else:
            start, end = date_ordinal(cfg.simulation_start), date_ordinal(cfg.simulation_end_exclusive)
        if start >= end:
            raise ValueError('Simulation window must be nonempty')
        daily = daily_integral(seconds, values, np.arange(start, end), cfg.timezone)
        if not (daily.weather_status == 'complete').all():
            missing = daily.loc[daily.weather_status != 'complete', 'date_gregorian']
            raise ValueError(f'Simulation requires complete weather on every day: {len(missing)} missing days ({missing.iloc[0]} through {missing.iloc[-1]})')
        return start, end
    dates = pd.to_datetime([seconds[0], seconds[-1]], unit='s', utc=True).tz_convert(cfg.timezone)
    start, end = (date_ordinal(d.date().isoformat()) for d in dates)
    if cfg.bill_window == 'target':
        start = max(start, date_ordinal(cfg.target_start))
        end = min(end, date_ordinal(cfg.target_end_exclusive) - 1)
    if start > end:
        raise ValueError('No overlap between bill window and available weather')
    days = np.arange(start, end + 1)
    daily = daily_integral(seconds, values, days, cfg.timezone)
    complete = days[daily.weather_status.to_numpy() == 'complete']
    if not len(complete):
        raise ValueError('No complete weather days in bill window')
    if np.any(np.diff(complete) != 1):
        raise ValueError('Weather has internal gaps; choose a continuous target window or repair weather')
    return int(complete[0]), int(complete[-1]) + 1


def apply_bill_window(source, cfg, start, end):
    """Apply boundaries to audited bills; rejected source records stay rejected.

    All intervals are half-open. Source IDs and raw_* values remain unchanged;
    reconciliation applies to the effective Consumption, not the original total.
    """
    result = source.copy()
    accepted = result.record_status == 'accepted'
    result['original_day_count'] = result.day_count
    result['original_consumption'] = result.Consumption
    result['retained_fraction'] = np.where(accepted, 1.0, 0.0)
    result['window_action'] = np.where(accepted, 'unchanged', 'source_rejected')
    left = result.start_ordinal.clip(lower=start)
    right = result.end_ordinal.clip(upper=end)
    overlaps = (right > left).fillna(False)
    contained = ((result.start_ordinal >= start) & (result.end_ordinal <= end)).fillna(False)
    too_long = accepted & (result.day_count > cfg.max_bill_days) if cfg.max_bill_days is not None else accepted & False
    if cfg.bill_duration_scope == 'boundary':
        too_long &= overlaps & ~contained
    result.loc[too_long, 'record_status'] = 'excluded_window'
    result.loc[too_long, 'exclusion_reason'] = 'bill_duration_exceeds_limit'
    result.loc[too_long, 'window_action'] = 'excluded_duration'
    result.loc[too_long, 'retained_fraction'] = 0.0
    accepted = accepted & ~too_long
    excluded = accepted & (~contained if cfg.bill_boundary_policy == 'exclude' else ~overlaps)
    result.loc[excluded, 'record_status'] = 'excluded_window'
    result.loc[excluded, 'exclusion_reason'] = 'bill_window_exclusion'
    result.loc[excluded, 'window_action'] = 'excluded'
    result.loc[excluded, 'retained_fraction'] = 0.0
    clipped = accepted & ~excluded & ~contained
    if cfg.bill_boundary_policy == 'prorate':
        result.loc[clipped, 'retained_fraction'] = (right - left)[clipped] / result.loc[clipped, 'day_count']
        result.loc[clipped, 'Consumption'] *= result.loc[clipped, 'retained_fraction']
    if cfg.bill_boundary_policy == 'monthly_weighted':
        result['original_weight_sum'] = np.nan
        result['retained_weight_sum'] = np.nan
        result['target_day_count'] = (right - left).clip(lower=0)
        eligible = accepted & ~excluded
        if eligible.any():
            # Prefix sums avoid rebuilding daily calendars for every bill.
            origin = int(result.loc[eligible, 'start_ordinal'].min())
            stop = int(result.loc[eligible, 'end_ordinal'].max())
            dates = pd.date_range(pd.Timestamp(origin, unit='D'), periods=stop-origin)
            prefix = np.concatenate(([0.0], np.cumsum([MONTH_WEIGHTS[m] for m in dates.month])))
            indices = result.index[eligible]
            starts = result.loc[indices, 'start_ordinal'].to_numpy(dtype=int)
            ends = result.loc[indices, 'end_ordinal'].to_numpy(dtype=int)
            denominator = prefix[ends-origin] - prefix[starts-origin]
            numerator = prefix[right.loc[indices].to_numpy(dtype=int)-origin] - prefix[left.loc[indices].to_numpy(dtype=int)-origin]
            result.loc[indices, 'original_weight_sum'] = denominator
            result.loc[indices, 'retained_weight_sum'] = numerator
            multiplier = np.clip(numerator / denominator, 0.0, 1.0)
            result.loc[indices, 'retained_fraction'] = multiplier
            result.loc[indices, 'Consumption'] *= multiplier
    if cfg.bill_boundary_policy in ('prorate', 'clip_preserve_total', 'monthly_weighted'):
        result.loc[clipped, 'start_ordinal'] = left[clipped]
        result.loc[clipped, 'end_ordinal'] = right[clipped]
        result.loc[clipped, 'inclusive_end_ordinal'] = right[clipped] - 1
        result.loc[clipped, 'day_count'] = (right - left)[clipped]
        for column, ordinals in [('FromDate', left), ('ToDate', right - 1)]:
            result.loc[clipped, column] = pd.to_datetime(ordinals[clipped], unit='D', origin='unix').dt.strftime('%Y-%m-%d')
        result.loc[clipped, 'window_action'] = {'prorate': 'prorated', 'clip_preserve_total': 'clipped_preserved_total', 'monthly_weighted': 'monthly_weighted'}[cfg.bill_boundary_policy]
    retained = result.record_status == 'accepted'
    summary = {
        'policy': cfg.bill_boundary_policy, 'window': cfg.bill_window,
        'duration_scope': cfg.bill_duration_scope, 'max_bill_days': cfg.max_bill_days,
        'weight_formula': 'retained_weight_sum / original_weight_sum' if cfg.bill_boundary_policy == 'monthly_weighted' else None,
        'start': str(pd.Timestamp(start, unit='D').date()),
        'end_exclusive': str(pd.Timestamp(end, unit='D').date()),
        'excluded_bills': int((excluded | too_long).sum()),
        'excluded_duration_bills': int(too_long.sum()),
        'clipped_preserved_total_bills': int((result.window_action == 'clipped_preserved_total').sum()),
        'monthly_weighted_bills': int((result.window_action == 'monthly_weighted').sum()),
        'month_weights': MONTH_WEIGHTS if cfg.bill_boundary_policy == 'monthly_weighted' else None,
        'prorated_bills': int((result.window_action == 'prorated').sum()),
        'original_accepted_consumption': float(source.loc[source.record_status == 'accepted', 'Consumption'].sum()),
        'retained_consumption': float(result.loc[retained, 'Consumption'].sum()),
        'reconciliation_basis': 'effective bill totals; raw_Consumption preserves source totals',
    }
    summary['removed_consumption'] = summary['original_accepted_consumption'] - summary['retained_consumption']
    return result, summary
