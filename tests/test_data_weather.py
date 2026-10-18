from dataclasses import replace
from datetime import datetime,timezone,timedelta
import csv
import numpy as np
import pandas as pd
import pytest
from isd.config import Config
from isd.data import COLUMNS,normalize_frame,audit_normalized,coverage_classes,date_ordinal,calendar_check,jalali_date
from isd.weather import daily_integral,weather_features,build_design

def frame(rows): return pd.DataFrame(rows,columns=COLUMNS)
def row(c,a,b,total): return [c,a,b,str(total),'40','1','6']
def test_ids_dates_source_rows_and_chunk_stability():
    raw=frame([row('00000000001','2025-01-20','2025-01-20',0),row('00000000002','2025-01-21','2025-01-23',9)])
    whole=normalize_frame(raw,'hash'); a=normalize_frame(raw.iloc[:1],'hash'); b=normalize_frame(raw.iloc[1:],'hash',row_start=3)
    assert whole.SubscriptionNumber.iloc[0]=='00000000001'; assert whole.source_row.tolist()==[2,3]; assert whole.bill_id.tolist()==a.bill_id.tolist()+b.bill_id.tolist(); assert whole.day_count.tolist()==[1,3]
    shuffled=whole.sample(frac=1,random_state=5).sort_values(['SubscriptionNumber','start_ordinal','end_ordinal','bill_id'])
    assert shuffled.bill_id.tolist()==whole.bill_id.tolist()

@pytest.mark.parametrize('a,b,total',[('01/20/2025','2025-01-21','5'),('2025-02-30','2025-03-01','5'),('2025-03-02','2025-03-01','5'),('2025-01-20','2025-01-21','-1'),('2025-01-20','2025-01-21','NaN')])
def test_invalid_quarantine(a,b,total):
    df=normalize_frame(frame([row('00000000001',a,b,total)])); audited,ledger=audit_normalized(df)
    assert audited.record_status.iloc[0]!='accepted'; assert ledger['invalid_rows']==1

def test_adjacent_overlap_duplicate_missing_policy():
    rows=[row('00000000001','2025-01-20','2025-02-10',10),row('00000000001','2025-02-11','2025-03-20',20),row('00000000002','2025-02-01','2025-02-10',0),row('00000000003','2025-01-20','2025-02-10',5),row('00000000003','2025-02-10','2025-03-20',6),row('00000000004','2025-04-01','2025-04-02',3)]
    df,ledger=audit_normalized(normalize_frame(frame(rows))); classes=coverage_classes(df,date_ordinal('2025-01-20'),date_ordinal('2025-03-21'))
    assert classes['00000000001']==('full',60); assert classes['00000000002']==('partial',10); assert classes['00000000003']==('none',0); assert classes['00000000004']==('none',0)
    assert ledger['same_customer_overlap_pairs']==1
    duplicate=normalize_frame(frame([rows[0],rows[0]])); d,stats=audit_normalized(duplicate); assert not (d.record_status=='accepted').any()
    d,stats=audit_normalized(duplicate,deduplicate_confirmed=True); assert (d.record_status=='accepted').sum()==1 and stats['record_status_counts']['removed_exact_duplicate']==1

def test_target_calendar_year_mapping_and_60_dates():
    info=calendar_check(Config()); assert info['days']==60 and not info['intended_year_confirmed']
    assert jalali_date(date_ordinal('2025-01-20'))=='1403-11-01'; assert jalali_date(date_ordinal('2025-03-20'))=='1403-12-30'
    with pytest.raises(ValueError): calendar_check(Config(target_start='2024-01-20'))
    with pytest.raises(ValueError,match='Production'): Config(production=True).validate()

def hourly_linear():
    start=datetime(2025,1,19,19,tzinfo=timezone.utc).timestamp(); seconds=start+np.arange(28)*3600
    t=(seconds-start)/3600; values=np.column_stack([t,100+t,np.full(28,12.874752)])
    return seconds,values

def test_weather_half_hour_boundary_integral_and_units():
    seconds,values=hourly_linear(); daily=daily_integral(seconds,values,[date_ordinal('2025-01-20')])
    assert daily.weather_status.iloc[0]=='complete'; assert daily.temperature_mean_C.iloc[0]==pytest.approx(13.5); assert daily.apparent_temperature_mean_C.iloc[0]==pytest.approx(113.5)
    assert daily.wind_mean_mph.iloc[0]==pytest.approx(8); assert daily.utc_day_start.iloc[0]=='2025-01-19T20:30:00+00:00'; assert daily.coverage_seconds.iloc[0]==86400
    features=weather_features(daily); assert features['HDD65'][0]==pytest.approx(65-(1.8*13.5+32)); assert features['HDDW65'][0]==pytest.approx(features['HDD65'][0])

@pytest.mark.parametrize('case',['missing_internal','missing_start','missing_end'])
def test_weather_missing_not_extrapolated(case):
    seconds,values=hourly_linear()
    index=np.arange(len(seconds)); index=np.delete(index,10) if case=='missing_internal' else index[3:] if case=='missing_start' else index[:-3]
    result=daily_integral(seconds[index],values[index],[date_ordinal('2025-01-20')]); assert result.weather_status.iloc[0]=='unavailable'; assert np.isnan(result.temperature_mean_C.iloc[0])

def test_wind_threshold_and_transform_after_mean():
    daily=pd.DataFrame({'temperature_mean_F':[30,30,30,65],'wind_mean_mph':[0,8,16,0]})
    f=weather_features(daily); np.testing.assert_allclose(f['HDDW65'][:3]/f['HDD65'][:3],[.95,1,1.1]); assert f['HDD65'][3]==0
    # Mean of threshold-crossing hourly HDD differs from transformation of daily mean.
    assert np.mean(np.maximum(65-np.array([60,70]),0))==2.5; assert f['HDD65'][3]!=2.5

def test_adapted_center_then_exposure():
    daily=pd.DataFrame({'temperature_mean_F':np.arange(60)+20.,'wind_mean_mph':np.ones(60)})
    mask=np.arange(60)<40; g=np.r_[np.ones(40),np.full(20,.5)]
    X,meta=build_design(daily,'winter_hdd65_v1',mask,'provisional_cohort_isd',g)
    assert X[0,0]==1 and X[-1,0]==.5; assert np.mean(X[mask,1])==pytest.approx(0,abs=1e-15); assert np.std(X[mask,1])==pytest.approx(1)
    U,_=build_design(daily,'winter_hdd65_v1',mask,'provisional_cohort_isd',g,False); np.testing.assert_allclose(X[40:],U[40:]*.5)


def test_array_traversal_matches_original_group_oracle():
    from isd import data_reference
    rows=[row('00000000001','2025-01-20','2025-02-10',10),row('00000000001','2025-02-11','2025-03-20',20),row('00000000002','2025-01-01','2025-01-05',2),row('00000000002','2025-01-07','2025-02-10',5),row('00000000003','2025-01-20','2025-02-20',5),row('00000000003','2025-02-01','2025-03-20',6)]
    raw=normalize_frame(frame(rows)); new,a=audit_normalized(raw); old,b=data_reference.audit_normalized(raw)
    assert a==b; assert new.record_status.tolist()==old.record_status.tolist()
    lo,hi=date_ordinal('2025-01-20'),date_ordinal('2025-03-21')
    assert coverage_classes(new,lo,hi)==data_reference.coverage_classes(old,lo,hi)
    assert isinstance(new.ConsumptionType.iloc[0],str)
