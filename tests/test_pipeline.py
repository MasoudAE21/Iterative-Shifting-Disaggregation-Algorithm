from dataclasses import replace
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from isd.config import Config
from isd.data import COLUMNS
from isd.pipeline import run

def test_pipeline_full_intervals_missing_zeros_and_chunked_exports(tmp_path):
    data=tmp_path/'data'; data.mkdir()
    rows=[['00000000001','2025-01-02','2025-02-11','102','40','1','6'],['00000000001','2025-02-12','2025-04-04','260','40','1','6'],['00000000002','2025-02-01','2025-02-10','0','40','1','6'],['00000000003','2025-04-01','2025-04-02','4','40','1','6']]
    pd.DataFrame(rows,columns=COLUMNS).to_csv(data/'bill_1403.csv',encoding='utf-8-sig',index=False)
    with (data/'open-meteo-fixture.csv').open('w',encoding='utf-8') as f:
        f.write('latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n34.411247,50.490566,1435,0,GMT,GMT\n\ntime,temperature_2m (°C),apparent_temperature (°C),wind_speed_10m (km/h)\n')
        for i in range(2880):
            dt=datetime(2025,1,1)+timedelta(hours=i); f.write(f'{dt:%Y-%m-%dT%H:%M},{5+np.sin(i/40)},{3+np.sin(i/40)},10\n')
    c=Config(n_lr_models=2,n_disagg_cycles=2,max_customers=None,checkpoint=False,row_group_size=17)
    m=run(tmp_path,c,tmp_path/'out'); target=pq.read_table(tmp_path/'out/target_customer_daily.parquet').to_pandas()
    assert len(target)==180 and target.date_gregorian.nunique()==60; assert m['export']['target_numeric_rows']==70; assert m['export']['target_null_rows']==110
    zero=target[(target.SubscriptionNumber=='00000000002') & (target.estimate_status=='recorded_zero')]; assert len(zero)==10 and (zero.estimated_consumption==0).all()
    outside=target[target.SubscriptionNumber=='00000000003']; assert outside.estimated_consumption.isna().all()
    reconciliation=pq.read_table(tmp_path/'out/bill_reconciliation.parquet').to_pandas(); assert reconciliation.passed.all(); np.testing.assert_allclose(reconciliation.full_daily_sum,reconciliation.target_daily_sum+reconciliation.outside_target_sum)
    full=pq.read_table(tmp_path/'out/full_bill_daily.parquet').to_pandas(); assert full.date_gregorian.min()<target.date_gregorian.min() and full.date_gregorian.max()>target.date_gregorian.max()
    run(tmp_path,replace(c,row_group_size=1000,ingestion_chunk_size=1),tmp_path/'out2')
    other=pq.read_table(tmp_path/'out2/target_customer_daily.parquet').to_pandas(); np.testing.assert_array_equal(target.bill_id.fillna("missing"),other.bill_id.fillna("missing")); np.testing.assert_allclose(target.estimated_consumption,other.estimated_consumption,equal_nan=True)


def test_all_zero_candidate_bypasses_regression_even_constant_weather(tmp_path):
    from isd.data import normalize_frame,audit_normalized,coverage_classes,date_ordinal
    from isd.pipeline import allocate_model
    from isd.weather import daily_integral
    from datetime import date
    raw=pd.DataFrame([['00000000001','2025-01-20','2025-03-20','0','40','1','6']],columns=COLUMNS)
    bills,_=audit_normalized(normalize_frame(raw));origin=date_ordinal('2025-01-20');n=60
    seconds=datetime(2025,1,19,19,tzinfo=timezone.utc).timestamp()+np.arange(1445)*3600
    weather=daily_integral(seconds,np.tile([5.,3.,10.],(len(seconds),1)),np.arange(origin,origin+n))
    classes=coverage_classes(bills,origin,origin+n)
    cfg=Config(checkpoint=False);modeled,result,lookup,diagnostics,X,mask,g=allocate_model(bills,classes,weather,origin,cfg,tmp_path)
    assert result is not None and result.all_zero_fast_path and result.iterations==[]
    np.testing.assert_array_equal(result.allocations,np.zeros(60));assert diagnostics['fallback_reason'] is None
