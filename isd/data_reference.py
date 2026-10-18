"""Strict ingestion, source-row identity, quarantine ledger and frozen cohorts."""
import csv, hashlib, re
from pathlib import Path
import numpy as np
import pandas as pd
import jdatetime
COLUMNS=['SubscriptionNumber','FromDate','ToDate','Consumption','ConsumptionType','UnitCount','Capacity']
EPOCH=pd.Timestamp('1970-01-01')

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def date_ordinal(text):
    from datetime import datetime
    value=datetime.strptime(text,'%Y-%m-%d').date()
    if value.isoformat()!=text: raise ValueError('Noncanonical date')
    return (value-EPOCH.date()).days

def jalali_date(ordinal):
    from datetime import timedelta
    return jdatetime.date.fromgregorian(date=EPOCH.date()+timedelta(days=int(ordinal))).isoformat()

def calendar_check(cfg):
    start=date_ordinal(cfg.target_start); end=date_ordinal(cfg.target_end_exclusive)
    if start>=end: raise ValueError('Empty target')
    candidate=cfg.target_jalali_year_candidate
    expected_start=jdatetime.date(candidate,11,1).togregorian().isoformat()
    expected_end=jdatetime.date(candidate,12,30).togregorian().isoformat()
    if cfg.target_start!=expected_start or jalali_date(end-1)!=f'{candidate:04d}-12-30': raise ValueError('Target differs from provisional Jalali year mapping')
    return {'candidate_year':candidate,'start_gregorian':expected_start,'last_gregorian':expected_end,'days':end-start,'mapping_verified':True,'intended_year_confirmed':cfg.target_year_confirmed}

def normalize_frame(raw,source_hash='synthetic',source_file='fixture.csv',allow_sample=False,row_start=2):
    if list(raw.columns)!=COLUMNS: raise ValueError('Exact seven columns required')
    raw=raw.astype('string[pyarrow]').copy()
    if any(raw[c].str.contains('[\r\n]',regex=True).fillna(False).any() for c in COLUMNS): raise ValueError('Multiline records unsupported: physical provenance requires audit')
    df=raw.copy(); df['source_row']=np.arange(row_start,row_start+len(df),dtype=np.int64)
    df['source_file']=source_file; df['source_file_sha256']=source_hash
    df['bill_id']=pd.array([hashlib.sha256(f'{source_hash}:{r}'.encode()).hexdigest() for r in df.source_row],dtype='string[pyarrow]')
    for c in COLUMNS[1:]: df['raw_'+c]=raw[c]
    df['record_status']='accepted'; df['exclusion_reason']=pd.Series([None]*len(df),index=df.index,dtype='string[pyarrow]')
    ids=raw.SubscriptionNumber.str.fullmatch(r'\d{11}')
    if allow_sample: ids=ids | raw.SubscriptionNumber.str.fullmatch(r'CUSTOMER_[A-Za-z0-9_]+')
    invalid=~ids.fillna(False)
    for c in COLUMNS: invalid |= raw[c].isna() | (raw[c].str.strip()=='')
    for c in ['FromDate','ToDate']:
        shape=raw[c].str.fullmatch(r'\d{4}-\d{2}-\d{2}').fillna(False)
        dt=pd.to_datetime(raw[c],format='%Y-%m-%d',errors='coerce',exact=True)
        invalid |= ~shape | dt.isna()
        df['start_ordinal' if c=='FromDate' else 'inclusive_end_ordinal']=((dt-EPOCH).dt.days).astype('Int64')
    df['end_ordinal']=df.inclusive_end_ordinal+1
    df['day_count']=df.end_ordinal-df.start_ordinal
    invalid |= (df.day_count<=0).fillna(True)
    for c in COLUMNS[3:]:
        values=pd.to_numeric(raw[c],errors='coerce').astype('float64')
        invalid |= ~np.isfinite(values)
        if c=='Consumption': invalid |= values<0
        df[c]=values
    df.loc[invalid,'record_status']='rejected_invalid'; df.loc[invalid,'exclusion_reason']='invalid_field_or_interval'
    df['source_calendar']='Gregorian_operational_unconfirmed'; df['endpoint_convention']='inclusive_provisional'
    df['consumption_unit']='source_units_unknown'; df['model_group_id']='unassigned'
    return df

def audit_normalized(df,deduplicate_confirmed=False):
    """Do not resolve conflicting records from arbitrary row order."""
    df=df.copy(); raw_cols=['SubscriptionNumber']+['raw_'+c for c in COLUMNS[1:]]
    duplicates=df.duplicated(raw_cols,keep=False); duplicate_excess=df.duplicated(raw_cols,keep='first')
    duplicate_ids=set(df.loc[duplicates,'SubscriptionNumber'])
    if deduplicate_confirmed:
        df.loc[duplicate_excess,'record_status']='removed_exact_duplicate'; df.loc[duplicate_excess,'exclusion_reason']='confirmed_exact_duplicate'
        duplicate_ids=set()
    valid=df[df.record_status=='accepted']
    conflict_ids=set(); overlap_pairs=0; gap_days=0; adjacent=0
    for ident,g in valid.groupby('SubscriptionNumber',sort=False):
        intervals=sorted(zip(g.start_ordinal.astype(int),g.end_ordinal.astype(int)))
        active=[]; end=None
        for a,b in intervals:
            active=[e for e in active if e>a]
            overlap_pairs+=len(active)
            if active: conflict_ids.add(ident)
            active.append(b)
            if end is not None:
                if a>end: gap_days+=a-end
                elif a==end: adjacent+=1
            end=max(end,b) if end is not None else b
    invalid_customers=set(df.loc[df.record_status=='rejected_invalid','SubscriptionNumber'].dropna())
    quarantine=conflict_ids|duplicate_ids|invalid_customers
    quarantined=(df.SubscriptionNumber.isin(quarantine)) & (df.record_status=='accepted')
    df.loc[quarantined,'record_status']='quarantined_customer'; df.loc[quarantined,'exclusion_reason']='rejected_conflict'
    counts=df.record_status.value_counts().to_dict(); volumes={k:float(v.Consumption[np.isfinite(v.Consumption)].sum()) for k,v in df.groupby('record_status')}
    audit={'rows':len(df),'customers':int(df.SubscriptionNumber.nunique()),'record_status_counts':counts,'volume_ledger_source_units':volumes,'quarantined_customers':len(quarantine),'exact_duplicate_excess_rows':int(duplicate_excess.sum()),'duplicate_confirmation':deduplicate_confirmed,'same_customer_overlap_pairs':overlap_pairs,'internal_gap_days_before_quarantine':gap_days,'adjacent_pairs':adjacent,'zero_bill_rows':int((df.Consumption==0).sum()),'negative_rows':int((df.Consumption<0).sum()),'invalid_rows':int((df.record_status=='rejected_invalid').sum())}
    assert sum(counts.values())==len(df)
    return df,audit

def read_bills(path,cfg,allow_sample=False):
    path=Path(path); digest=sha256(path)
    with path.open(encoding='utf-8-sig',newline='') as f:
        if next(csv.reader(f))!=COLUMNS: raise ValueError('Unexpected bill header')
    frames=[]; row=2
    for raw in pd.read_csv(path,encoding='utf-8-sig',dtype='string[pyarrow]',keep_default_na=False,chunksize=cfg.ingestion_chunk_size,on_bad_lines='error'):
        frame=normalize_frame(raw,digest,path.name,allow_sample,row); row+=len(frame); frames.append(frame)
    return audit_normalized(pd.concat(frames,ignore_index=True))

def coverage_classes(df,start,end):
    result={ident:('none',0) for ident in df.SubscriptionNumber.dropna().unique()}
    for ident,g in df[df.record_status=='accepted'].groupby('SubscriptionNumber',sort=False):
        span=[]
        for a,b in zip(g.start_ordinal.astype(int),g.end_ordinal.astype(int)):
            a,b=max(a,start),min(b,end)
            if a<b: span.append((a,b))
        days=0; prev=None
        for a,b in sorted(span):
            if prev is None or a>prev: days+=b-a; prev=b
            elif b>prev: days+=b-prev; prev=b
        result[ident]=('full' if days==end-start else 'partial' if days else 'none',days)
    return result

def hash_sample(identifiers,count,seed):
    order=sorted(identifiers,key=lambda x:(hashlib.sha256((seed+str(x)).encode()).hexdigest(),str(x)))
    return order if count is None else order[:count]

def prepare_state(bills,origin,n_days):
    from .solver import State
    starts=bills.start_ordinal.to_numpy(dtype=np.int64)-origin; lengths=bills.day_count.to_numpy(dtype=np.int64)
    offsets=np.concatenate(([0],np.cumsum(lengths,dtype=np.int64)))
    return State(starts,lengths,bills.Consumption.to_numpy(dtype=np.float64),offsets,n_days,hashlib.sha256("|".join(bills.bill_id.astype(str)).encode()).hexdigest()).validate()
