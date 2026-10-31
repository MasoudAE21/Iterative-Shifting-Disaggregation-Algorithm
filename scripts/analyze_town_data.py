"""Read-only Town audit; write reproducible aggregate evidence to outputs/town_analysis."""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / 'data' / 'prepared'
O = ROOT / 'outputs/town_analysis'
O.mkdir(parents=True, exist_ok=True)
def read(name):
    return pd.read_csv(D/name, dtype={'SubscriptionNumber':str}, encoding='utf-8-sig')
roster = read('Customers_Town_Q.csv')
ids = sorted(roster.SubscriptionNumber.dropna().unique())
lookup = {v:i for i,v in enumerate(ids)}
import sys
sys.path.insert(0,str(ROOT))
from isd.weather import read_weather, daily_integral
weather_paths=sorted(D.glob('open-meteo*.csv'))
if len(weather_paths)!=1: raise ValueError('Expected exactly one prepared weather export')
weather_path=weather_paths[0]
x, weather_values, weather_metadata=read_weather(weather_path)
weather=pd.read_csv(weather_path,skiprows=3)
wt=pd.to_datetime(weather.time)
tbs = read('TBS_Town_Q_daily_consumption.csv')
tbs.index = pd.to_datetime(tbs.date_gregorian)
dates = pd.date_range('2024-01-01', '2026-01-01', inclusive='left')
daily = pd.DataFrame(index=dates)
daily['tbs_m3'] = tbs.consumption_m3
daily['tbs_valid'] = daily.tbs_m3.notna() & (daily.tbs_m3 > 0)
weather_daily=daily_integral(x,weather_values,((dates-pd.Timestamp('1970-01-01')).days).to_numpy())
daily['weather_valid']=weather_daily.weather_status.eq('complete').to_numpy()
daily['apparent_temperature_c']=weather_daily.apparent_temperature_mean_C.to_numpy()
daily['wind_max_kmh']=weather_daily.wind_max_kmh.to_numpy()
summary={'roster_rows':len(roster),'roster_customers':len(ids),'roster_duplicate_rows':int(roster.duplicated().sum()),'sources':{},'weather':{'rows':len(weather),'start_date':str(wt.min().date()),'end_date':str(wt.max().date()),'metadata':weather_metadata,'timezone_mismatch_accepted':True,'duplicate_timestamps':int(wt.duplicated().sum()),'nondaily_steps':int((wt.diff().dropna()!=pd.Timedelta(days=1)).sum()),'missing_values':int(weather.isna().sum().sum())},'tbs':{'rows':len(tbs),'start':str(tbs.index.min().date()),'end':str(tbs.index.max().date()),'missing_values':int(tbs.consumption_m3.isna().sum()),'negative_days':int((tbs.consumption_m3<0).sum()),'zero_days':int((tbs.consumption_m3==0).sum()),'duplicate_dates':int(tbs.index.duplicated().sum()),'missing_dates':int(len(pd.date_range(tbs.index.min(),tbs.index.max()).difference(tbs.index)))}}
matrices={}; candidates=[]
for name in ['bill_Customers_Town_Q.csv']:
    raw=read(name); f=raw.drop_duplicates().copy()
    for c in ['FromDate','ToDate']: f[c]=pd.to_datetime(f[c],errors='coerce')
    f['Consumption']=pd.to_numeric(f.Consumption,errors='coerce')
    f['days']=(f.ToDate-f.FromDate).dt.days+1
    valid=f.FromDate.notna() & f.ToDate.notna() & (f.days>0) & np.isfinite(f.Consumption) & (f.Consumption>=0)
    f=f[valid].copy(); m=np.zeros((len(ids),len(dates)),dtype=np.uint8); mw=m.copy(); mh=m.copy(); allocation=np.zeros(len(dates))
    mismatch=0; overlap=0; gap=0
    attrs=roster.groupby('SubscriptionNumber').apply(lambda g:set(zip(g.Capacity,g.UnitCount)),include_groups=False).to_dict()
    for ident,g in f.groupby('SubscriptionNumber'):
        g=g.sort_values('FromDate'); prev=None
        for r in g.itertuples():
            if prev is not None:
                overlap+=int(r.FromDate<=prev); gap+=max(0,(r.FromDate-prev).days-1)
            prev=r.ToDate if prev is None else max(prev,r.ToDate)
            if ident not in lookup: continue
            if (r.Capacity,r.UnitCount) not in attrs[ident]: mismatch+=1
            a=max(0,(r.FromDate-dates[0]).days); b=min(len(dates),(r.ToDate-dates[0]).days+1)
            if b<=a: continue
            i=lookup[ident]; m[i,a:b]=1; mh[i,a:max(a,b-1)]=1
            allocation[a:b]+=r.Consumption/r.days
            wa=r.FromDate.tz_localize('Asia/Tehran').timestamp(); wb=(r.ToDate+pd.Timedelta(days=1)).tz_localize('Asia/Tehran').timestamp()
            if r.FromDate>=wt.min() and r.ToDate<=wt.max() and daily.weather_valid.iloc[a:b].all(): mw[i,a:b]=1
    key='history'
    matrices[key]=m
    daily[key+'_coverage']=m.mean(axis=0); daily[key+'_weather_bounded_coverage']=mw.mean(axis=0); daily[key+'_halfopen_coverage']=mh.mean(axis=0); daily[key+'_uniform_estimate']=allocation
    summary['sources'][key]={'file':name,'rows':len(raw),'customers':int(raw.SubscriptionNumber.nunique()),'outside_roster':len(set(raw.SubscriptionNumber)-set(ids)),'roster_without_bills':len(set(ids)-set(raw.SubscriptionNumber)),'duplicates':len(raw)-len(raw.drop_duplicates()),'invalid_rows_after_dedup':int((~valid).sum()),'start':str(f.FromDate.min().date()),'end':str(f.ToDate.max().date()),'zero_rows':int((f.Consumption==0).sum()),'attribute_mismatch_rows':mismatch,'overlap_pairs':overlap,'internal_gap_days':gap,'duration_quantiles':f.days.quantile([0,.5,.9,.99,1]).to_dict(),'consumption_total':float(f.Consumption.sum()),'types':raw.ConsumptionType.value_counts().to_dict()}
    ready=daily.tbs_valid & daily.weather_valid
    for length in [30,60,90]:
        for start in range(len(dates)-length+1):
            end=start+length; sl=slice(start,end)
            if not ready.iloc[sl].all(): continue
            candidates.append({'source':key,'start':str(dates[start].date()),'end':str(dates[end-1].date()),'days':length,'minimum_coverage':float(m[:,sl].mean(axis=0).min()),'mean_coverage':float(m[:,sl].mean()),'fully_covered_customers':int(m[:,sl].all(axis=1).sum()),'weather_bounded_minimum':float(mw[:,sl].mean(axis=0).min()),'halfopen_minimum':float(mh[:,sl].mean(axis=0).min()),'apparent_temperature_min':float(daily.apparent_temperature_c.iloc[sl].min()),'apparent_temperature_max':float(daily.apparent_temperature_c.iloc[sl].max()),'uniform_to_tbs_ratio':float(allocation[sl].sum()/daily.tbs_m3.iloc[sl].sum())})
    # Customer identifiers intentionally omitted from public report evidence.
    f['daily_rate']=f.Consumption/f.days
    rates=f.groupby('SubscriptionNumber').daily_rate.median().sort_values(ascending=False)
    summary['sources'][key]['top_1pct_rate_share']=float(rates.head(max(1,int(np.ceil(len(rates)*.01)))).sum()/rates.sum())
# Winter screening deliberately does not require existing weather coverage.
winter=[]
for length in [30,60,90]:
    for start in range(len(dates)-length+1):
        stop=start+length; block=daily.iloc[start:stop]
        if not (block.index.month.isin([11,12,1,2,3]).all() and block.tbs_valid.all()): continue
        covered=m[:,start:stop]
        winter.append(dict(start=str(dates[start].date()),end=str(dates[stop-1].date()),days=length,
            minimum_coverage=float(covered.mean(axis=0).min()),mean_coverage=float(covered.mean()),
            fully_covered_customers=int(covered.all(axis=1).sum()),mean_tbs_m3=float(block.tbs_m3.mean()),
            peak_tbs_m3=float(block.tbs_m3.max()),weather_days=int(block.weather_valid.sum()),
            mean_apparent_temperature_c=float(block.apparent_temperature_c.mean()),
            weather_bounded_minimum=float(mw[:,start:stop].mean(axis=0).min())))
winter=pd.DataFrame(winter)
winter.to_csv(O/'winter_candidates.csv',index=False)
selected=winter[winter.minimum_coverage>=.95].sort_values(['days','mean_tbs_m3','minimum_coverage'],ascending=[True,False,False]).groupby('days').head(1)
selected.to_csv(O/'winter_shortlist.csv',index=False)
requirements=[]
for candidate in selected.itertuples():
    start=pd.Timestamp(candidate.start); end=pd.Timestamp(candidate.end)
    intersect=f[(f.FromDate<=end)&(f.ToDate>=start)].copy()
    full_ids=[ids[i] for i in np.flatnonzero(m[:,(start-dates[0]).days:(end-dates[0]).days+1].all(axis=1))]
    full=intersect[intersect.SubscriptionNumber.isin(full_ids)]
    for cap in [60,90,120,180,210,270,365,99999]:
        kept=full.groupby('SubscriptionNumber').filter(lambda g:bool((g.days<=cap).all()))
        if kept.empty: continue
        lo=kept.FromDate.min(); hi=kept.ToDate.max()+pd.Timedelta(days=1)
        requirements.append(dict(target_start=candidate.start,target_end=candidate.end,target_days=candidate.days,
            max_bill_days=cap if cap!=99999 else 'all',fully_covered_customers=kept.SubscriptionNumber.nunique(),
            roster_coverage=kept.SubscriptionNumber.nunique()/len(ids),weather_start_local=str(lo.date()),
            weather_end_local_exclusive=str(hi.date()),
            download_start_utc=str((lo-pd.Timedelta(days=1)).date()),download_end_utc=str(hi.date()),
            intersecting_bills=len(kept),observed_bill_volume=float(kept.Consumption.sum())))
pd.DataFrame(requirements).to_csv(O/'weather_requirements.csv',index=False)
summary['user_decisions']={'population_confirmed':True,'additional_bills_expected':False,'target':'cold high-consumption days; November-March screening assumption','missing_customers_treatment':'retain roster denominator; do not infer zero usage'}
rawt=pd.read_csv(ROOT/'data/raw/TBS_Town_Q_daily_raw.tab',sep='\t')
rt=pd.to_datetime(rawt.Time,format='%Y-%m-%d,%H:%M:%S'); v=pd.to_numeric(rawt['Vb [m3]'])
mask=(rt.dt.hour==0)&(rt.dt.minute==0)&(rt.dt.second==0)
rr=pd.DataFrame({'time':rt[mask],'v':v[mask]}).set_index('time')
derived=(rr.v.shift(-1)-rr.v).where(rr.index.to_series().shift(-1)-rr.index.to_series()==pd.Timedelta(days=1))
joined=pd.concat([derived.rename('raw'),tbs.consumption_m3.rename('prepared')],axis=1)
summary['tbs']['max_extraction_difference']=float((joined.raw-joined.prepared).abs().max())
summary['tbs']['missing_pattern_matches']=bool(joined.raw.isna().equals(joined.prepared.isna()))
summary['tbs']['statistics']=tbs.consumption_m3.describe().to_dict()
common=daily[daily.tbs_valid & daily.weather_valid]
summary['weather']['daily_tbs_apparent_temperature_correlation']=float(common.tbs_m3.corr(common.apparent_temperature_c))
summary['weather']['complete_local_start']=str(common.index.min().date()); summary['weather']['complete_local_end']=str(common.index.max().date())
summary['threshold_runs']={}
for key in matrices:
    summary['threshold_runs'][key]={}
    for threshold in [.95,.98,.99]:
        eligible=(daily[key+'_coverage']>=threshold)&daily.tbs_valid&daily.weather_valid
        runs=[]; start=None
        for i,ok in enumerate(list(eligible)+[False]):
            if ok and start is None:start=i
            if not ok and start is not None:
                runs.append({'start':str(dates[start].date()),'end':str(dates[i-1].date()),'days':i-start}); start=None
        summary['threshold_runs'][key][str(threshold)]=sorted(runs,key=lambda r:r['days'],reverse=True)
summary['fingerprints']={str(p.relative_to(ROOT/'data')):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['raw','prepared'] for p in (ROOT/'data'/folder).iterdir() if p.suffix in ['.csv','.tab','.xlsx']}
pd.DataFrame(candidates).sort_values(['source','days','minimum_coverage','mean_coverage'],ascending=[True,True,False,False]).to_csv(O/'candidate_periods.csv',index=False)
daily.index.name='date'; daily.to_csv(O/'daily_coverage.csv')
(O/'audit.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
print(json.dumps(summary,indent=2,default=str))
