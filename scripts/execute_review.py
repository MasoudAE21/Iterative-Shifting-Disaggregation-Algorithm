"""Reproduce tests, staged pilots and review material; never runs full production."""
import argparse,cProfile,gc,io,json,pstats,shutil,subprocess,sys,time,zipfile
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from isd.config import Config
from isd.data import read_bills,sha256,coverage_classes,date_ordinal,hash_sample,prepare_state
from isd.pipeline import run,population,allocate_model,PeakMemory,write_json
from isd.weather import read_weather,daily_integral
from isd.solver import solve
from isd.experiments import synthetic_experiment
REVIEW=ROOT/'handoff'/'implementation'; REVIEW.mkdir(parents=True,exist_ok=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['measure','finish'],default='finish');args=parser.parse_args()
    print('SYNTHETIC TESTS FIRST',flush=True)
    test=subprocess.run([sys.executable,'-m','pytest','tests','-q','--junitxml='+str(REVIEW/'test_results.xml')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (REVIEW/'test_results.txt').write_text(test.stdout+test.stderr,encoding='utf-8');print(test.stdout,flush=True)
    if test.returncode: raise SystemExit('Tests failed: real pilots not started')
    synthetic_experiment().to_csv(REVIEW/'synthetic_truth_comparison.csv',index=False)
    print('IMPORT AND FRESH FULL-SOURCE STRUCTURAL AUDIT',flush=True)
    prof=cProfile.Profile()
    with PeakMemory() as measured:
        prof.enable(); source,audit=read_bills(ROOT/'data'/'bill_1403.csv',Config());prof.disable()
    write_json(REVIEW/'recomputed_source_audit.json',{'audit':audit,'interval_days':int(source.loc[source.record_status=='accepted','day_count'].sum()),'wall_seconds':measured.seconds,'peak_rss_bytes':measured.peak,'source_sha256':sha256(ROOT/'data'/'bill_1403.csv')})
    buf=io.StringIO();pstats.Stats(prof,stream=buf).strip_dirs().sort_stats('cumtime').print_stats(25);(REVIEW/'import_profile.txt').write_text(buf.getvalue(),encoding='utf-8')
    print('Full source audited',audit,'seconds',measured.seconds,'peak',measured.peak,flush=True)
    expected=json.loads((ROOT/'handoff'/'data_schema.json').read_text(encoding='utf-8'))['bill_audits']['bill_1403.csv']
    if sha256(ROOT/'data'/'bill_1403.csv')=='a40d065cf7bf0168c34443912318ad5f51e07b8af99a77c351191cbbe828f29d':
        assert audit['rows']==expected['row_count'] and audit['customers']==expected['distinct_customers'] and audit['zero_bill_rows']==expected['zero_consumption_rows'] and audit['same_customer_overlap_pairs']==0
    if args.phase=='measure':
        print('FIRST REAL-DATA SMOKE PILOT, 100 HASH-SELECTED CUSTOMERS',flush=True)
        prof=cProfile.Profile();prof.enable();m=run(ROOT,Config(max_customers=100,checkpoint=False),ROOT/'outputs'/'pilot_100',preloaded=(source,audit));prof.disable()
        buf=io.StringIO();pstats.Stats(prof,stream=buf).strip_dirs().sort_stats('cumtime').print_stats(30);(REVIEW/'first_pilot_profile.txt').write_text(buf.getvalue(),encoding='utf-8')
        print('Measure phase complete. Inspect profile before choosing optimizations.',flush=True);return
    records=[]
    for size in [100,500,2000,10000]:
        print('PROGRESSIVE PILOT',size,flush=True)
        m=run(ROOT,Config(max_customers=size,checkpoint=size==10000),ROOT/'outputs'/f'pilot_{size}',preloaded=(source,audit))
        record=pd.read_csv(ROOT/'outputs'/f'pilot_{size}'/'run_summary.csv').iloc[0].to_dict();record['sample_scope']='universe';record['source_import_reused']=True;records.append(record)
    # Profile a real-cohort scalar oracle before choosing the sequential compiled engine for scale.
    print('REAL-DATA REFERENCE / SCALED EQUALITY',flush=True)
    cfg=Config(max_customers=100,sample_scope='cohort',engine='reference',checkpoint=False)
    selected,classes,info=population(source,cfg);accepted=selected[selected.record_status=='accepted'];origin=int(accepted.start_ordinal.min());end=int(accepted.end_ordinal.max())
    sec,val,meta=read_weather(next((ROOT/'data').glob('open-meteo*.csv')));daily=daily_integral(sec,val,np.arange(origin,end))
    out=ROOT/'outputs'/'reference_equality';out.mkdir(parents=True,exist_ok=True);prof=cProfile.Profile();prof.enable()
    modeled,ref,lookup,diag,X,mask,g=allocate_model(accepted,classes,daily,origin,cfg,out);prof.disable()
    if ref is None: raise RuntimeError('Reference adaptation unexpectedly unavailable')
    fixtures=ROOT/'tests'/'fixtures';fixtures.mkdir(exist_ok=True)
    raw=pd.DataFrame({'SubscriptionNumber':modeled.SubscriptionNumber})
    for column in ['FromDate','ToDate','Consumption','ConsumptionType','UnitCount','Capacity']: raw[column]=modeled['raw_'+column]
    ids={c:f'CUSTOMER_{i+1:03d}' for i,c in enumerate(sorted(raw.SubscriptionNumber.unique()))}
    raw['SubscriptionNumber']=raw.SubscriptionNumber.map(ids);raw.to_csv(fixtures/'cohort_equivalence_bills.csv',index=False)
    daily.to_csv(fixtures/'cohort_equivalence_daily_weather.csv',index=False)
    st=prepare_state(modeled,origin,len(daily));fast=solve(st,X,replace(cfg,engine='scaled'),mask,exposure=g)
    np.testing.assert_allclose(ref.allocations,fast.allocations,atol=cfg.reconciliation_atol,rtol=cfg.reconciliation_rtol);np.testing.assert_allclose(ref.y,fast.y,atol=1e-6,rtol=cfg.reconciliation_rtol)
    buf=io.StringIO();pstats.Stats(prof,stream=buf).strip_dirs().sort_stats('cumtime').print_stats(25);(REVIEW/'reference_profile.txt').write_text(buf.getvalue(),encoding='utf-8')
    write_json(REVIEW/'engine_equivalence.json',{'customers':diag['modeled_customers'],'bills':len(modeled),'interval_days':int(st.offsets[-1]),'same_mode':cfg.mode,'same_features':cfg.feature_preset,'same_fit_mask_and_exposure':True,'reference_seconds_profiled':ref.wall_seconds,'scaled_seconds_warm':fast.wall_seconds,'max_allocation_absolute_difference':float(np.max(np.abs(ref.allocations-fast.allocations))),'max_aggregate_absolute_difference':float(np.max(np.abs(ref.y-fast.y))),'passed':True})
    print('SEPARATELY SELECTED PATH A COHORT PILOT, 10000 CUSTOMERS',flush=True)
    m=run(ROOT,Config(max_customers=10000,sample_scope='cohort'),ROOT/'outputs'/'cohort_pilot_10000',preloaded=(source,audit))
    record=pd.read_csv(ROOT/'outputs'/'cohort_pilot_10000'/'run_summary.csv').iloc[0].to_dict();record['sample_scope']='cohort';record['source_import_reused']=True;records.append(record)
    print('PAPER REFERENCE SMOKE RUN',flush=True)
    run(ROOT,Config(mode='paper_reference',feature_preset='paper_section3_v1',max_customers=100,checkpoint=False),ROOT/'outputs'/'paper_reference_100',preloaded=(source,audit))
    print('REGISTERED REAL-DATA SENSITIVITY',flush=True)
    sensitivity=[]
    for label,changes in [('alpha_001',{'alpha':.01}),('alpha_005',{}),('alpha_010',{'alpha':.1}),('loops_5',{'n_lr_models':5,'n_disagg_cycles':5}),('loops_20',{'n_lr_models':20,'n_disagg_cycles':20}),('boundary_unscaled',{'exposure_scaled':False}),('wind_feature',{'feature_preset':'winter_hdd65_hddw65_v1'})]:
        out=ROOT/'outputs'/('sensitivity_'+label);m=run(ROOT,Config(max_customers=1000,sample_scope='cohort',checkpoint=False,**changes),out,preloaded=(source,audit));a=pd.read_csv(out/'aggregate_daily_summary.csv');sensitivity.append((label,a,m))
    base=next(a for label,a,m in sensitivity if label=='alpha_005');rows=[]
    for label,a,m in sensitivity:
        delta=a.cohort_isd_sum-base.cohort_isd_sum;target=(a.date_gregorian>='2025-01-20')&(a.date_gregorian<'2025-03-21');rows.append({'experiment':label,'target_aggregate_mean_absolute_difference_from_default':float(np.mean(np.abs(delta[target]))),'target_aggregate_max_absolute_difference_from_default':float(np.max(np.abs(delta[target]))),'full_aggregate_max_absolute_difference_from_default':float(np.max(np.abs(delta))),'fallback_reason':m['model_diagnostics']['fallback_reason'],'interpretation':'Sensitivity, not measured error or calibrated uncertainty'})
    pd.DataFrame(rows).to_csv(REVIEW/'sensitivity_comparison.csv',index=False)
    pd.DataFrame(records).to_csv(REVIEW/'benchmark_results.csv',index=False)
    # Small deliberately pseudonymized fixtures; no original ID mapping exported.
    fixtures=ROOT/'tests'/'fixtures';fixtures.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'handoff'/'bill_sample_pseudonymized.csv',fixtures/'bill_relationship_fixture.csv');shutil.copyfile(ROOT/'handoff'/'weather_sample.csv',fixtures/'weather_boundary_fixture.csv')
    (fixtures/'README.md').write_text('Bill IDs replaced with CUSTOMER labels, all selected histories retained; deliberate examples, not representative. Weather metadata/boundary rows are preserved; omitted middle rows are deliberate sample gaps. Use explicit allow_sample=True for bill fixture ingestion. Neither fixture is a production input.',encoding='utf-8')
    # Package only source/docs/tests/fixtures and small aggregate diagnostics, never bulk customer tables.
    for name in ['pilot_100','pilot_500','pilot_2000','pilot_10000','cohort_pilot_10000','paper_reference_100']:
        directory=REVIEW/'pilots'/name;directory.mkdir(parents=True,exist_ok=True)
        for f in ['run_manifest.json','run_summary.csv','aggregate_daily_summary.csv','baseline_comparison.csv','iteration_summary.csv']:
            if (ROOT/'outputs'/name/f).exists():shutil.copyfile(ROOT/'outputs'/name/f,directory/f)
    report=['# Local benchmark report','', 'Source ingestion/audit was performed once and reused for subset runs. Benchmark wall time below includes selection, weather, model, reconciliation and streamed exports; source import/audit timing and full process RSS are recorded separately. Preloaded runs retain the source table, so their peak RSS includes that table. RSS sampling interval is 20 ms. JIT initialization is visible in the smoke measurements; warm times are labeled. Reference cProfile timings include instrumentation overhead. No full production run was performed.','',pd.DataFrame(records).to_markdown(index=False) if __import__('importlib').util.find_spec('tabulate') else pd.DataFrame(records).to_string(index=False),'', 'The initial profiles are preserved. Optimizations keep canonical sequential updates and one global aggregate; batching only affects storage. Review the profile and equivalence JSON for measured evidence. All actual solver runs use complete selected bill intervals. Timing does not imply validated daily accuracy.']
    (REVIEW/'benchmark_report.md').write_text(chr(10).join(report),encoding='utf-8')
    summary=['# Pilot diagnostics and review status','', 'Tests pass; all accepted selected bills reconcile within configured tolerance. No independent local daily truth is available. Synthetic truth scores are labeled separately. Uniform, weather-weighted and non-reconciled OLS diagnostics are distinct from ISD. Real-data comparisons report shape differences and registered sensitivity only.','', 'See pilots/ for manifests with source hashes, configuration, rank, fallback counts, coverage, iterations and stage timings. Actual output paths are outputs/pilot_10000 and outputs/cohort_pilot_10000. No full production run.']
    (REVIEW/'pilot_diagnostics.md').write_text(chr(10).join(summary),encoding='utf-8')
    final_tests=subprocess.run([sys.executable,'-m','pytest','tests','-q','--junitxml='+str(REVIEW/'test_results.xml')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (REVIEW/'test_results.txt').write_text(final_tests.stdout+final_tests.stderr,encoding='utf-8')
    if final_tests.returncode: raise SystemExit('Final tests failed; review not packaged')
    subprocess.run([sys.executable,str(ROOT/'scripts'/'package_review.py')],cwd=ROOT,check=True)
    print('Review execution complete and packaged.',flush=True)

if __name__=='__main__': main()
