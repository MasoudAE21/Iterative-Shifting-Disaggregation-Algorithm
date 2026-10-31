"""Report current daily-weather readiness for the confirmed validation period."""
from pathlib import Path
import json
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/town_analysis'
s=json.loads((OUT/'audit.json').read_text())
d=pd.read_csv(OUT/'daily_coverage.csv',parse_dates=['date'])
t=d[d.date.between('2025-01-02','2025-02-28')]
b=s['sources']['history']; w=s['weather']; m=w['metadata']
report=f'''# Town Q data audit — current daily weather

## Fixed validation period

January 2–February 28, 2025, inclusive: **58 days**. The customer population is confirmed. Bills use inclusive endpoints and m3; station timestamps are local. No additional bills are expected. Matching source weather date labels to local station dates is an explicitly accepted approximation; the new export uses {m['timezone']} daily summaries. No hourly integration or timezone resampling is performed.

## Weather input

The current file contains **{w['rows']} daily rows**, from **{w['start_date']} through {w['end_date']}**, with {w['duplicate_timestamps']} duplicate dates, {w['nondaily_steps']} non-daily steps, and {w['missing_values']} missing cells.

- Daily mean apparent temperature, in Celsius, is used directly.
- Daily maximum wind speed, in km/h, is retained and plotted as maximum wind.
- There is no air-temperature column and no mean-wind column. Neither is fabricated.
- The explicit `daily_apparent_hdd65_v1` model uses apparent-temperature heating degree days. It is a changed feature definition, not equivalent to the earlier air-temperature model. Maximum wind is not fed into a formula defined for mean wind.
- Metadata location: {m['latitude']}, {m['longitude']}, elevation {m['elevation']} m. The elevation differs from the previous 1435 m export; comparisons with old runs therefore also reflect a changed source.

## Target readiness

| Measure | Result |
|---|---:|
| Complete daily weather labels | {int(t.weather_valid.sum())} / {len(t)} |
| Positive TBS days | {int(t.tbs_valid.sum())} / {len(t)} |
| Minimum raw daily customer coverage | {t.history_coverage.min():.2%} |
| Average raw daily customer coverage | {t.history_coverage.mean():.2%} |
| Minimum daily coverage after excluding bills outside weather dates | {t.history_weather_bounded_coverage.min():.2%} |
| Average daily coverage after that exclusion | {t.history_weather_bounded_coverage.mean():.2%} |
| Mean daily TBS volume | {t.tbs_m3.mean():,.2f} m3 |
| Mean apparent temperature | {t.apparent_temperature_c.mean():.2f} C |
| Apparent daily mean temperature range | {t.apparent_temperature_c.min():.2f} to {t.apparent_temperature_c.max():.2f} C |

The default run preserves original bill totals and excludes bills extending beyond available weather dates (`bill_boundary_policy=exclude`, `bill_window=weather`). The new file covers all target dates, but not every complete boundary-crossing or multi-year bill. Missing weather is not filled. Exclusion is reported explicitly by the pipeline; it changes the modeled population. TBS is not scaled or modified.

## Bill and station audit

There are {b['rows']:,} bills for {b['customers']:,} customers out of {s['roster_customers']:,} roster customers. {b['roster_without_bills']} customers have no bills; they remain in the roster denominator and are not assigned zero demand. There are {b['duplicates']} duplicate bill rows, {b['invalid_rows_after_dedup']} invalid rows after deduplication, {b['overlap_pairs']} overlap pairs, and {b['internal_gap_days']} internal gap days under inclusive endpoints. {b['zero_rows']:,} bills have zero consumption. The longest bill spans {b['duration_quantiles']['1.0']:,.0f} days.

The station file contains {s['tbs']['rows']} dates, {s['tbs']['missing_values']} missing daily values, {s['tbs']['negative_days']} negative days, and {s['tbs']['zero_days']} zero days. The April–May zero run is outside this winter target. Raw-counter extraction agrees with the prepared series within {s['tbs']['max_extraction_difference']:.2g} m3.

## Interpretation and reproducibility

Bill-total conservation and daily agreement with TBS answer different questions. Missing customers' demand share remains unknown. m3 units are confirmed, but identical base-temperature/pressure correction between bills and station Vb has not been independently established. Daily GMT summaries and local-day TBS are aligned by date as authorized, with a 3.5-hour winter boundary difference.

Run `scripts/analyze_town_data.py` then `scripts/report_town_analysis.py`. `audit.json` records source hashes and metadata; `daily_coverage.csv` contains daily evidence. Historical January–February reviews and previous weather recommendations were generated using the old hourly file and are superseded by this report. The winter search CSVs remain exploratory diagnostics; they do not change the fixed validation period.
'''
(OUT/'Town_data_analysis_report.md').write_text(report,encoding='utf-8')
print(OUT/'Town_data_analysis_report.md')
