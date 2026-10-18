"""Independent readback checks for full bill conservation and final peak CSV."""
from pathlib import Path
import csv,itertools,json,math,shutil,time
import numpy as np
import pyarrow.parquet as pq
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isd.data import sha256
from isd.pipeline import source_fingerprint
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'outputs'

def records(path,columns):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536,columns=columns):
        data=batch.to_pydict()
        yield from zip(*(data[c] for c in columns))

def main():
    start=time.perf_counter();manifest=json.loads((out/'run_manifest.json').read_text());cfg=manifest['configuration']
    bills=records(out/'bill_reconciliation.parquet',['bill_id','bill_total','target_daily_sum','outside_target_sum'])
    count=0;max_error=0.;zero_bills=0
    daily=records(out/'full_bill_daily.parquet',['bill_id','estimated_consumption'])
    for ident,group in itertools.groupby(daily,key=lambda row:row[0]):
        bill,total,target,outside=next(bills);assert bill==ident
        values=[v for _,v in group];assert all(math.isfinite(v) and v>=0 for v in values)
        error=abs(math.fsum(values)-total);max_error=max(max_error,error)
        assert error<=cfg['reconciliation_atol']+cfg['reconciliation_rtol']*abs(total)
        assert math.isclose(math.fsum(values),target+outside,rel_tol=1e-10,abs_tol=1e-8)
        if total==0: assert all(v==0 for v in values);zero_bills+=1
        count+=1
    assert next(bills,None) is None and count==manifest['source_audit']['rows']
    normalized=pq.read_table(out/'normalized_bills.parquet',columns=['SubscriptionNumber']).column(0).to_pylist();source_ids=set(normalized);del normalized
    values_by_day={};population=set()
    for ident,day,value,coverage in records(out/'target_customer_daily.parquet',['SubscriptionNumber','date_gregorian','estimated_consumption','coverage_class']):
        if coverage=='full':
            population.add(ident);values_by_day.setdefault(day,[]).append(value)
    totals={day:math.fsum(values) for day,values in values_by_day.items()}
    assert all(len(values)==len(population) for values in values_by_day.values());del values_by_day
    peak=min(totals,key=lambda d:(-totals[d],d));assert str(peak)==manifest['peak']['date']
    same_day=pq.read_table(out/'target_customer_daily.parquet',filters=[('date_gregorian','=',peak)],columns=['SubscriptionNumber','estimated_consumption']).to_pydict()
    expected=dict(zip(same_day['SubscriptionNumber'],same_day['estimated_consumption']))
    ids=set();missing=zeros=0;cohort=[]
    with (out/'customer_peak_consumption.csv').open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f);assert reader.fieldnames==['SubscriptionNumber','peakCosumptionValue']
        for row in reader:
            ident=row['SubscriptionNumber'];assert ident not in ids;ids.add(ident)
            text=row['peakCosumptionValue'];value=None if text=='' else float(text)
            assert value==expected[ident]
            if value is None:missing+=1
            else:
                assert math.isfinite(value) and value>=0;zeros+=value==0
                if ident in population:cohort.append(value)
    assert ids==source_ids and len(ids)==manifest['source_audit']['customers']
    assert math.isclose(math.fsum(cohort),totals[peak],rel_tol=1e-14,abs_tol=1e-8)
    assert source_fingerprint(ROOT)==manifest['code']
    report={'passed':True,'full_bill_rows_reconciled_from_daily_parquet':count,'maximum_bill_error':max_error,'zero_bills_checked':zero_bills,'distinct_input_and_csv_customers':len(ids),'missing_values':missing,'retained_zero_values':zeros,'same_day_values_exactly_match':True,'independent_math_fsum_peak_date':str(peak),'independent_math_fsum_peak_total':totals[peak],'fixed_population_customers':len(population),'source_hashes_match_final_run':True,'artifact_sha256':{name:sha256(out/name) for name in ['customer_peak_consumption.csv','peak_daily_totals.csv','peak_missing_reasons.csv','run_manifest.json']},'output_sizes_bytes':{p.name:p.stat().st_size for p in out.iterdir() if p.is_file()},'available_disk_bytes':shutil.disk_usage(ROOT).free,'verification_seconds':time.perf_counter()-start}
    (ROOT/'handoff/peak_final_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
