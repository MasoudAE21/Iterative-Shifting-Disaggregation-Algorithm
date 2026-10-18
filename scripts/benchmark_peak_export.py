"""Export-only memory benchmark; each size runs in a fresh process."""
import sys,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import psutil
from isd.data import COLUMNS,normalize_frame,date_ordinal
from isd.pipeline import export_outputs,PeakMemory
from isd.config import Config
from datetime import date,timedelta
n=int(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
raw=pd.DataFrame([[f'{i:011d}','2025-01-20','2025-03-20','60','40','1','6'] for i in range(n)],columns=COLUMNS)
bills=normalize_frame(raw);del raw
classes={f'{i:011d}':('full',60) for i in range(n)}
daily=pd.DataFrame({'date_gregorian':[date(2025,1,20)+timedelta(days=i) for i in range(60)],'temperature_mean_F':[40.]*60,'wind_mean_mph':[1.]*60,'weather_status':['complete']*60})
import gc;gc.collect()
before=psutil.Process().memory_info().rss
with PeakMemory() as m:
    result,_=export_outputs(bills,classes,daily,date_ordinal('2025-01-20'),Config(row_group_size=10000),out,'benchmark',bills.iloc[:0],None,{}, {'fallback_reason':'fit_unavailable','fit_dates':[]})
report={'customers':n,'row_group_size':10000,'rss_before_export':before,'peak_rss':m.peak,'incremental_peak_rss':m.peak-before,'seconds':m.seconds,'reconciled_bills':result['bill_reconciliation_passed']}
(out/'memory.json').write_text(json.dumps(report,indent=2));print(report)
