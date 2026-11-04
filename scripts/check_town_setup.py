"""Audit the configured Town inputs and boundaries without fitting the solver."""
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_pipeline import CONFIG, BILLS_PATH
from isd.data import read_bills, coverage_classes, sha256
from isd.weather import read_weather, daily_integral
from isd.bill_window import resolve_window, apply_bill_window


def main():
    cfg = replace(CONFIG, **json.loads((ROOT/'configs/town.json').read_text())).validate()
    weather_path = ROOT/'data/prepared/open-meteo-2024-25.csv'
    seconds, values, metadata = read_weather(weather_path)
    start, end = resolve_window(seconds, values, cfg)
    source, audit = read_bills(BILLS_PATH, cfg)
    bounded, ledger = apply_bill_window(source, cfg, start, end)
    classes = coverage_classes(bounded, start, end)
    accepted = bounded[bounded.record_status.eq('accepted')]
    counts = np.zeros(end-start+1, dtype=int)
    for r in accepted.itertuples():
        counts[int(r.start_ordinal)-start] += 1
        counts[int(r.end_ordinal)-start] -= 1
    daily = daily_integral(seconds, values, np.arange(start,end))
    daily['accepted_active_bills'] = counts.cumsum()[:-1]
    station = pd.read_csv(ROOT/cfg.tbs_path)
    station['date_gregorian'] = pd.to_datetime(station.date_gregorian, format='mixed').dt.date
    daily = daily.merge(station[['date_gregorian','consumption_m3']], on='date_gregorian', how='left', validate='one_to_one')
    summary = dict(configuration=cfg.as_dict(), days=end-start, source_audit=audit,
                   boundary_policy=ledger, coverage_classes=dict(Counter(v[0] for v in classes.values())),
                   minimum_accepted_active_bills=int(daily.accepted_active_bills.min()),
                   missing_tbs_days=int(daily.consumption_m3.isna().sum()),
                   zero_tbs_days=int(daily.consumption_m3.eq(0).sum()),
                   weather_metadata=metadata,
                   source_hashes={BILLS_PATH.name:sha256(BILLS_PATH),weather_path.name:sha256(weather_path)})
    out = ROOT/'outputs/town_setup'
    out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out/'daily_readiness.csv',index=False)
    (out/'readiness.json').write_text(json.dumps(summary, indent=2),encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
