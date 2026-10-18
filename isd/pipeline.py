"""Import -> audit -> weather -> population -> full ISD -> reconcile -> export."""
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import hashlib, importlib.metadata, json, math, os, platform, threading, time, uuid
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import psutil
from .errors import AvailabilityError
from .config import Config
from .data import read_bills,sha256,date_ordinal,jalali_date,calendar_check,coverage_classes,hash_sample,prepare_state,EPOCH
from .weather import read_weather,daily_integral,build_design,weather_features
from .solver import initialize,solve,lstsq_diagnostics,aggregate_kernel,correct_roundoff

class PeakMemory:
    """Sample RSS including import/ingestion; Windows peak working set is also recorded."""
    def __enter__(self):
        self.peak=0; self.done=threading.Event(); self.start=time.perf_counter(); self.process=psutil.Process()
        def sample():
            while not self.done.is_set():
                self.peak=max(self.peak,self.process.memory_info().rss); self.done.wait(.02)
        self.thread=threading.Thread(target=sample,daemon=True); self.thread.start(); return self
    def __exit__(self,*args):
        self.peak=max(self.peak,self.process.memory_info().rss); self.done.set(); self.thread.join(); self.seconds=time.perf_counter()-self.start

def clean_json(value):
    if isinstance(value,dict): return {str(k):clean_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [clean_json(v) for v in value]
    if isinstance(value,np.generic): return clean_json(value.item())
    if isinstance(value,float) and not math.isfinite(value): return None
    if isinstance(value,Path): return str(value)
    return value

def write_json(path,value): Path(path).write_text(json.dumps(clean_json(value),indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def source_fingerprint(root):
    paths=[root/'run_pipeline.py',root/'requirements.txt',root/'README.md']+sorted((root/'isd').glob('*.py'))+sorted((root/'tests').glob('*.py'))+sorted((root/'configs').glob('*.json'))+sorted((root/'scripts').glob('*.py'))
    versions={str(p.relative_to(root)):sha256(p) for p in paths if p.exists()}
    combined=hashlib.sha256(json.dumps(versions,sort_keys=True).encode()).hexdigest()
    return {'source_sha256':combined,'files':versions}

class RowWriter:
    def __init__(self,path,schema,chunk): self.writer=pq.ParquetWriter(path,schema,compression='zstd'); self.schema=schema; self.chunk=chunk; self.rows=[]; self.count=0
    def append(self,row):
        self.rows.append(row); self.count+=1
        if len(self.rows)>=self.chunk: self.flush()
    def flush(self):
        if self.rows: self.writer.write_table(pa.Table.from_pylist(self.rows,schema=self.schema),row_group_size=self.chunk); self.rows=[]
    def close(self): self.flush(); self.writer.close()

def schema_for(kind):
    string=pa.string(); day=pa.date32(); number=pa.float64()
    if kind=='bill_daily':
        return pa.schema([('run_id',string),('model_group_id',string),('bill_id',string),('SubscriptionNumber',string),('source_row',pa.int64()),('date_gregorian',day),('estimated_consumption',number),('method',string),('estimate_status',string)])
    return pa.schema([('run_id',string),('SubscriptionNumber',string),('date_gregorian',day),('date_jalali',string),('estimated_consumption',number),('bill_id',string),('model_group_id',string),('coverage_class',string),('method',string),('estimate_status',string),('reason',string)])

def canonical(df):
    return df.sort_values(['SubscriptionNumber','start_ordinal','end_ordinal','bill_id'],kind='stable').reset_index(drop=True)

def population(df,cfg):
    lo,hi=date_ordinal(cfg.target_start),date_ordinal(cfg.target_end_exclusive)
    classes=coverage_classes(df,lo,hi); candidate=[c for c,(kind,n) in classes.items() if kind=='full']
    eligible=list(classes) if cfg.sample_scope=='universe' else candidate
    ids=hash_sample(eligible,cfg.max_customers,cfg.sample_seed)
    selected=canonical(df[df.SubscriptionNumber.isin(ids)].copy())
    selected_classes={c:classes[c] for c in ids}
    return selected,selected_classes,{'source_customers':len(classes),'source_coverage_counts':dict(Counter(k for k,n in classes.values())),'source_balanced_candidates':len(candidate),'selection':'SHA256(seed + SubscriptionNumber) ascending; all bills retained','seed':cfg.sample_seed,'sample_scope':cfg.sample_scope,'selected_customers':len(ids),'selected_coverage_counts':dict(Counter(k for k,n in selected_classes.values())),'selected_covered_customer_days':sum(n for k,n in selected_classes.values()),'selected_null_customer_days':sum(hi-lo-n for k,n in selected_classes.values())}

def allocate_model(accepted,classes,daily,origin,cfg,out):
    cfg.validate()
    if cfg.resume and (not cfg.checkpoint or not (out/'checkpoint.npz').exists()): raise ValueError('No resume checkpoint')
    lo,hi=date_ordinal(cfg.target_start),date_ordinal(cfg.target_end_exclusive); n=len(daily)
    if cfg.mode=='paper_reference': modeled=accepted.copy(); cohort_ids=set(accepted.SubscriptionNumber); mask=np.ones(n,bool)
    else:
        cohort_ids={c for c,(k,_) in classes.items() if k=='full'}; modeled=accepted[accepted.SubscriptionNumber.isin(cohort_ids)].reset_index(drop=True)
        mask=(np.arange(origin,origin+n)>=lo)&(np.arange(origin,origin+n)<hi)
    diagnostics={'modeled_customers':len(cohort_ids),'modeled_bills':len(modeled),'fallback_reason':None}; result=None; design=None; feature_info=None
    counts=np.zeros(n,np.int64)
    # Accepted within-customer bills are non-overlapping, so count bill support equals distinct customers.
    for a,b in zip(modeled.start_ordinal.astype(int),modeled.end_ordinal.astype(int)): counts[a-origin:b-origin]+=1
    exposure=counts/len(cohort_ids) if cohort_ids else np.zeros(n)
    if cfg.mode=='paper_reference': exposure=np.ones(n)
    else: mask &= (counts==len(cohort_ids)) & (daily.weather_status.to_numpy()=='complete')
    if len(modeled):
        state=prepare_state(modeled,origin,n)
        try:
            design,feature_info=build_design(daily,cfg.feature_preset,mask,cfg.mode,exposure,cfg.exposure_scaled,allow_zero_spread=bool(np.all(state.totals==0)))
            singular=np.linalg.svd(design[mask],compute_uv=False); rcond=cfg.regression_rcond if cfg.regression_rcond is not None else max(int(mask.sum()),design.shape[1])*np.finfo(float).eps
            rank=int(np.sum(singular>rcond*singular[0])) if len(singular) else 0
            diagnostics['initial_rank']={'rank':rank,'columns':design.shape[1],'n_fit':int(mask.sum()),'singular_values':singular.tolist(),'diagnostic_only_svd_no_extra_regression':True}
            result=solve(state,design,cfg,mask,out/'checkpoint.npz' if cfg.checkpoint else None,out/'allocations.memmap',exposure=exposure)
        except AvailabilityError as e:
            if cfg.mode=='paper_reference' or cfg.resume: raise
            diagnostics['fallback_reason']='weather_unavailable' if 'weather_unavailable' in str(e) else 'fit_unavailable'; diagnostics['fallback_detail']=str(e)
        diagnostics['allocated_model_interval_days']=int(state.offsets[-1])
    else: diagnostics['fallback_reason']='fit_unavailable'; diagnostics['allocated_model_interval_days']=0
    diagnostics.update({'feature_scaling':feature_info,'exposure_scaled_design':cfg.mode!='paper_reference' and cfg.exposure_scaled,'fit_dates':[str(d) for d in daily.loc[mask,'date_gregorian']],'g':exposure.tolist(),'n_cohort_covered':counts.tolist()})
    lookup={str(b):i for i,b in enumerate(modeled.bill_id)} if result is not None else {}
    return modeled,result,lookup,diagnostics,design,mask,exposure

def export_outputs(selected,classes,daily,origin,cfg,out,run_id,modeled,result,lookup,diagnostics):
    accepted=selected[selected.record_status=='accepted'].reset_index(drop=True); n=len(daily); lo=date_ordinal(cfg.target_start); hi=date_ordinal(cfg.target_end_exclusive)
    model_offsets=np.concatenate(([0],np.cumsum(modeled.day_count.to_numpy(dtype=np.int64))))
    dates=[EPOCH.date()+timedelta(days=int(i)) for i in range(origin,origin+n)]
    sums=np.zeros(n); uniform_sum=np.zeros(n); weighted_sum=np.zeros(n); fallback_sum=np.zeros(n); model_sum=np.zeros(n); covered=np.zeros(n,np.int64); zeros=np.zeros(n,np.int64)
    reconcile=[]; methods=Counter(); method_days=Counter(); bill_writer=RowWriter(out/'full_bill_daily.parquet',schema_for('bill_daily'),cfg.row_group_size)
    reconc_schema=pa.schema([('run_id',pa.string()),('bill_id',pa.string()),('SubscriptionNumber',pa.string()),('source_row',pa.int64()),('bill_total',pa.float64()),('full_daily_sum',pa.float64()),('signed_discrepancy',pa.float64()),('absolute_discrepancy',pa.float64()),('target_daily_sum',pa.float64()),('outside_target_sum',pa.float64()),('method',pa.string()),('passed',pa.bool_())])
    rw=RowWriter(out/'bill_reconciliation.parquet',reconc_schema,cfg.row_group_size)
    features=weather_features(daily); weights=1+features['HDD65']; weather_ok=np.isfinite(weights).all()
    # Compact fallback representation is expanded one bill at a time.
    def allocation(r):
        l=int(r.day_count); d=int(r.start_ordinal)-origin; total=float(r.Consumption)
        if str(r.bill_id) in lookup:
            i=lookup[str(r.bill_id)]; vals=result.allocations[model_offsets[i]:model_offsets[i+1]]
            method='paper_reference_isd' if cfg.mode=='paper_reference' else 'cohort_exposure_isd' if cfg.exposure_scaled else 'cohort_masked_unscaled_isd'; reason='none'
        else:
            vals=correct_roundoff(np.full(l,total/l),total,cfg); method='uniform_full_interval'
            reason=diagnostics['fallback_reason'] if classes[str(r.SubscriptionNumber)][0]=='full' and diagnostics['fallback_reason'] else 'partial_target_coverage'
        return vals,d,method,reason
    for r in accepted.itertuples(index=False):
        vals,d,method,reason=allocation(r); l=len(vals); total=float(r.Consumption); methods[method]+=1; method_days[method]+=l
        uniform=correct_roundoff(np.full(l,total/l),total,cfg)
        if weather_ok:
            w=weights[d:d+l]; weighted=correct_roundoff(total*(w/math.fsum(w)),total,cfg)
        else: weighted=np.full(l,np.nan)
        sums[d:d+l]+=vals; uniform_sum[d:d+l]+=uniform; weighted_sum[d:d+l]+=weighted; covered[d:d+l]+=1
        if total==0: zeros[d:d+l]+=1
        if method.endswith('_isd'): model_sum[d:d+l]+=vals
        else: fallback_sum[d:d+l]+=vals
        left=max(0,lo-int(r.start_ordinal)); right=min(l,hi-int(r.start_ordinal)); target=math.fsum(vals[left:right]) if right>left else 0.0
        full=math.fsum(vals); outside=full-target; error=full-total; passed=abs(error)<=cfg.reconciliation_atol+cfg.reconciliation_rtol*abs(total)
        if not passed or np.any(vals<0) or not np.isfinite(vals).all(): raise ArithmeticError('Export conservation/nonnegativity')
        rw.append({'run_id':run_id,'bill_id':str(r.bill_id),'SubscriptionNumber':str(r.SubscriptionNumber),'source_row':int(r.source_row),'bill_total':total,'full_daily_sum':full,'signed_discrepancy':error,'absolute_discrepancy':abs(error),'target_daily_sum':target,'outside_target_sum':outside,'method':method,'passed':passed})
        reconcile.append(abs(error))
        for j,value in enumerate(vals): bill_writer.append({'run_id':run_id,'model_group_id':'shared_population' if method.endswith('_isd') else 'fallback','bill_id':str(r.bill_id),'SubscriptionNumber':str(r.SubscriptionNumber),'source_row':int(r.source_row),'date_gregorian':dates[d+j],'estimated_consumption':float(value),'method':method,'estimate_status':'recorded_zero' if total==0 else 'estimated'})
    bill_writer.close(); rw.close()
    tw=RowWriter(out/'target_customer_daily.parquet',schema_for('target'),cfg.row_group_size); target_sum=np.zeros(hi-lo); target_numeric=target_null=0
    quarantine=set(selected.loc[selected.record_status!='accepted','SubscriptionNumber'])
    records=iter(accepted.itertuples(index=False)); current=next(records,None)
    target_dates=[EPOCH.date()+timedelta(days=int(d)) for d in range(lo,hi)]; jalali=[jalali_date(d) for d in range(lo,hi)]
    for ident in sorted(classes):
        values=[None]*(hi-lo); billids=[None]*(hi-lo); meth=['none']*(hi-lo); reasons=['rejected_conflict' if ident in quarantine else 'no_target_bill']*(hi-lo); recorded_zero=[False]*(hi-lo)
        while current is not None and str(current.SubscriptionNumber)==str(ident):
                r=current; current=next(records,None)
                vals,d,method,reason=allocation(r)
                for day in range(max(lo,int(r.start_ordinal)),min(hi,int(r.end_ordinal))):
                    pos=day-lo
                    if values[pos] is not None: raise ArithmeticError('Unresolved overlap in customer export')
                    values[pos]=float(vals[day-int(r.start_ordinal)]); billids[pos]=str(r.bill_id); meth[pos]=method; reasons[pos]=reason; recorded_zero[pos]=r.Consumption==0
        for j,value in enumerate(values):
            if value is None: target_null+=1
            else: target_numeric+=1; target_sum[j]+=value
            tw.append({'run_id':run_id,'SubscriptionNumber':str(ident),'date_gregorian':target_dates[j],'date_jalali':jalali[j],'estimated_consumption':value,'bill_id':billids[j],'model_group_id':'shared_population' if meth[j].endswith('_isd') else 'fallback' if value is not None else None,'coverage_class':classes[ident][0],'method':meth[j],'estimate_status':'unavailable' if value is None else 'recorded_zero' if recorded_zero[j] else 'estimated','reason':reasons[j]})
    tw.close()
    # Domain can exclude unsupported target dates; align by date, without fabricating individual zero values.
    for j,day in enumerate(range(lo,hi)):
        expected=sums[day-origin] if origin<=day<origin+n else 0
        if not np.isclose(target_sum[j],expected,atol=1e-7,rtol=1e-10): raise ArithmeticError('Customer/aggregate target identity')
    last_p=result.prediction if result is not None else np.full(n,np.nan)
    aggregate=pd.DataFrame({'run_id':run_id,'date_gregorian':dates,'cohort_isd_sum':model_sum,'observed_partial_or_failed_uniform_sum':fallback_sum,'combined_observed_support_sum':sums,'uniform_baseline_sum':uniform_sum,'weather_weighted_baseline_sum':weighted_sum,'predicted_profile_last_outer':last_p,'n_customers_covered':covered,'n_bills_covered':covered,'n_zero_customers':zeros,'missing_customer_count':len(classes)-covered,'coverage_fraction':covered/max(1,len(classes)),'fit_eligible':[result is not None and str(x) in diagnostics['fit_dates'] for x in dates],'weather_status':daily.weather_status,'extrapolation_flag':[not (lo<=origin+i<hi) for i in range(n)]})
    aggregate.to_parquet(out/'aggregate_daily.parquet',index=False); aggregate.to_csv(out/'aggregate_daily_summary.csv',index=False)
    comparison=[]
    target_mask=(np.arange(origin,origin+n)>=lo)&(np.arange(origin,origin+n)<hi)
    for name,arr in [('uniform',uniform_sum),('weather_weighted_baseload1_hdd65',weighted_sum)]:
        delta=sums[target_mask]-arr[target_mask]
        comparison.append({'baseline':name,'target_aggregate_mean_absolute_difference':float(np.mean(np.abs(delta))) if len(delta) else None,'target_aggregate_max_absolute_difference':float(np.max(np.abs(delta))) if len(delta) else None,'target_baseline_total_source_units':float(np.sum(arr[target_mask])),'target_pipeline_total_source_units':float(np.sum(sums[target_mask])),'interpretation':'Shape difference, not measured error; no independent daily truth'})
    pd.DataFrame(comparison).to_csv(out/'baseline_comparison.csv',index=False)
    audit={'full_bill_daily_rows':bill_writer.count,'target_customer_daily_rows':tw.count,'target_numeric_rows':target_numeric,'target_null_rows':target_null,'bill_reconciliation_passed':len(reconcile),'max_bill_abs_discrepancy':max(reconcile,default=0),'methods_bill_counts':dict(methods),'methods_interval_days':dict(method_days),'allocated_interval_days':int(accepted.day_count.sum()),'total_bill_consumption_source_units':float(accepted.Consumption.sum()),'full_allocation_sum':float(sums.sum()),'full_target_export_identities_passed':True,'baseline_definitions':{'uniform':'B/L on complete bill interval','weather_weighted':'B * (1+HDD65) / sum_interval(1+HDD65); fixed, no regression or shifting','ols':'last immutable aggregate prediction; diagnostic, not bill reconciled'}}
    return audit,comparison

def run(root,cfg,output_dir=None,bills_path=None,weather_path=None,preloaded=None):
    root=Path(root).resolve(); cfg.validate(); mapping=calendar_check(cfg); run_id=uuid.uuid4().hex
    out=Path(output_dir) if output_dir else root/'outputs'/'ide_pilot'; out.mkdir(parents=True,exist_ok=True)
    # Invalidate prior completion artifacts before a new attempt; retain resume state.
    for name in ('run_manifest.json','run_summary.csv','peak_summary.md','customer_peak_consumption.csv','target_customer_daily.parquet','peak_missing_reasons.csv','peak_daily_totals.csv'):
        (out/name).unlink(missing_ok=True)
    bills_path=Path(bills_path) if bills_path else root/'data'/'bill_1403.csv'; weather_path=Path(weather_path) if weather_path else next((root/'data').glob('open-meteo*.csv'))
    with PeakMemory() as memory:
        stages={}; rss_stages={}; available_ram=psutil.virtual_memory().available; t=time.perf_counter()
        if preloaded is None: source,audit=read_bills(bills_path,cfg)
        else: source,audit=preloaded
        stages['import_audit_seconds']=time.perf_counter()-t
        rss_stages['after_import']=memory.process.memory_info().rss
        t=time.perf_counter(); selected,classes,selection=population(source,cfg); stages['population_seconds']=time.perf_counter()-t
        accepted=selected[selected.record_status=='accepted']; lo=date_ordinal(cfg.target_start); hi=date_ordinal(cfg.target_end_exclusive)
        origin=int(accepted.start_ordinal.min()) if len(accepted) else lo; end=int(accepted.end_ordinal.max()) if len(accepted) else hi
        t=time.perf_counter(); seconds,values,weather_meta=read_weather(weather_path)
        if cfg.provider_variable_definition!='instant' or cfg.weather_adapter!='point_linear_integral_v1': raise ValueError('Unimplemented weather adapter; period orientation required')
        daily=daily_integral(seconds,values,np.arange(origin,end),cfg.timezone); daily.to_parquet(out/'daily_weather.parquet',index=False); stages['weather_seconds']=time.perf_counter()-t
        persisted=selected.copy()
        for field,ordinal in [('start_day','start_ordinal'),('end_day_exclusive','end_ordinal')]: persisted[field]=pd.to_datetime(persisted[ordinal],unit='D',origin='unix',errors='coerce').dt.date

        t=time.perf_counter(); modeled,result,lookup,diagnostics,design,mask,g=allocate_model(accepted,classes,daily,origin,cfg,out); stages['model_seconds']=time.perf_counter()-t
        rss_stages['after_solve_checkpoint']=memory.process.memory_info().rss
        persisted['model_group_id']=np.where(persisted.bill_id.astype(str).isin(lookup),'shared_population',np.where(persisted.record_status=='accepted','fallback',None))
        persisted.to_parquet(out/'normalized_bills.parquet',index=False)
        t=time.perf_counter(); export,baselines=export_outputs(selected,classes,daily,origin,cfg,out,run_id,modeled,result,lookup,diagnostics); stages['export_seconds']=time.perf_counter()-t
        rss_stages['after_full_and_target_export']=memory.process.memory_info().rss
        from .peak import export_peak
        t=time.perf_counter(); peak=export_peak(out,classes,cfg); stages['peak_export_seconds']=time.perf_counter()-t
        input_files=[bills_path,weather_path]+list((root/'data').glob('ISD_Independent_Review.docx'))+list((root/'data').glob('ISD_Implementation_Handoff.docx'))+list((root/'data').glob('An Iterative*.pdf'))
        hashes={p.name:sha256(p) for p in input_files}
        if len(source) and hashes[bills_path.name]!=str(source.source_file_sha256.iloc[0]): raise RuntimeError('Source changed after ingestion')
        locked=json.loads((root/'handoff'/'data_schema.json').read_text(encoding='utf-8')) if (root/'handoff'/'data_schema.json').exists() else None
        hash_match=all(hashes.get(i['filename'],i['sha256'])==i['sha256'] for i in locked['files']) if locked else None
        manifest={'run_id':run_id,'configuration':cfg.as_dict(),'inputs':hashes,'audit_hash_lock_matched':hash_match,'code':source_fingerprint(root),'dependencies':{p:importlib.metadata.version(p) for p in ['numpy','pandas','pyarrow','numba','llvmlite','jdatetime','jalali-core','tzdata','psutil']},'python':platform.python_version(),'calendar_mapping':mapping,'source_audit':audit,'selection':selection,'date_domain_half_open':[str(EPOCH.date()+timedelta(days=origin)),str(EPOCH.date()+timedelta(days=end))],'weather_metadata':weather_meta,'weather_daily_complete':int((daily.weather_status=='complete').sum()),'weather_daily_unavailable':int((daily.weather_status!='complete').sum()),'model_diagnostics':diagnostics,'export':export,'peak':peak,'memory_stage_rss_bytes':rss_stages,'available_ram_at_start':available_ram,'stage_wall_seconds':stages,'warnings':['Provisional semantics and intended target year unconfirmed.','Recorded consumption units and physical interpretation are unknown.','No independent daily measurements supplied: consistency, plausibility and sensitivity only.','Deterministic customer hash sample is not proof of representativeness.','Combined observed-support aggregate mixes cohort ISD and uniform fallback; not citywide demand.','Exposure scaling outside fit window assumes equal average weather response.']}
        if result:
            manifest['iterations']=result.iterations; manifest['cycles']=result.cycles; manifest['zero_residual_noops']=result.zero_residual_noops; manifest['all_zero_fast_path']=result.all_zero_fast_path
            pd.DataFrame(result.iterations).drop(columns=['column_ranges','beta','singular_values','zero_columns'],errors='ignore').to_csv(out/'iteration_summary.csv',index=False)
        else: manifest['zero_residual_noops']=0
    manifest['wall_seconds']=memory.seconds; manifest['peak_rss_bytes']=memory.peak
    write_json(out/'run_manifest.json',manifest)
    from .peak import write_peak_summary
    write_peak_summary(out,manifest)
    pd.DataFrame([{'customers':len(classes),'bills':len(accepted),'model_customers':diagnostics['modeled_customers'],'model_bills':diagnostics['modeled_bills'],'allocated_interval_days':export['allocated_interval_days'],'model_interval_days':diagnostics['allocated_model_interval_days'],'wall_seconds':memory.seconds,'peak_rss_bytes':memory.peak,**{k:v for k,v in stages.items()}}]).to_csv(out/'run_summary.csv',index=False)
    print(f'Completed {out}: {len(classes)} customers, {len(accepted)} bills, {export["allocated_interval_days"]} bill-days, {memory.seconds:.2f}s',flush=True)
    return manifest
