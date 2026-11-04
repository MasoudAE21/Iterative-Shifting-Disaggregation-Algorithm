"""Compare extended Town inputs without changing sources or model policies.

Run: .venv/Scripts/python.exe scripts/audit_town_extended.py
All date conversion is audit-only; production readers are probed separately.
"""
import csv
import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from isd.data import normalize_frame, audit_normalized, read_bills, sha256
from isd.weather import read_weather
from isd.bill_window import apply_bill_window
from isd.data import date_ordinal
from run_pipeline import CONFIG

D = ROOT / 'data/prepared'
O = ROOT / 'outputs/town_extended_audit'


def weather(name):
    raw = (D / name).read_bytes()
    try:
        text = raw.decode('utf-8-sig')
        encoding = 'utf-8-sig'
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
        encoding = 'cp1252'
    lines = text.splitlines()
    meta = dict(zip(next(csv.reader([lines[0]])), next(csv.reader([lines[1]]))))
    f = pd.read_csv(io.StringIO('\n'.join(lines[3:])))
    padding = [c for c in f if c.startswith('Unnamed:') and f[c].isna().all()]
    f = f.drop(columns=padding)
    fmt = '%m/%d/%Y' if f.time.str.contains('/').all() else '%Y-%m-%d'
    f.index = pd.to_datetime(f.pop('time'), format=fmt, errors='raise')
    try:
        read_weather(D / name)
        probe = 'accepted'
    except Exception as exc:
        probe = f'{type(exc).__name__}: {exc}'
    return f, dict(file=name, encoding=encoding, metadata=meta, rows=len(f),
        start=str(f.index.min().date()), end=str(f.index.max().date()),
        duplicate_dates=int(f.index.duplicated().sum()),
        missing_dates=len(pd.date_range(f.index.min(), f.index.max()).difference(f.index)),
        missing_values=int(f.isna().sum().sum()), nonfinite_values=int((~np.isfinite(f)).sum().sum()),
        negative_wind=int((f.iloc[:, -1] < 0).sum()), padding_columns=len(padding),
        statistics=f.describe().to_dict(), production_reader=probe)


def matrix(frame, ids, dates):
    lookup = {v: i for i, v in enumerate(ids)}
    m = np.zeros((len(ids), len(dates)), dtype=bool)
    volume = np.zeros(len(dates))
    origin = (dates[0] - pd.Timestamp('1970-01-01')).days
    for r in frame.itertuples():
        if r.SubscriptionNumber not in lookup:
            continue
        a, b = max(0, int(r.start_ordinal) - origin), min(len(dates), int(r.end_ordinal) - origin)
        if b > a:
            m[lookup[r.SubscriptionNumber], a:b] = True
            volume[a:b] += r.Consumption / r.day_count
    return m, volume


def main():
    O.mkdir(parents=True, exist_ok=True)
    roster = pd.read_csv(D / 'Customers_Town_Q.csv', dtype={'SubscriptionNumber': str})
    ids = sorted(roster.SubscriptionNumber.unique())
    dates = pd.date_range('2023-12-01', '2025-06-30')
    daily = pd.DataFrame(index=dates)
    tbs = pd.read_csv(D / 'TBS_Town_Q_daily_consumption.csv', parse_dates=['date_gregorian']).set_index('date_gregorian')
    blank_station_rows = int(tbs.index.isna().sum())
    tbs = tbs[tbs.index.notna()]
    daily['tbs_m3'] = tbs.consumption_m3
    summary = {'roster_customers': len(ids), 'roster_duplicates': int(roster.duplicated().sum()),
        'weather': {}, 'bills': {}, 'policy_scenarios': [], 'fingerprints': {},
        'tbs': {'dated_rows': len(tbs), 'blank_date_rows': blank_station_rows, 'start': str(tbs.index.min().date()), 'end': str(tbs.index.max().date()),
                'duplicate_dates': int(tbs.index.duplicated().sum()),
                'missing_dates': len(pd.date_range(tbs.index.min(), tbs.index.max()).difference(tbs.index)),
                'missing_value_dates': tbs.index[tbs.consumption_m3.isna()].strftime('%Y-%m-%d').tolist(),
                'zero_dates': tbs.index[tbs.consumption_m3.eq(0)].strftime('%Y-%m-%d').tolist(),
                'negative_dates': tbs.index[tbs.consumption_m3.lt(0)].strftime('%Y-%m-%d').tolist()}}
    ws = {}
    for key, name in [('old', 'open-meteo-34.41N50.49E1333m.csv'), ('new', 'open-meteo-2024-25.csv')]:
        ws[key], summary['weather'][key] = weather(name)
    w = ws['new']
    daily['weather_valid'] = w.reindex(dates).notna().all(axis=1)
    for c in w:
        daily[c] = w[c]
    common = ws['old'].join(w, lsuffix='_old', rsuffix='_new', how='inner')
    summary['weather_overlap'] = {'days': len(common), 'variables': {}}
    for c in ws['old']:
        delta = common[c + '_new'] - common[c + '_old']
        summary['weather_overlap']['variables'][c] = {'mean_new_minus_old': float(delta.mean()),
            'mae': float(delta.abs().mean()), 'max_absolute_difference': float(delta.abs().max()),
            'correlation': float(common[c + '_new'].corr(common[c + '_old']))}
    frames, mats = {}, {}
    for key, name, fmt in [('old', 'bill_Customers_Town_Q.csv', '%Y-%m-%d'),
                           ('new', 'bill_Customers_Town_Q_full_year.csv', '%m/%d/%Y')]:
        raw = pd.read_csv(D / name, dtype=str, keep_default_na=False)
        canonical = raw.copy()
        for c in ['FromDate', 'ToDate']:
            canonical[c] = pd.to_datetime(raw[c], format=fmt, errors='raise').dt.strftime('%Y-%m-%d')
        normalized = normalize_frame(canonical, sha256(D / name), name)
        audited, audit = audit_normalized(normalized, cfg=CONFIG)
        frames[key] = canonical
        accepted = audited[audited.record_status.eq('accepted')]
        valid = normalized[normalized.record_status.eq('accepted')]
        m, volume = matrix(valid.drop_duplicates(subset=list(canonical.columns)), ids, dates)
        mats[key] = m
        daily[key + '_raw_coverage'] = m.mean(axis=0)
        daily[key + '_uniform_m3'] = volume
        audit.update(file=name, start=canonical.FromDate.min(), end=canonical.ToDate.max(),
            customers_outside_roster=len(set(raw.SubscriptionNumber) - set(ids)),
            roster_without_bills=len(set(ids) - set(raw.SubscriptionNumber)),
            duration_quantiles=valid.day_count.astype(float).quantile([0, .5, .9, .95, .99, 1]).to_dict(),
            bills_per_customer_quantiles=raw.groupby('SubscriptionNumber').size().quantile([0,.5,.9,1]).to_dict(),
            field_counts={c: raw[c].value_counts().to_dict() for c in ['ConsumptionType', 'UnitCount', 'Capacity']},
            attribute_changing_customers={c: int((raw.groupby('SubscriptionNumber')[c].nunique()>1).sum()) for c in ['ConsumptionType','UnitCount','Capacity']})
        joined = canonical.merge(roster[['SubscriptionNumber','Capacity','UnitCount']], on='SubscriptionNumber', suffixes=('', '_roster'))
        audit['attribute_comparison_rows'] = len(joined)
        audit['as_labeled_capacity_unit_match_rows'] = int(((pd.to_numeric(joined.Capacity) == joined.Capacity_roster) & (pd.to_numeric(joined.UnitCount) == joined.UnitCount_roster)).sum())
        audit['hypothesized_rotated_capacity_unit_match_rows'] = int(((pd.to_numeric(joined.ConsumptionType) == joined.Capacity_roster) & (pd.to_numeric(joined.Capacity) == joined.UnitCount_roster)).sum())
        _, probe = read_bills(D / name, CONFIG)
        audit['production_reader_status_counts'] = probe['record_status_counts']
        summary['bills'][key] = audit
        if key == 'new':
            summary['current_boundary_policy_scenarios'] = []
            for cap in [100,150,None]:
                cfg = replace(CONFIG, max_bill_days=cap)
                adjusted, ledger = apply_bill_window(audited, cfg, date_ordinal(cfg.target_start), date_ordinal(cfg.target_end_exclusive))
                mm, vv = matrix(adjusted[adjusted.record_status.eq('accepted')], ids, dates)
                mask = (dates >= cfg.target_start) & (dates < cfg.target_end_exclusive)
                summary['current_boundary_policy_scenarios'].append(dict(duration_cap=cap, ledger=ledger,
                    minimum_coverage=float(mm[:,mask].mean(axis=0).min()), full_customers=int(mm[:,mask].all(axis=1).sum()),
                    uniform_to_tbs_ratio=float(vv[mask].sum()/daily.tbs_m3[mask].sum())))
        # Same policy and same new weather for a fair bill-history comparison.
        for cap in [None, 60, 90, 100, 120, 150, 180, 365]:
            kept = accepted[(accepted.FromDate >= str(w.index.min().date())) & (accepted.ToDate <= str(w.index.max().date()))]
            if cap is not None:
                kept = kept[kept.day_count <= cap]
            mm, vv = matrix(kept, ids, dates)
            for start, end in [('2025-01-02','2025-02-28'), ('2024-01-01','2024-12-31'), ('2024-12-01','2025-02-28'), ('2025-01-01','2025-03-31')]:
                mask = (dates >= start) & (dates <= end)
                paired = mask & daily.tbs_m3.gt(0).to_numpy() & daily.weather_valid.to_numpy()
                summary['policy_scenarios'].append(dict(source=key, duration_cap=cap, start=start, end=end,
                    days=int(mask.sum()), positive_tbs_weather_days=int(paired.sum()),
                    minimum_coverage=float(mm[:, mask].mean(axis=0).min()),
                    mean_coverage=float(mm[:, mask].mean()), fully_covered_customers=int(mm[:,mask].all(axis=1).sum()),
                    retained_bills=len(kept), uniform_to_tbs_ratio=float(vv[paired].sum()/daily.tbs_m3[paired].sum())))
            if cap is None:
                daily[key + '_weather_bounded_coverage'] = mm.mean(axis=0)
        if key == 'new':
            for period_start, period_end in [('2025-01-02','2025-02-28'),('2024-01-01','2024-12-31')]:
                crossing = accepted[(accepted.FromDate<=period_end)&(accepted.ToDate>=period_start)]
                summary.setdefault('full_bill_weather_requirements', []).append(dict(
                    start=period_start, end=period_end, intersecting_bills=len(crossing),
                    required_start=crossing.FromDate.min(), required_end_inclusive=crossing.ToDate.max(),
                    before_weather=int((crossing.FromDate<str(w.index.min().date())).sum()),
                    after_weather=int((crossing.ToDate>str(w.index.max().date())).sum())))
    keys = ['SubscriptionNumber','FromDate','ToDate']
    joined = frames['old'].merge(frames['new'], on=keys, suffixes=('_old','_new'))
    summary['bill_overlap'] = {'matching_interval_rows': len(joined),
        'old_rows': len(frames['old']),
        'same_consumption': int((joined.Consumption_old == joined.Consumption_new).sum()),
        'same_all_labeled_fields': int(np.logical_and.reduce([(joined[c+'_old']==joined[c+'_new']).to_numpy() for c in ['Consumption','ConsumptionType','UnitCount','Capacity']]).sum()),
        'rotation_matches': int(((joined.ConsumptionType_new==joined.Capacity_old)&(joined.UnitCount_new==joined.ConsumptionType_old)&(joined.Capacity_new==joined.UnitCount_old)).sum())}
    monthly = []
    for month, block in daily.groupby(daily.index.to_period('M')):
        if month < pd.Period('2024-01') or month > pd.Period('2025-03'):
            continue
        mask = dates.isin(block.index)
        paired = block.tbs_m3.gt(0) & block.weather_valid
        monthly.append(dict(month=str(month), days=len(block), weather_days=int(block.weather_valid.sum()),
            positive_tbs_days=int(block.tbs_m3.gt(0).sum()),
            old_min_coverage=float(block.old_raw_coverage.min()), new_min_coverage=float(block.new_raw_coverage.min()),
            new_fully_covered_customers=int(mats['new'][:,mask].all(axis=1).sum()),
            new_weather_bounded_min=float(block.new_weather_bounded_coverage.min()),
            uniform_to_tbs_ratio=float(block.new_uniform_m3[paired].sum()/block.tbs_m3[paired].sum()) if paired.any() else None))
    pd.DataFrame(monthly).to_csv(O / 'monthly_coverage.csv', index=False)
    pd.DataFrame(summary['policy_scenarios']).to_csv(O / 'policy_scenarios.csv', index=False)
    # Winter windows are screening candidates, not automatically selected validation targets.
    candidates = []
    for length in [30, 60, 90]:
        for i in range(len(dates)-length+1):
            block = daily.iloc[i:i+length]
            if not (block.index.month.isin([11,12,1,2,3]).all() and block.weather_valid.all() and block.tbs_m3.gt(0).all()):
                continue
            candidates.append(dict(days=length, start=str(block.index[0].date()), end=str(block.index[-1].date()),
                minimum_raw_coverage=float(block.new_raw_coverage.min()),
                minimum_weather_bounded_coverage=float(block.new_weather_bounded_coverage.min()),
                full_raw_customers=int(mats['new'][:,i:i+length].all(axis=1).sum()),
                mean_tbs_m3=float(block.tbs_m3.mean())))
    pd.DataFrame(candidates).sort_values(['days','minimum_weather_bounded_coverage','mean_tbs_m3'], ascending=[True,False,False]).to_csv(O / 'winter_candidates.csv', index=False)
    for p in D.glob('*.csv'):
        summary['fingerprints'][p.name] = sha256(p)
    daily.to_csv(O / 'daily_coverage.csv', index_label='date')
    (O / 'audit.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['policy_scenarios', 'fingerprints']}, indent=2, default=str))


if __name__ == '__main__':
    main()
