import argparse, csv, hashlib, io, json, platform, sys, subprocess, zipfile
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TARGET_START = date(2025, 1, 20)
TARGET_END = date(2025, 3, 20)
DAY = timedelta(days=1)
COLUMNS = ['SubscriptionNumber','FromDate','ToDate','Consumption','ConsumptionType','UnitCount','Capacity']

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

@lru_cache(maxsize=4096)
def explicit_date(s):
    d=datetime.strptime(s,'%Y-%m-%d').date()
    if d.isoformat()!=s: raise ValueError('Noncanonical date')
    return d

def file_info(p):
    b=p.read_bytes()
    encoding='utf-8-sig' if b.startswith(b'\xef\xbb\xbf') else 'utf-8'
    if p.suffix.lower()=='.csv': b.decode(encoding,errors='strict')
    return {'filename':p.name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(), 'magic_hex':b[:16].hex(), 'format':'PDF' if b.startswith(b'%PDF-') else 'CSV text','encoding':encoding if p.suffix.lower()=='.csv' else None,'newline':'CRLF' if b'\r\n' in b else 'LF'}

def union_days(intervals,lo,hi,exclusive=False):
    segments=[]
    for a,b in intervals:
        if exclusive: b-=DAY
        a,b=max(a,lo),min(b,hi)
        if a<=b: segments.append((a,b))
    total=0; end=None
    for a,b in sorted(segments):
        if end is None or a>end+DAY: total+=(b-a).days+1; end=b
        elif b>end: total+=(b-end).days; end=b
    return total

def audit_bills(p):
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); headers=reader.fieldnames; rows=list(reader)
    if headers!=COLUMNS or any(None in r or None in r.values() for r in rows): raise ValueError('Unexpected CSV shape')
    missing={c:sum(not r[c].strip() for r in rows) for c in headers}
    groups=defaultdict(list); exact=Counter(); keys=defaultdict(set); values={c:Counter() for c in headers[3:]}
    numeric_fractional=Counter(); numeric_invalid=Counter(); numeric_min={}; numeric_max={}; invalid=[]; starts=[]; ends=[]
    zero=negative=0; id_lengths=Counter(); id_non_digits=0
    for idx,r in enumerate(rows,2):
        ident=r['SubscriptionNumber']; groups[ident].append((idx,r)); id_lengths[len(ident)]+=1; id_non_digits+=not ident.isdigit()
        exact[tuple(r[c] for c in headers)]+=1
        keys[(ident,r['FromDate'],r['ToDate'])].add(tuple(r[c] for c in headers[3:]))
        for c in headers[3:]:
            values[c][r[c]]+=1
            try:
                from decimal import Decimal
                n=Decimal(r[c]); assert n.is_finite(); numeric_fractional[c]+=n!=n.to_integral_value()
                numeric_min[c]=min(n,numeric_min.get(c,n)); numeric_max[c]=max(n,numeric_max.get(c,n))
                if c=='Consumption': zero+=n==0; negative+=n<0
            except Exception: numeric_invalid[c]+=1
        try:
            a=explicit_date(r['FromDate']); b=explicit_date(r['ToDate']); starts.append(a); ends.append(b)
            if a>b: invalid.append((idx,'reversed interval'))
        except ValueError: invalid.append((idx,'invalid date'))
    distribution=Counter(len(v) for v in groups.values()); coverage=Counter(); exclusive_coverage=Counter(); covered=exclusive_covered=0
    target_days=(TARGET_END-TARGET_START).days+1; coverage_days=Counter(); uncovered_days_by_class=Counter()
    adj=Counter(); overlap_pairs=overlap_days=gap_days=0; overlap_customers=set(); gap_customers=set(); attribute_changes=Counter(); durations=Counter(); selected={}; min_dates=[]; max_dates=[]
    for ident,items in groups.items():
        ints=[]
        for idx,r in items:
            try:
                a=explicit_date(r['FromDate']); b=explicit_date(r['ToDate'])
                if a<=b: ints.append((a,b,idx,r)); durations[(b-a).days+1]+=1
            except ValueError: pass
        ints.sort(key=lambda x:(x[0],x[1],x[2]))
        pairs=[(a,b) for a,b,_,_ in ints]
        n=union_days(pairs,TARGET_START,TARGET_END); covered+=n
        label='fully_covered' if n==target_days else 'partially_covered' if n else 'uncovered'; coverage[label]+=1; coverage_days[label]+=n; uncovered_days_by_class[label]+=target_days-n
        ne=union_days(pairs,TARGET_START,TARGET_END,True); exclusive_covered+=ne; exclusive_coverage['fully_covered' if ne==target_days else 'partially_covered' if ne else 'uncovered']+=1
        if label not in selected: selected[label]=ident
        active=[]
        for a,b,idx,r in ints:
            active=[x for x in active if x[1]>=a]
            for aa,bb,_,_ in active:
                overlap_pairs+=1; overlap_days+=(min(b,bb)-a).days+1; overlap_customers.add(ident)
            active.append((a,b,idx,r))
        unique=sorted(set(pairs)); running_end=None
        for a,b in unique:
            if running_end is not None and a>running_end+DAY:
                gap_customers.add(ident); gap_days+=(a-running_end).days-1
            running_end=max(b,running_end) if running_end else b
        for prev,nxt in zip(unique,unique[1:]):
            delta=(nxt[0]-prev[1]).days
            adj[str(delta)]+=1
        for c in ['ConsumptionType','UnitCount','Capacity']:
            attribute_changes[c]+=len(set(r[c] for _,r in items))>1
        if ints: min_dates.append(ints[0][0]); max_dates.append(max(x[1] for x in ints))
        if ident in overlap_customers and 'overlap' not in selected: selected['overlap']=ident
        if ident in gap_customers and 'gap' not in selected: selected['gap']=ident
        if any(r['Consumption']=='0' for _,r in items) and 'zero' not in selected: selected['zero']=ident
        if any(r['Consumption'].startswith('-') for _,r in items) and 'negative' not in selected: selected['negative']=ident
    result={'row_count':len(rows),'distinct_customers':len(groups),'headers':headers,'missing_or_whitespace':missing,'numeric_parse_failures':{c:numeric_invalid[c] for c in headers[3:]},'fractional_numeric_rows':{c:numeric_fractional[c] for c in headers[3:]},'numeric_ranges':{c:{'min':str(numeric_min[c]),'max':str(numeric_max[c])} for c in numeric_min},'observed_values':{c:dict(values[c]) for c in ['ConsumptionType','UnitCount','Capacity']},'customer_id_length_counts':dict(id_lengths),'non_digit_id_rows':id_non_digits,'bills_per_customer':dict(sorted(distribution.items())),'from_date_range':[str(min(starts)),str(max(starts))],'to_date_range':[str(min(ends)),str(max(ends))],'zero_consumption_rows':zero,'negative_consumption_rows':negative,'exact_duplicate_excess_rows':sum(n-1 for n in exact.values()),'exact_duplicate_groups':sum(n>1 for n in exact.values()),'conflicting_customer_interval_keys':sum(len(v)>1 for v in keys.values()),'invalid_interval_rows':len(invalid),'invalid_interval_reasons':dict(Counter(reason for _,reason in invalid)),'inclusive_duration_days_counts':dict(sorted(durations.items())),'same_customer_overlap_pairs_including_duplicate_rows':overlap_pairs,'pairwise_overlap_days_not_union':overlap_days,'overlap_customers':len(overlap_customers),'internal_union_gap_days':gap_days,'gap_customers':len(gap_customers),'adjacent_distinct_interval_start_minus_previous_end_days':dict(sorted(adj.items(),key=lambda x:int(x[0]))),'customers_with_attribute_changes':dict(attribute_changes),'target':{'start':str(TARGET_START),'end':str(TARGET_END),'days_per_customer':target_days,'inclusive_endpoint_assumption':{'customers':{k:coverage[k] for k in ['fully_covered','partially_covered','uncovered']},'covered_customer_days_by_class':{k:coverage_days[k] for k in ['fully_covered','partially_covered','uncovered']},'uncovered_customer_days_by_class':{k:uncovered_days_by_class[k] for k in ['fully_covered','partially_covered','uncovered']},'covered_customer_days':covered,'uncovered_customer_days':target_days*len(groups)-covered,'potential_customer_days':target_days*len(groups)},'alternative_from_inclusive_to_exclusive':{'customers':dict(exclusive_coverage),'covered_customer_days':exclusive_covered,'uncovered_customer_days':target_days*len(groups)-exclusive_covered}}}
    return result,rows,groups,selected

def machine():
    command="Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory,NumberOfLogicalProcessors | ConvertTo-Json -Compress; Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress; Get-CimInstance Win32_OperatingSystem | Select-Object Caption,FreePhysicalMemory | ConvertTo-Json -Compress"
    try:
        out=subprocess.check_output(['powershell','-NoProfile','-Command',command],text=True)
        hardware=[json.loads(x) for x in out.splitlines() if x.strip()]
    except Exception as e: hardware={'unavailable':str(e)}
    return {'python_executable':sys.executable,'python_version':sys.version,'platform':platform.platform(),'hardware':hardware,'memory_guidance':'Audit uses string records and interval unions; avoid a dense customer-by-day matrix. A 362660 x 60 float64 array alone needs 174076800 bytes; Python objects and full-interval arrays add overhead. Free memory is a snapshot.'}

def weather(p,full_rows):
    lines=p.read_text(encoding='utf-8-sig').splitlines(); metadata=dict(zip(next(csv.reader([lines[0]])),next(csv.reader([lines[1]]))))
    if metadata.get('timezone')!='GMT' or metadata.get('utc_offset_seconds')!='0': raise ValueError('Weather timezone metadata changed; do not assume UTC')
    records=list(csv.DictReader(io.StringIO('\n'.join(lines[3:])))); header=list(records[0]); timestamps=[]; invalid=0; missing=Counter(); duplicates=Counter()
    for r in records:
        try:
            t=datetime.strptime(r['time'],'%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc)
            if t.strftime('%Y-%m-%dT%H:%M')!=r['time']: raise ValueError()
            timestamps.append(t); duplicates[t]+=1
        except ValueError: invalid+=1
        for c in header[1:]:
            try: assert __import__('math').isfinite(float(r[c]))
            except Exception: missing[c]+=1
    unique=sorted(set(timestamps)); missing_hours=[]; offgrid=0
    for a,b in zip(unique,unique[1:]):
        delta=int((b-a).total_seconds()); offgrid+=delta%3600!=0
        t=a+timedelta(hours=1)
        while t<b: missing_hours.append(t.isoformat()); t+=timedelta(hours=1)
    intervals=[]; touching=[]
    for r in full_rows:
        try:
            a=explicit_date(r['FromDate']); b=explicit_date(r['ToDate'])
            if a<=b:
                intervals.append((a,b))
                if a<=TARGET_END and b>=TARGET_START: touching.append((a,b))
        except ValueError: pass
    tz=ZoneInfo('Asia/Tehran'); available=set(unique)
    def requirement(ints):
        lo=min(a for a,b in ints); hi=max(b for a,b in ints)
        start=datetime.combine(lo,datetime.min.time(),tz).astimezone(timezone.utc)
        end=datetime.combine(hi+DAY,datetime.min.time(),tz).astimezone(timezone.utc)
        # Linear interpolation needs both bracketing hourly point observations.
        first=start.replace(minute=0,second=0,microsecond=0)
        last=end.replace(minute=0,second=0,microsecond=0)+(timedelta(hours=1) if end.minute else timedelta())
        t=first; absent=[]; required=0
        while t<=last:
            required+=1
            if t not in available: absent.append(t.isoformat())
            t+=timedelta(hours=1)
        complete=0; incomplete=[]
        d=lo
        while d<=hi:
            s=datetime.combine(d,datetime.min.time(),tz).astimezone(timezone.utc); e=s+DAY
            f=s.replace(minute=0); l=e.replace(minute=0)+timedelta(hours=1)
            t=f; ok=True
            while t<=l:
                if t not in available: ok=False
                t+=timedelta(hours=1)
            if ok: complete+=1
            else: incomplete.append(str(d))
            d+=DAY
        return {'local_date_envelope':[str(lo),str(hi)],'local_day_boundary_utc':[start.isoformat(),end.isoformat()],'required_hourly_point_brackets_utc':[first.isoformat(),last.isoformat()],'required_hourly_points_envelope':required,'absent_required_hourly_points':len(absent),'absent_required_timestamps_utc':absent,'complete_local_days_by_timestamps':complete,'incomplete_local_dates_by_timestamps':incomplete,'note':'Envelope includes dates between bills; point-bracket convention is provisional pending observation aggregation semantics.'}
    result={'metadata':metadata,'metadata_rows':2,'blank_separator_rows':1,'header_line_1_based':4,'headers':header,'column_types':{header[0]:'naive ISO datetime, explicitly interpreted as UTC',**{c:'finite decimal numeric' for c in header[1:]}},'units':{header[1]:'degrees Celsius',header[2]:'degrees Celsius',header[3]:'km/h'},'timestamps_strictly_increasing_in_source_order':all(a<b for a,b in zip(timestamps,timestamps[1:])),'timestamps_on_hour':all(t.minute==0 for t in timestamps),'row_count':len(records),'time_parse_failures':invalid,'timestamp_assumption':'GMT metadata and zero utc_offset_seconds imply UTC; timestamps carry no explicit offset','utc_range':[unique[0].isoformat(),unique[-1].isoformat()],'local_timestamp_range':[unique[0].astimezone(tz).isoformat(),unique[-1].astimezone(tz).isoformat()],'duplicate_timestamp_excess_rows':sum(n-1 for n in duplicates.values()),'missing_internal_hours_count':len(missing_hours),'missing_internal_hours_utc':missing_hours,'non_hourly_step_pairs':offgrid,'missing_or_invalid_numeric_values':{c:missing[c] for c in header[1:]},'all_bill_interval_requirement':requirement(intervals),'target_intersecting_bill_requirement':requirement(touching),'target_only_requirement':requirement([(TARGET_START,TARGET_END)])}
    # Preserve metadata verbatim and complete pairs bracketing UTC/local boundaries.
    chosen=set(range(min(6,len(records))))|set(range(max(0,len(records)-6),len(records)))
    for i,t in enumerate(timestamps):
        if t.date() in [date(2025,1,19),date(2025,3,20)] and t.hour in [19,20,21,22,23]: chosen.add(i)
    sample='\n'.join(lines[:4]+[lines[i+4] for i in sorted(chosen)])+'\n'
    return result,sample

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); args=parser.parse_args(); root=args.root.resolve(); data=root/'data'; out=root/'handoff'; out.mkdir(exist_ok=True)
    files=sorted(data.iterdir()); bill_paths=sorted(data.glob('bill_1403*.csv'))
    if len(bill_paths)!=2: raise ValueError('Expected two bill CSV files')
    all_stats={}; content={}; grouped={}; selections={}
    before={p.name:digest(p) for p in files if p.is_file()}
    for p in bill_paths:
        print('Auditing',p.name,flush=True); stats,rows,groups,selected=audit_bills(p); all_stats[p.name]=stats; content[p.name]=rows; grouped[p.name]=groups; selections[p.name]=selected
    full=content['bill_1403.csv']; pilot=content['bill_1403_top_10000.csv']; full_ids=[r['SubscriptionNumber'] for r in full]; pilot_ids=[r['SubscriptionNumber'] for r in pilot]; pilot_id_set=set(pilot_ids)
    comparison={'pilot_is_exact_first_n_full_rows':pilot==full[:len(pilot)],'pilot_row_count':len(pilot),'pilot_customer_count':len(set(pilot_ids)),'full_customer_count':len(set(full_ids)),'full_ids_nondecreasing_lexicographic':all(a<=b for a,b in zip(full_ids,full_ids[1:])),'pilot_ids_nondecreasing_lexicographic':all(a<=b for a,b in zip(pilot_ids,pilot_ids[1:])),'pilot_contains_all_full_bills_for_its_customers':sum(1 for r in full if r['SubscriptionNumber'] in pilot_id_set)==len(pilot)}
    wp=next(data.glob('open-meteo*.csv')); weather_stats,weather_sample=weather(wp,full)
    pdf=next(data.glob('An Iterative Shifting Disaggregation*.pdf'))
    try:
        from pypdf import PdfReader
        reader=PdfReader(pdf); pdf_stats={'pages':len(reader.pages),'metadata':{str(k):str(v) for k,v in reader.metadata.items()},'first_page_title':reader.metadata.title,'scope':'Reference identity/metadata inspected. Solver and paper implementation not audited.'}
    except ImportError: pdf_stats={'note':'Install pypdf to inspect PDF metadata; no solver implementation.'}
    schema={'audit_version':1,'files':[file_info(p) for p in files if p.is_file()],'bill_schema':{'delimiter':',','quotechar':'"','metadata_rows':0,'header_line_1_based':1,'encoding':'UTF-8 with BOM','columns':{'SubscriptionNumber':{'storage':'string','semantic':'customer ID; retain leading zeroes; do not numeric-coerce'},'FromDate':{'storage':'date','format':'%Y-%m-%d','calendar':'Gregorian observed format; source confirmation requested','endpoint':'provisionally inclusive'},'ToDate':{'storage':'date','format':'%Y-%m-%d','endpoint':'provisionally inclusive'},'Consumption':{'storage':'decimal numeric','unit':None,'semantic':'bill total, interpretation unconfirmed'},'ConsumptionType':{'storage':'string code','label':None},'UnitCount':{'storage':'numeric integer as observed','semantic':None},'Capacity':{'storage':'numeric as observed','unit':None,'semantic':None}}},'bill_audits':all_stats,'pilot_comparison':comparison,'weather':weather_stats,'pdf':pdf_stats,'machine':machine(),'raw_data_mutated':False,'assumptions':['Inclusive bill endpoints remain provisional.','Target coverage is union of valid intervals; it does not establish consumption validity or solver eligibility.','All observed customer IDs, including invalid-record-only customers, form coverage denominator.','Gaps are internal uncovered calendar days between valid interval unions; no missing bills inferred beyond each customer observed span.','Exact duplicates and overlap pairs are reported before any correction; no records removed.','Conflicts use (customer, FromDate, ToDate) with differing remaining columns.']}
    (out/'data_schema.json').write_text(json.dumps(schema,indent=2,ensure_ascii=False),encoding='utf-8')
    # Select full histories for a few deliberately chosen examples; no reversible ID mapping exported.
    chosen=list(dict.fromkeys(list(selections['bill_1403.csv'].values())+full_ids[:6]))[:10]
    pseudo={ident:f'CUSTOMER_{i+1:03d}' for i,ident in enumerate(chosen)}
    with (out/'bill_sample_pseudonymized.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=COLUMNS); w.writeheader()
        for r in full:
            if r['SubscriptionNumber'] in pseudo: w.writerow({**r,'SubscriptionNumber':pseudo[r['SubscriptionNumber']]})
    (out/'weather_sample.csv').write_text(weather_sample,encoding='utf-8')
    notes={'bill_sample':'Deliberate small example selection: first encountered full/partial/uncovered/overlap/gap/zero/negative customers when present, plus initial customers up to ten. All rows for selected customers preserved in original order; only SubscriptionNumber replaced. No original ID mapping included. Dates and other quasi-identifiers remain; pseudonymized, not guaranteed anonymous. Not a representative sample.','weather_sample':'Verbatim metadata and headers; first/last six rows and 19:00-23:00 UTC around target start/end boundaries. Intentionally discontinuous; gaps in this sample are not source missingness. GMT 20:00 and 21:00 bracket Tehran midnight at 20:30 UTC.'}
    (out/'sample_notes.json').write_text(json.dumps(notes,indent=2),encoding='utf-8')
    report=['# Local data audit and algorithm handoff','', 'No ISD solver implemented. Raw inputs are unchanged. Detailed machine-readable counts, distributions, hashes and schemas are in `data_schema.json`.','', '## Files and provenance','', 'Project inspection: only `data/` was present; no Git directory, project files or AGENTS.md found in project or D:/work and D:/ parent directories. No GitHub connection used. A defensive .gitignore was added for future initialization.','']
    for info in schema['files']: report.append(f"- `{info['filename']}`: {info['format']}, {info['bytes']:,} bytes; encoding {info['encoding']}; {info['newline']} newlines. SHA-256: `{info['sha256']}`.")
    report+=['','Bill CSVs: comma delimiter, UTF-8 BOM, CRLF, one header row, no metadata rows. Customer IDs read as strings. Dates strictly parsed as `%Y-%m-%d`; filenames containing 1403 do not change the observed date format. Columns: '+', '.join(COLUMNS)+'. Numeric ranges and code frequencies are in schema. Consumption units, Capacity meaning/units, UnitCount meaning and code 40 label are unknown.','', '## Bill audit','']
    for name,s in all_stats.items():
        report += [f'### {name}', '', f"Rows: {s['row_count']:,}; distinct customers: {s['distinct_customers']:,}; bills/customer distribution: `{s['bills_per_customer']}`.", f"FromDate range: {s['from_date_range']}; ToDate range: {s['to_date_range']}.", f"Missing/whitespace fields: `{s['missing_or_whitespace']}`. Numeric parse failures: `{s['numeric_parse_failures']}`. Non-digit ID rows: {s['non_digit_id_rows']}; ID lengths: `{s['customer_id_length_counts']}`.", f"Zero consumption: {s['zero_consumption_rows']:,}; negative: {s['negative_consumption_rows']:,}; exact duplicate excess rows: {s['exact_duplicate_excess_rows']:,} ({s['exact_duplicate_groups']} groups); conflicting customer/interval keys: {s['conflicting_customer_interval_keys']:,}; invalid dates/intervals: {s['invalid_interval_rows']:,}.", f"Same-customer overlap pairs: {s['same_customer_overlap_pairs_including_duplicate_rows']:,}, involving {s['overlap_customers']:,} customers. Internal gap union-days: {s['internal_union_gap_days']:,}, involving {s['gap_customers']:,} customers. Pairwise overlap-days: {s['pairwise_overlap_days_not_union']:,} (can double-count days).", f"Customers with changing attributes: `{s['customers_with_attribute_changes']}`.", f"Adjacent distinct intervals, next start minus previous end in days: `{s['adjacent_distinct_interval_start_minus_previous_end_days']}`.", '', f"Target {TARGET_START} through {TARGET_END}: 60 inclusive days. Inclusive-assumption customer counts: `{s['target']['inclusive_endpoint_assumption']['customers']}`; covered customer-days: {s['target']['inclusive_endpoint_assumption']['covered_customer_days']:,}; uncovered customer-days: {s['target']['inclusive_endpoint_assumption']['uncovered_customer_days']:,} / {s['target']['inclusive_endpoint_assumption']['potential_customer_days']:,} potential.", f"Endpoint sensitivity, [FromDate, ToDate): `{s['target']['alternative_from_inclusive_to_exclusive']}`.", '']
    report+=['## Endpoint interpretation and coverage','', 'A next-start minus previous-end difference of +1 supports inclusive calendar endpoints: adjacent bills cover consecutive days without gaps. It is evidence, not confirmation of the utility convention. A difference of 0 would share one day under inclusive endpoints. Coverage uses interval unions so duplicates/overlaps never inflate customer-days; ambiguous records remain unchanged. Internal gaps exclude unknown periods outside the observed customer span. Coverage is provisional and is not solver eligibility.', '', '## Pilot selection','', json.dumps(comparison,indent=2), '', 'The smaller file must not be described as random or representative. Exact-prefix status and ID ordering are measured above. An ordered prefix can favor earlier customer identifiers, service/geographic allocation or enrollment cohorts; the meaning of ID order has not been established. Compare category distributions and coverage in the two audits before choosing a pilot.', '', '## Weather','', 'Weather has two metadata rows, a blank separator, and the true header on line 4. Encoding is UTF-8 (strict decode); comma delimiter. Metadata: '+json.dumps(weather_stats['metadata'])+'.', 'Units from headers: temperature_2m and apparent_temperature in degrees Celsius; wind_speed_10m in km/h. Coordinates/elevation describe a single weather point; customer geographic suitability is unconfirmed.', f"Hourly rows: {weather_stats['row_count']:,}; UTC range: {weather_stats['utc_range']}; Tehran timestamp range: {weather_stats['local_timestamp_range']}. Duplicate excess timestamps: {weather_stats['duplicate_timestamp_excess_rows']}; internal missing hours: {weather_stats['missing_internal_hours_count']}; invalid timestamps: {weather_stats['time_parse_failures']}; numeric missing/invalid: {weather_stats['missing_or_invalid_numeric_values']}.", '', 'Required weather is based on entire valid bill intervals, including parts outside the target. The following are conservative date envelopes; see the exact absent timestamps in JSON. For bills intersecting the target, use their full intervals, not clipped target dates.']
    for key in ['all_bill_interval_requirement','target_intersecting_bill_requirement','target_only_requirement']:
        v=weather_stats[key]; report += ['',f"- {key}: local dates {v['local_date_envelope']}; hourly UTC point brackets {v['required_hourly_point_brackets_utc']}; absent required points {v['absent_required_hourly_points']}; timestamp-complete local days {v['complete_local_days_by_timestamps']}; incomplete local dates {v['incomplete_local_dates_by_timestamps']}."]
    report+=['', 'Daily feature formation (proposed; not executed): parse naive timestamps explicitly, attach UTC based on metadata, then convert with ZoneInfo("Asia/Tehran"). Define each day by local midnight to next midnight. In this 2025 period Tehran is UTC+03:30, so UTC 20:00 and 21:00 bracket local midnight at UTC 20:30. For point-valued temperature/apparent-temperature/wind observations, linearly interpolate boundary values and time-integrate each feature over the local day, dividing by its 24-hour duration. Daily min/max are extrema of that interpolated curve; retain completeness flags and hour/segment counts. Do not average UTC-date groups or simply group shifted 24 hourly labels: midnight splits hourly segments. If provider variables are hourly period averages rather than points, use overlap-duration weighting instead; confirm semantics before implementation. Do not fill missing boundary values silently. Heating-degree features require a separately confirmed base temperature and formula.', '', '## Execution environment','', json.dumps(schema['machine'],indent=2), '', 'The reusable audit uses the Python standard library plus tzdata on Windows; pypdf is optional for reference metadata. No pandas dependency is required. Runtime complexity is dominated by reading rows and sorting each customer history; no dense solver matrix is allocated. Machine free RAM is a snapshot. The PATH python entry was a WindowsApps alias, while the bundled Python was actually executed.', '', '## Reproduction and privacy','', 'From the project root run `python scripts/audit_data.py --root D:\\work\\repo` with Python 3.9+ and IANA timezone data (Windows may need `tzdata`); optional `pypdf` enables PDF metadata. The bundled interpreter path is recorded in JSON. Script is packaged under scripts/ in the ZIP. The ZIP contains only these handoff files and the audit script; no raw customer file, PDF, environments, caches or credentials. Small bill sample preserves complete histories for up to ten deliberately selected customers and replaces IDs without exporting a mapping; dates and attributes remain quasi-identifiers. Weather sample preserves source metadata and boundary pairs, with intentionally omitted middle periods.','']
    cov=all_stats['bill_1403.csv']['target']['inclusive_endpoint_assumption']
    quick=['## Measured target coverage and pilot comparison','', '| Full-file category | Customers | Covered customer-days | Uncovered customer-days |','| --- | ---: | ---: | ---: |']
    for k in ['fully_covered','partially_covered','uncovered']:
        quick.append(f"| {k.replace('_',' ')} | {cov['customers'][k]:,} | {cov['covered_customer_days_by_class'][k]:,} | {cov['uncovered_customer_days_by_class'][k]:,} |")
    quick+=['',f"Pilot is an exact ordered prefix: {comparison['pilot_is_exact_first_n_full_rows']}; contains all full bills for its selected customers: {comparison['pilot_contains_all_full_bills_for_its_customers']}. It has {len(pilot):,} rows, not 10,000 customers.",'', '| Row metric | Full file | Pilot |','| --- | ---: | ---: |']
    for label,col,val in [('Zero consumption','Consumption','0'),('UnitCount=1','UnitCount','1'),('Capacity=6','Capacity','6')]:
        rates=[sum(r[col]==val for r in rs)/len(rs)*100 for rs in [full,pilot]]
        quick.append(f"| {label} | {rates[0]:.2f}% | {rates[1]:.2f}% |")
    quick+=['','These observed distribution differences do not establish the source of selection bias, but reinforce that the pilot is not proven representative.','', 'Observed numeric types: all Consumption, ConsumptionType, UnitCount and Capacity values parse as finite integers in both source files (fractional counts recorded in JSON). IDs are 11-digit strings. Weather values are finite decimal numbers.','']
    report[4:4]=quick
    (out/'data_audit.md').write_text('\n'.join(report),encoding='utf-8')
    questions='''# Questions before solver design or data correction

1. Does the utility define FromDate and ToDate as inclusive calendar days? What do meter-reading dates mean? Adjacent +1-day evidence supports but cannot establish inclusion.
2. What are Consumption units and scaling, and does it represent a corrected bill total? Are zero bills true zero usage, vacant properties, estimated reads or missing readings?
3. What do ConsumptionType code 40, UnitCount and Capacity mean? What are Capacity units? How should time-varying customer attributes be treated?
4. For duplicate/conflicting/overlapping records, which source authority determines corrections? Do gaps represent absent bills, service breaks or extract restrictions? Audit does not correct them.
5. Is bill_1403 the intended complete population? Why was the top_10000 extract selected, and how are customer IDs allocated? An ordered prefix cannot establish a representative pilot.
6. Are the observed ISO dates Gregorian and local to Asia/Tehran? Confirm billing day boundaries and any partial-day interpretation.
7. Current weather covers the full observed bill envelope and all required UTC brackets. If additional bills extend that envelope, can weather be re-exported to cover their full intervals? Missing boundary values must not be extrapolated silently.
8. What Open-Meteo endpoint/model, retrieval time, variables and timestamp observation/aggregation semantics produced this export? Are Celsius and km/h header units accurate? Are temperatures point observations or hourly averages?
9. Is the single point near 34.411247 N, 50.490566 E, elevation 1435m suitable for all customers? No customer locations were supplied.
10. Which customers should be eligible for the 2025-01-20 to 2025-03-20 target? Should partial coverage be excluded, reported separately or supported with additional bills? Coverage is not consumption-quality eligibility.
11. Confirm heating-degree base temperature, daily aggregation convention, and policy for missing weather. No consumption-unit, type-label or Capacity assumptions have been made.

Current provisional decisions: inclusive endpoints; timezone UTC from GMT metadata then Asia/Tehran; coverage from valid interval unions; no raw records altered. Alternative end-exclusive coverage is reported for sensitivity. Solver implementation is intentionally deferred.
'''
    (out/'questions.md').write_text(questions,encoding='utf-8')
    ignore=root/'.gitignore'; entries=['/data/','/outputs/','/output/','/bulk_outputs/','/.venv/','/venv/','__pycache__/','*.py[cod]','/.cache/','/.env','/.env.*']
    existing=ignore.read_text(encoding='utf-8') if ignore.exists() else ''
    add=[x for x in entries if x not in existing.splitlines()]
    if add: ignore.write_text(existing+('\n' if existing and not existing.endswith('\n') else '')+'\n'.join(add)+'\n',encoding='utf-8')
    after={p.name:digest(p) for p in files if p.is_file()}
    if before!=after: raise RuntimeError('Raw input hashes changed')
    allow=['data_audit.md','data_schema.json','bill_sample_pseudonymized.csv','weather_sample.csv','sample_notes.json','questions.md']
    with zipfile.ZipFile(out/'data_audit_bundle.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in allow: z.write(out/name,'handoff/'+name)
        z.write(Path(__file__),'scripts/audit_data.py')
    with zipfile.ZipFile(out/'data_audit_bundle.zip') as z:
        assert z.testzip() is None
        assert len(z.namelist())==7
    print(json.dumps({'bill_audits':all_stats,'pilot_comparison':comparison,'weather':weather_stats,'zip':str(out/'data_audit_bundle.zip'),'raw_sha256_unchanged':before==after},indent=2))

if __name__=='__main__': main()


