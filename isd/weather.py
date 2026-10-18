"""Point-value adapter; transform weather only AFTER local daily integration."""
from .errors import AvailabilityError
import csv, io
from datetime import datetime,timedelta,timezone,date
from zoneinfo import ZoneInfo
from pathlib import Path
import numpy as np
import pandas as pd
from .data import EPOCH
HEADERS=['time','temperature_2m (°C)','apparent_temperature (°C)','wind_speed_10m (km/h)']

def read_weather(path):
    lines=Path(path).read_text(encoding='utf-8').splitlines()
    if len(lines)<5 or lines[2]!='': raise ValueError('Weather metadata shape')
    metadata=dict(zip(next(csv.reader([lines[0]])),next(csv.reader([lines[1]]))))
    if metadata.get('timezone')!='GMT' or metadata.get('utc_offset_seconds')!='0': raise ValueError('UTC adapter requires GMT metadata')
    df=pd.read_csv(io.StringIO('\n'.join(lines[3:])),dtype={'time':'string'},keep_default_na=False)
    if list(df.columns)!=HEADERS: raise ValueError('Weather headers/units changed')
    if not df.time.str.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}').all(): raise ValueError('Weather datetime format')
    instants=pd.to_datetime(df.time,format='%Y-%m-%dT%H:%M',utc=True,errors='raise')
    seconds=instants.astype('int64').to_numpy()/ (1e6 if instants.dtype.unit=='us' else 1e9)
    if np.any(np.diff(seconds)<=0): raise ValueError('Duplicate or unordered weather timestamps')
    values=df[HEADERS[1:]].astype(float).to_numpy()
    if not np.isfinite(values).all() or np.any(values[:,2]<0): raise ValueError('Invalid weather values')
    metadata.update({'provider_model':None,'retrieved_at':None,'provider_variable_definition':'instant','wind_formula_unit':'mph','wind_unit_provenance':'NMGC Revised 2024 IRP, Appendix C-5, PDF page 69; formula matches paper Eq.16'})
    return seconds,values,metadata

def daily_integral(seconds,values,days,tz_name='Asia/Tehran'):
    seconds=np.asarray(seconds,float); values=np.asarray(values,float); tz=ZoneInfo(tz_name)
    if len(seconds)<2 or np.any(np.diff(seconds)<=0): raise ValueError('Weather timestamp ordering')
    records=[]
    for ordinal in days:
        d=EPOCH.date()+timedelta(days=int(ordinal))
        begin=datetime.combine(d,datetime.min.time(),tz).astimezone(timezone.utc).timestamp()
        end=datetime.combine(d+timedelta(days=1),datetime.min.time(),tz).astimezone(timezone.utc).timestamp()
        first=np.searchsorted(seconds,begin,side='right')-1; last=np.searchsorted(seconds,end,side='left')
        complete=first>=0 and last<len(seconds)
        if complete:
            complete=bool(np.all(np.diff(seconds[first:last+1])<=3600) and np.isfinite(values[first:last+1]).all())
        row={'date_gregorian':d,'weather_location_id':'open_meteo_34.411247_50.490566_1435','coverage_seconds':end-begin if complete else 0.0,'weather_status':'complete' if complete else 'unavailable','adapter_version':'point_linear_integral_v1','utc_day_start':datetime.fromtimestamp(begin,timezone.utc).isoformat(),'utc_day_end':datetime.fromtimestamp(end,timezone.utc).isoformat()}
        means=[]
        for j,name in enumerate(['temperature_mean_C','apparent_temperature_mean_C','wind_mean_kmh']):
            if complete:
                inner=seconds[(seconds>begin)&(seconds<end)]; x=np.concatenate(([begin],inner,[end])); v=np.interp(x,seconds,values[:,j]); mean=float(np.trapezoid(v,x)/(end-begin))
            else: mean=float('nan')
            row[name]=mean; means.append(mean)
        row['temperature_mean_F']=means[0]*1.8+32; row['wind_mean_mph']=means[2]/1.609344
        records.append(row)
    return pd.DataFrame(records)

def weather_features(daily):
    t=daily.temperature_mean_F.to_numpy(); wind=daily.wind_mean_mph.to_numpy()
    h65=np.maximum(65-t,0); h55=np.maximum(55-t,0); c65=np.maximum(t-65,0)
    multiplier=np.where(wind<=8,(152+wind)/160,(72+wind)/80)
    return {'intercept':np.ones(len(t)),'HDD65':h65,'HDD55':h55,'HDDW65':h65*multiplier,'CDD65':c65}

def build_design(daily,preset,mask,mode,exposure,exposure_scaled=True,allow_zero_spread=False):
    presets={'paper_section3_v1':['intercept','HDD65','HDD55','HDDW65','CDD65'],'winter_hdd65_v1':['intercept','HDD65'],'winter_hdd65_hddw65_v1':['intercept','HDD65','HDDW65'],'intercept_only_v1':['intercept']}
    if preset not in presets: raise ValueError('Unregistered feature preset')
    columns=presets[preset]; f=weather_features(daily); phi=np.column_stack([f[c] for c in columns]); metadata={'features':columns,'means':[0.0]*len(columns),'population_std':[1.0]*len(columns),'exposure_scaled_design':mode!='paper_reference' and exposure_scaled}
    if not np.isfinite(phi).all(): raise AvailabilityError('weather_unavailable: whole interval requires weather')
    if mode!='paper_reference':
        if np.sum(mask)==0: raise AvailabilityError('fit_unavailable: empty fit mask')
        for j in range(1,len(columns)):
            mean=float(np.mean(phi[mask,j])); std=float(np.std(phi[mask,j],ddof=0)); metadata['means'][j]=mean; metadata['population_std'][j]=std
            if std<=64*np.finfo(float).eps*max(1,abs(mean)):
                if allow_zero_spread: phi[:,j]=0; continue
                raise AvailabilityError('fit_unavailable: zero-spread feature')
            phi[:,j]=(phi[:,j]-mean)/std
        if exposure_scaled: phi=exposure[:,None]*phi
    return phi,metadata
