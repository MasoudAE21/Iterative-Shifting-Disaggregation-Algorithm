from dataclasses import replace
import csv
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from isd.config import Config
from isd.data import COLUMNS,read_bills,sha256
from isd.peak import choose_peak,export_peak
from datetime import date


def test_peak_ties_precision_same_day_missing_and_zero(tmp_path):
    assert choose_peak([date(2025,1,2),date(2025,1,1)],[2.,2.])==1
    assert choose_peak([1,2],[2.,np.nextafter(2.,3.)])==1
    classes={'00000000001':('full',2),'00000000002':('full',2),'00000000003':('partial',1),'00000000004':('none',0)}
    rows=[]
    for ident,values in zip(classes,[[9.,1.],[0.,10.],[100.,None],[None,None]]):
        for day,value in zip([date(2025,1,20),date(2025,1,21)],values):
            rows.append({'SubscriptionNumber':ident,'date_gregorian':day,'estimated_consumption':value,'reason':'no_target_bill' if value is None else 'none'})
    pq.write_table(pa.Table.from_pylist(rows),tmp_path/'target_customer_daily.parquet')
    p=export_peak(tmp_path,classes,Config(target_end_exclusive='2025-01-22'))
    assert p['date']=='2025-01-21' and p['total']==11 and p['missing_values']==2
    with (tmp_path/'customer_peak_consumption.csv').open() as f: data=list(csv.reader(f))
    assert data==[['SubscriptionNumber','peakCosumptionValue'],['00000000001','1.0'],['00000000002','10.0'],['00000000003',''],['00000000004','']]
    rows[1]['estimated_consumption']=0.; rows[3]['estimated_consumption']=0.
    pq.write_table(pa.Table.from_pylist(rows),tmp_path/'target_customer_daily.parquet')
    assert export_peak(tmp_path,classes,Config(target_end_exclusive='2025-01-22'))['valid_zeros']==1
    with pytest.raises(ValueError,match='No complete'): export_peak(tmp_path,{'x':('none',0)},Config())


@pytest.mark.parametrize('chunk',[1,2,100000])
@pytest.mark.parametrize('blank',['\n','  \r\n','\t\n'])
def test_physical_blank_rejected(tmp_path,chunk,blank):
    p=tmp_path/'b.csv'; p.write_text(','.join(COLUMNS)+'\n00000000001,2025-01-20,2025-01-20,1,40,1,6\n'+blank+'00000000002,2025-01-20,2025-01-20,1,40,1,6\n',encoding='utf-8-sig')
    with pytest.raises(ValueError,match='Blank physical'): read_bills(p,Config(ingestion_chunk_size=chunk))


def test_physical_identity_bom_crlf_quoted_comma_multiline(tmp_path):
    import hashlib
    p=tmp_path/'b.csv'
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(COLUMNS)
        for i in range(3): w.writerow([f'{i:011d}','2025-01-20','2025-01-20',1,'40,quoted',1,6])
    for chunk in [1,2,100000]:
        df,_=read_bills(p,Config(ingestion_chunk_size=chunk))
        assert list(df.source_row)==[2,3,4]
        assert list(df.bill_id)==[hashlib.sha256(f'{sha256(p)}:{i}'.encode()).hexdigest() for i in [2,3,4]]
    p.write_text(p.read_text(encoding='utf-8-sig').replace('40,quoted','40,\nquoted'),encoding='utf-8-sig')
    with pytest.raises(ValueError,match='Multiline'): read_bills(p,Config())


@pytest.mark.parametrize('kwargs',[{'feature_preset':'typo'},{'reconciliation_atol':float('nan')},{'reconciliation_rtol':-1},{'reconciliation_atol':float('inf')}])
def test_invalid_config_before_outputs(tmp_path,kwargs):
    from isd.pipeline import run
    with pytest.raises(ValueError): run(tmp_path,Config(**kwargs),tmp_path/'out')
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('engine',['reference','scaled'])
@pytest.mark.parametrize('stop',[1,3,9])
def test_resume_boundaries(engine,stop,tmp_path):
    from isd.solver import solve,State
    st=State(np.array([0,0]),np.array([40,40]),np.array([10.,90.]),np.array([0,40,80]),40)
    X=np.column_stack([np.ones(40),np.sin(np.arange(40))])
    c=Config(engine=engine,n_lr_models=3,n_disagg_cycles=3,memmap_threshold_mb=0)
    uninterrupted=solve(st,X,c)
    ck=tmp_path/'checkpoint.npz';solve(st,X,c,checkpoint_path=ck,stop_after_cycles=stop,storage=tmp_path/'first.memmap')
    resumed=solve(st,X,replace(c,resume=True),checkpoint_path=ck,storage=tmp_path/'resumed.memmap')
    np.testing.assert_array_equal(resumed.allocations,uninterrupted.allocations)
    np.testing.assert_array_equal(resumed.prediction,uninterrupted.prediction)
    assert len(resumed.cycles)==9 and len(resumed.iterations)==3

@pytest.mark.parametrize('failure',['missing','incompatible','unreadable'])
def test_pipeline_checkpoint_failures_no_success(tmp_path,failure):
    from isd.pipeline import run
    from test_pipeline import test_pipeline_full_intervals_missing_zeros_and_chunked_exports
    test_pipeline_full_intervals_missing_zeros_and_chunked_exports(tmp_path)
    out=tmp_path/'failed';out.mkdir()
    for name in ['run_manifest.json','target_customer_daily.parquet','customer_peak_consumption.csv']:
        (out/name).write_text('stale previous success')
    if failure=='unreadable': (out/'checkpoint.npz').write_bytes(b'not a checkpoint')
    if failure=='incompatible': np.savez(out/'checkpoint.npz',lock='wrong')
    with pytest.raises((ValueError,OSError)):
        run(tmp_path,Config(resume=True,max_customers=None,n_lr_models=2,n_disagg_cycles=2),out)
    assert not (out/'run_manifest.json').exists()
    assert not (out/'target_customer_daily.parquet').exists()
    assert not (out/'customer_peak_consumption.csv').exists()


def test_expected_weather_and_rank_fallback(tmp_path):
    from isd.data import normalize_frame,audit_normalized,coverage_classes,date_ordinal
    from isd.pipeline import allocate_model
    raw=pd.DataFrame([['00000000001','2025-01-20','2025-03-20',60,40,1,6]],columns=COLUMNS)
    bills,_=audit_normalized(normalize_frame(raw));origin=date_ordinal('2025-01-20')
    classes=coverage_classes(bills,origin,origin+60)
    daily=pd.DataFrame({'date_gregorian':[date(2025,1,20)+__import__('datetime').timedelta(days=i) for i in range(60)],'weather_status':['complete']*60,'temperature_mean_F':[40.]*60,'wind_mean_mph':[1.]*60})
    assert allocate_model(bills,classes,daily,origin,Config(),tmp_path)[3]['fallback_reason']=='fit_unavailable'
    daily.loc[0,'temperature_mean_F']=np.nan
    assert allocate_model(bills,classes,daily,origin,Config(),tmp_path)[3]['fallback_reason']=='weather_unavailable'



def test_cursor_leading_interior_trailing_quarantined_customers(tmp_path):
    from isd.data import normalize_frame,audit_normalized,coverage_classes,date_ordinal
    from isd.pipeline import export_outputs,canonical
    from datetime import timedelta
    raw=pd.DataFrame([[f'{i:011d}','2025-01-20','2025-03-20','-1' if i in [0,2,4] else '60','40','1','6'] for i in range(5)],columns=COLUMNS)
    bills,_=audit_normalized(normalize_frame(raw)); bills=canonical(bills)
    origin=date_ordinal('2025-01-20');classes=coverage_classes(bills,origin,origin+60)
    daily=pd.DataFrame({'date_gregorian':[date(2025,1,20)+timedelta(days=i) for i in range(60)],'temperature_mean_F':[40.]*60,'wind_mean_mph':[1.]*60,'weather_status':['complete']*60})
    export_outputs(bills,classes,daily,origin,Config(row_group_size=17),tmp_path,'test',bills.iloc[:0],None,{}, {'fallback_reason':'fit_unavailable','fit_dates':[]})
    target=pq.read_table(tmp_path/'target_customer_daily.parquet').to_pandas()
    for ident,group in target.groupby('SubscriptionNumber'):
        assert len(group)==60
        if int(ident) in [0,2,4]: assert group.estimated_consumption.isna().all() and (group.reason=='rejected_conflict').all()
        else: assert (group.estimated_consumption==1).all()

@pytest.mark.parametrize('scenario',['weather_response','unmodeled_daily_variation'])
def test_default_cohort_known_truth_exposure(tmp_path,scenario,record_property):
    from isd.data import normalize_frame,audit_normalized,coverage_classes,date_ordinal,EPOCH
    from isd.pipeline import allocate_model,canonical
    from datetime import timedelta
    origin=date_ordinal('2025-01-10');n=80;x=np.arange(n);hdd=15+8*np.sin(x/9)
    daily=pd.DataFrame({'date_gregorian':[EPOCH.date()+timedelta(days=int(origin+i)) for i in x],'temperature_mean_F':65-hdd,'wind_mean_mph':np.ones(n),'weather_status':['complete']*n})
    truth=np.array([2+(i+1)*hdd/10 for i in range(4)])
    if scenario=='unmodeled_daily_variation': truth*=1+.6*np.sin(x*2)[None,:]
    bounds=[[(0,35),(35,70)],[(10,45),(45,80)],[(5,50),(50,75)],[(20,40)]]
    rows=[]
    for i,intervals in enumerate(bounds):
        for a,b in intervals: rows.append([f'{i:011d}',str(daily.date_gregorian[a]),str(daily.date_gregorian[b-1]),str(float(truth[i,a:b].sum())),40,1,6])
    bills,_=audit_normalized(normalize_frame(pd.DataFrame(rows,columns=COLUMNS)));bills=canonical(bills)
    classes=coverage_classes(bills,origin+10,origin+70)
    cfg=Config(checkpoint=False)
    modeled,result,lookup,diag,X,mask,g=allocate_model(bills,classes,daily,origin,cfg,tmp_path)
    assert result is not None and len(lookup)==6 and diag['modeled_customers']==3
    assert np.all(g[10:70]==1) and np.any(g[:10]<1) and np.any(g[70:]<1)
    target=np.zeros((3,60));uniform=np.zeros_like(target);offset=0
    for r in modeled.itertuples():
        a=int(r.start_ordinal)-origin;b=int(r.end_ordinal)-origin;values=result.allocations[offset:offset+b-a];offset+=b-a
        assert sum(values)==pytest.approx(r.Consumption,abs=1e-8,rel=1e-10)
        left=max(10,a);right=min(70,b);i=int(r.SubscriptionNumber)
        target[i,left-10:right-10]=values[left-a:right-a];uniform[i,left-10:right-10]=r.Consumption/(b-a)
    mae=float(np.mean(np.abs(target-truth[:3,10:70])));baseline=float(np.mean(np.abs(uniform-truth[:3,10:70])))
    assert np.isfinite(mae) and np.isfinite(baseline)
    record_property('scenario',scenario);record_property('isd_customer_mae',mae);record_property('uniform_customer_mae',baseline)

