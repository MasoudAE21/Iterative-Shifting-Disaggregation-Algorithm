"""Bound modeled bills without changing source records or hiding adjustments."""
import numpy as np
import pandas as pd

from .data import date_ordinal
from .weather import daily_integral


def resolve_window(seconds, values, cfg):
    """Find complete local weather days; never bridge a weather gap."""
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
    excluded = accepted & (~contained if cfg.bill_boundary_policy == 'exclude' else ~overlaps)
    result.loc[excluded, 'record_status'] = 'excluded_window'
    result.loc[excluded, 'exclusion_reason'] = 'bill_window_exclusion'
    result.loc[excluded, 'window_action'] = 'excluded'
    result.loc[excluded, 'retained_fraction'] = 0.0
    clipped = accepted & ~excluded & ~contained
    if cfg.bill_boundary_policy == 'prorate':
        result.loc[clipped, 'retained_fraction'] = (right - left)[clipped] / result.loc[clipped, 'day_count']
        result.loc[clipped, 'Consumption'] *= result.loc[clipped, 'retained_fraction']
        result.loc[clipped, 'start_ordinal'] = left[clipped]
        result.loc[clipped, 'end_ordinal'] = right[clipped]
        result.loc[clipped, 'inclusive_end_ordinal'] = right[clipped] - 1
        result.loc[clipped, 'day_count'] = (right - left)[clipped]
        for column, ordinals in [('FromDate', left), ('ToDate', right - 1)]:
            result.loc[clipped, column] = pd.to_datetime(ordinals[clipped], unit='D', origin='unix').dt.strftime('%Y-%m-%d')
        result.loc[clipped, 'window_action'] = 'prorated'
    retained = result.record_status == 'accepted'
    summary = {
        'policy': cfg.bill_boundary_policy, 'window': cfg.bill_window,
        'start': str(pd.Timestamp(start, unit='D').date()),
        'end_exclusive': str(pd.Timestamp(end, unit='D').date()),
        'excluded_bills': int(excluded.sum()),
        'prorated_bills': int((result.window_action == 'prorated').sum()),
        'original_accepted_consumption': float(source.loc[accepted, 'Consumption'].sum()),
        'retained_consumption': float(result.loc[retained, 'Consumption'].sum()),
        'reconciliation_basis': 'effective bill totals; raw_Consumption preserves source totals',
    }
    summary['removed_consumption'] = summary['original_accepted_consumption'] - summary['retained_consumption']
    return result, summary
