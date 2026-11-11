"""Customer summer baselines on audited, effective, nonoverlapping bill intervals."""
import numpy as np
import pandas as pd


def normalize_consumption(source, cfg):
    """Divide accepted bill totals once; keep original source fields for provenance."""
    result = source.copy()
    result['consumption_before_unit_normalization'] = result.Consumption
    if cfg.divide_consumption_by_unit_count:
        accepted = result.record_status == 'accepted'
        units = result.loc[accepted, 'UnitCount'].to_numpy(dtype=float)
        if not np.isfinite(units).all() or np.any(units < 1) or np.any(units != np.floor(units)):
            raise ValueError('UnitCount must be a positive integer for consumption normalization')
        result.loc[accepted, 'Consumption'] = result.loc[accepted, 'Consumption'] / units
    return result


def attach_customer_floors(source, cfg):
    """Weight uniform bill consumption by covered June 1--September 30 days.

    Auditing has removed overlapping customer histories, so overlap counts are
    covered days, not duplicate observations. All available summers are pooled.
    """
    result = source.copy()
    accepted = result.record_status == 'accepted'
    bills = result.loc[accepted]
    result['summer_covered_days'] = 0
    result['summer_daily_baseline'] = np.nan
    result['daily_floor'] = np.nan
    result['floor_source'] = 'not_accepted'
    result['floor_feasibility_adjusted'] = False
    if bills.empty:
        return result
    means = (bills.Consumption / bills.day_count).astype('float64')
    if not cfg.customer_summer_floor:
        result.loc[accepted, 'daily_floor'] = cfg.redistribution_floor * means
        result.loc[accepted, 'floor_source'] = 'bill_relative'
        return result
    origin = int(bills.start_ordinal.min())
    end = int(bills.end_ordinal.max())
    dates = pd.date_range(pd.Timestamp(origin, unit='D'), periods=end-origin)
    prefix = np.r_[0, np.cumsum((dates.month >= 6) & (dates.month <= 9))]
    counts = prefix[bills.end_ordinal.to_numpy(dtype=int)-origin] - prefix[bills.start_ordinal.to_numpy(dtype=int)-origin]
    evidence = pd.DataFrame({'customer': bills.SubscriptionNumber,
                             'days': counts, 'volume': counts * means})
    grouped = evidence.groupby('customer')[['days', 'volume']].sum()
    covered = bills.SubscriptionNumber.map(grouped.days)
    baseline = bills.SubscriptionNumber.map(grouped.volume / grouped.days.replace(0, np.nan))
    sufficient = covered >= cfg.summer_min_covered_days
    requested = (cfg.summer_floor_fraction * baseline).where(sufficient, cfg.summer_fallback_fraction * means)
    result.loc[accepted, 'summer_covered_days'] = covered
    result.loc[accepted, 'summer_daily_baseline'] = baseline
    result.loc[accepted, 'daily_floor'] = np.minimum(requested, means)
    result.loc[accepted, 'floor_source'] = np.where(sufficient, 'customer_summer', 'insufficient_summer_fallback')
    result.loc[accepted, 'floor_feasibility_adjusted'] = requested > means
    return result
