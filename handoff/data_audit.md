# Local data audit and algorithm handoff

No ISD solver implemented. Raw inputs are unchanged. Detailed machine-readable counts, distributions, hashes and schemas are in `data_schema.json`.

## Measured target coverage and pilot comparison

| Full-file category | Customers | Covered customer-days | Uncovered customer-days |
| --- | ---: | ---: | ---: |
| fully covered | 143,859 | 8,631,540 | 0 |
| partially covered | 218,564 | 9,360,075 | 3,753,765 |
| uncovered | 237 | 0 | 14,220 |

Pilot is an exact ordered prefix: True; contains all full bills for its selected customers: True. It has 10,000 rows, not 10,000 customers.

| Row metric | Full file | Pilot |
| --- | ---: | ---: |
| Zero consumption | 4.22% | 1.63% |
| UnitCount=1 | 76.22% | 60.90% |
| Capacity=6 | 79.40% | 76.17% |

These observed distribution differences do not establish the source of selection bias, but reinforce that the pilot is not proven representative.

Observed numeric types: all Consumption, ConsumptionType, UnitCount and Capacity values parse as finite integers in both source files (fractional counts recorded in JSON). IDs are 11-digit strings. Weather values are finite decimal numbers.

## Files and provenance

Project inspection: only `data/` was present; no Git directory, project files or AGENTS.md found in project or D:/work and D:/ parent directories. No GitHub connection used. A defensive .gitignore was added for future initialization.

- `An Iterative Shifting Disaggregation Algorithm .pdf`: PDF, 7,039,897 bytes; encoding None; CRLF newlines. SHA-256: `da4804937e984877a257dee8b4affefa9670989d351d236bbdcd253b011792d5`.
- `bill_1403.csv`: CSV text, 23,722,904 bytes; encoding utf-8-sig; CRLF newlines. SHA-256: `a40d065cf7bf0168c34443912318ad5f51e07b8af99a77c351191cbbe828f29d`.
- `bill_1403_top_10000.csv`: CSV text, 463,112 bytes; encoding utf-8-sig; CRLF newlines. SHA-256: `a2da3a4deb7771a2e5bf8e3801e0e1afe5af739a78cbfb70769edbc12ff654b1`.
- `open-meteo-34.41N50.49E1435m.csv`: CSV text, 88,353 bytes; encoding utf-8; LF newlines. SHA-256: `6c56d838b470e1255332b1ec0e39c48280bbfe27e0c7b0d8df65582cc1894533`.

Bill CSVs: comma delimiter, UTF-8 BOM, CRLF, one header row, no metadata rows. Customer IDs read as strings. Dates strictly parsed as `%Y-%m-%d`; filenames containing 1403 do not change the observed date format. Columns: SubscriptionNumber, FromDate, ToDate, Consumption, ConsumptionType, UnitCount, Capacity. Numeric ranges and code frequencies are in schema. Consumption units, Capacity meaning/units, UnitCount meaning and code 40 label are unknown.

## Bill audit

### bill_1403.csv

Rows: 513,921; distinct customers: 362,660; bills/customer distribution: `{1: 211656, 2: 150750, 3: 251, 4: 3}`.
FromDate range: ['2025-01-02', '2025-04-29']; ToDate range: ['2025-01-03', '2025-04-29'].
Missing/whitespace fields: `{'SubscriptionNumber': 0, 'FromDate': 0, 'ToDate': 0, 'Consumption': 0, 'ConsumptionType': 0, 'UnitCount': 0, 'Capacity': 0}`. Numeric parse failures: `{'Consumption': 0, 'ConsumptionType': 0, 'UnitCount': 0, 'Capacity': 0}`. Non-digit ID rows: 0; ID lengths: `{11: 513921}`.
Zero consumption: 21,705; negative: 0; exact duplicate excess rows: 0 (0 groups); conflicting customer/interval keys: 0; invalid dates/intervals: 0.
Same-customer overlap pairs: 0, involving 0 customers. Internal gap union-days: 0, involving 0 customers. Pairwise overlap-days: 0 (can double-count days).
Customers with changing attributes: `{'ConsumptionType': 0, 'UnitCount': 0, 'Capacity': 0}`.
Adjacent distinct intervals, next start minus previous end in days: `{'1': 151261}`.

Target 2025-01-20 through 2025-03-20: 60 inclusive days. Inclusive-assumption customer counts: `{'fully_covered': 143859, 'partially_covered': 218564, 'uncovered': 237}`; covered customer-days: 17,991,615; uncovered customer-days: 3,767,985 / 21,759,600 potential.
Endpoint sensitivity, [FromDate, ToDate): `{'customers': {'partially_covered': 352477, 'fully_covered': 9939, 'uncovered': 244}, 'covered_customer_days': 17736019, 'uncovered_customer_days': 4023581}`.

### bill_1403_top_10000.csv

Rows: 10,000; distinct customers: 7,181; bills/customer distribution: `{1: 4367, 2: 2809, 3: 5}`.
FromDate range: ['2025-01-02', '2025-04-09']; ToDate range: ['2025-01-29', '2025-04-29'].
Missing/whitespace fields: `{'SubscriptionNumber': 0, 'FromDate': 0, 'ToDate': 0, 'Consumption': 0, 'ConsumptionType': 0, 'UnitCount': 0, 'Capacity': 0}`. Numeric parse failures: `{'Consumption': 0, 'ConsumptionType': 0, 'UnitCount': 0, 'Capacity': 0}`. Non-digit ID rows: 0; ID lengths: `{11: 10000}`.
Zero consumption: 163; negative: 0; exact duplicate excess rows: 0 (0 groups); conflicting customer/interval keys: 0; invalid dates/intervals: 0.
Same-customer overlap pairs: 0, involving 0 customers. Internal gap union-days: 0, involving 0 customers. Pairwise overlap-days: 0 (can double-count days).
Customers with changing attributes: `{'ConsumptionType': 0, 'UnitCount': 0, 'Capacity': 0}`.
Adjacent distinct intervals, next start minus previous end in days: `{'1': 2819}`.

Target 2025-01-20 through 2025-03-20: 60 inclusive days. Inclusive-assumption customer counts: `{'fully_covered': 2660, 'partially_covered': 4518, 'uncovered': 3}`; covered customer-days: 352,357; uncovered customer-days: 78,503 / 430,860 potential.
Endpoint sensitivity, [FromDate, ToDate): `{'customers': {'partially_covered': 6970, 'fully_covered': 207, 'uncovered': 4}, 'covered_customer_days': 347532, 'uncovered_customer_days': 83328}`.

## Endpoint interpretation and coverage

A next-start minus previous-end difference of +1 supports inclusive calendar endpoints: adjacent bills cover consecutive days without gaps. It is evidence, not confirmation of the utility convention. A difference of 0 would share one day under inclusive endpoints. Coverage uses interval unions so duplicates/overlaps never inflate customer-days; ambiguous records remain unchanged. Internal gaps exclude unknown periods outside the observed customer span. Coverage is provisional and is not solver eligibility.

## Pilot selection

{
  "pilot_is_exact_first_n_full_rows": true,
  "pilot_row_count": 10000,
  "pilot_customer_count": 7181,
  "full_customer_count": 362660,
  "full_ids_nondecreasing_lexicographic": true,
  "pilot_ids_nondecreasing_lexicographic": true,
  "pilot_contains_all_full_bills_for_its_customers": true
}

The smaller file must not be described as random or representative. Exact-prefix status and ID ordering are measured above. An ordered prefix can favor earlier customer identifiers, service/geographic allocation or enrollment cohorts; the meaning of ID order has not been established. Compare category distributions and coverage in the two audits before choosing a pilot.

## Weather

Weather has two metadata rows, a blank separator, and the true header on line 4. Encoding is UTF-8 (strict decode); comma delimiter. Metadata: {"latitude": "34.411247", "longitude": "50.490566", "elevation": "1435.0", "utc_offset_seconds": "0", "timezone": "GMT", "timezone_abbreviation": "GMT"}.
Units from headers: temperature_2m and apparent_temperature in degrees Celsius; wind_speed_10m in km/h. Coordinates/elevation describe a single weather point; customer geographic suitability is unconfirmed.
Hourly rows: 2,880; UTC range: ['2025-01-01T00:00:00+00:00', '2025-04-30T23:00:00+00:00']; Tehran timestamp range: ['2025-01-01T03:30:00+03:30', '2025-05-01T02:30:00+03:30']. Duplicate excess timestamps: 0; internal missing hours: 0; invalid timestamps: 0; numeric missing/invalid: {'temperature_2m (°C)': 0, 'apparent_temperature (°C)': 0, 'wind_speed_10m (km/h)': 0}.

Required weather is based on entire valid bill intervals, including parts outside the target. The following are conservative date envelopes; see the exact absent timestamps in JSON. For bills intersecting the target, use their full intervals, not clipped target dates.

- all_bill_interval_requirement: local dates ['2025-01-02', '2025-04-29']; hourly UTC point brackets ['2025-01-01T20:00:00+00:00', '2025-04-29T21:00:00+00:00']; absent required points 0; timestamp-complete local days 118; incomplete local dates [].

- target_intersecting_bill_requirement: local dates ['2025-01-02', '2025-04-29']; hourly UTC point brackets ['2025-01-01T20:00:00+00:00', '2025-04-29T21:00:00+00:00']; absent required points 0; timestamp-complete local days 118; incomplete local dates [].

- target_only_requirement: local dates ['2025-01-20', '2025-03-20']; hourly UTC point brackets ['2025-01-19T20:00:00+00:00', '2025-03-20T21:00:00+00:00']; absent required points 0; timestamp-complete local days 60; incomplete local dates [].

Daily feature formation (proposed; not executed): parse naive timestamps explicitly, attach UTC based on metadata, then convert with ZoneInfo("Asia/Tehran"). Define each day by local midnight to next midnight. In this 2025 period Tehran is UTC+03:30, so UTC 20:00 and 21:00 bracket local midnight at UTC 20:30. For point-valued temperature/apparent-temperature/wind observations, linearly interpolate boundary values and time-integrate each feature over the local day, dividing by its 24-hour duration. Daily min/max are extrema of that interpolated curve; retain completeness flags and hour/segment counts. Do not average UTC-date groups or simply group shifted 24 hourly labels: midnight splits hourly segments. If provider variables are hourly period averages rather than points, use overlap-duration weighting instead; confirm semantics before implementation. Do not fill missing boundary values silently. Heating-degree features require a separately confirmed base temperature and formula.

## Execution environment

{
  "python_executable": "C:\\Users\\Masoud\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe",
  "python_version": "3.12.14 (main, Aug 25 2026, 14:01:42) [MSC v.1944 64 bit (AMD64)]",
  "platform": "Windows-11-10.0.26200-SP0",
  "hardware": [
    {
      "TotalPhysicalMemory": 16780775424,
      "NumberOfLogicalProcessors": 12
    },
    {
      "Name": "Intel(R) Core(TM) 5 210H",
      "NumberOfCores": 8,
      "NumberOfLogicalProcessors": 12
    },
    {
      "Caption": "Microsoft Windows 11 Home",
      "FreePhysicalMemory": 3408480
    }
  ],
  "memory_guidance": "Audit uses string records and interval unions; avoid a dense customer-by-day matrix. A 362660 x 60 float64 array alone needs 174076800 bytes; Python objects and full-interval arrays add overhead. Free memory is a snapshot."
}

The reusable audit uses the Python standard library plus tzdata on Windows; pypdf is optional for reference metadata. No pandas dependency is required. Runtime complexity is dominated by reading rows and sorting each customer history; no dense solver matrix is allocated. Machine free RAM is a snapshot. The PATH python entry was a WindowsApps alias, while the bundled Python was actually executed.

## Reproduction and privacy

From the project root run `python scripts/audit_data.py --root D:\work\repo` with Python 3.9+ and IANA timezone data (Windows may need `tzdata`); optional `pypdf` enables PDF metadata. The bundled interpreter path is recorded in JSON. Script is packaged under scripts/ in the ZIP. The ZIP contains only these handoff files and the audit script; no raw customer file, PDF, environments, caches or credentials. Small bill sample preserves complete histories for up to ten deliberately selected customers and replaces IDs without exporting a mapping; dates and attributes remain quasi-identifiers. Weather sample preserves source metadata and boundary pairs, with intentionally omitted middle periods.
