"""Fixed complete-coverage population peak and same-day customer export."""
from collections import Counter
from datetime import date, timedelta
import csv, json, math
import numpy as np
import pyarrow.parquet as pq


def choose_peak(dates, totals):
    if len(dates)==0 or not np.isfinite(totals).all() or np.any(np.asarray(totals)<0):
        raise ValueError('No valid peak totals')
    return min(range(len(dates)),key=lambda i:(-totals[i],dates[i]))


def export_peak(out, classes, cfg):
    dates=[date.fromisoformat(cfg.target_start)+timedelta(days=i) for i in range((date.fromisoformat(cfg.target_end_exclusive)-date.fromisoformat(cfg.target_start)).days)]
    population={str(c) for c,(kind,_) in classes.items() if kind=='full'}
    if not population: raise ValueError('No complete-coverage customers for peak selection')
    totals=np.zeros(len(dates)); compensation=np.zeros(len(dates)); counts=np.zeros(len(dates),dtype=np.int64)
    index={d:i for i,d in enumerate(dates)}
    path=out/'target_customer_daily.parquet'
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536,columns=['SubscriptionNumber','date_gregorian','estimated_consumption']):
        rows=batch.to_pydict()
        for ident,day,value in zip(*rows.values()):
            if ident not in population: continue
            if value is None or not math.isfinite(value) or value<0: raise ArithmeticError('Invalid peak population estimate')
            i=index[day]; y=value-compensation[i]; t=totals[i]+y; compensation[i]=(t-totals[i])-y; totals[i]=t; counts[i]+=1
    if not np.all(counts==len(population)): raise ArithmeticError('Peak population coverage mismatch')
    peak_index=choose_peak(dates,totals); peak_day=dates[peak_index]
    with (out/'peak_daily_totals.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f); writer.writerow(['date','estimated_daily_total','peak_selection_customers'])
        writer.writerows((d.isoformat(),repr(float(t)),len(population)) for d,t in zip(dates,totals))
    selected=pq.read_table(path,filters=[('date_gregorian','=',peak_day)],columns=['SubscriptionNumber','estimated_consumption','reason']).to_pydict()
    ids=selected['SubscriptionNumber']; values=selected['estimated_consumption']
    if len(ids)!=len(classes) or len(set(ids))!=len(ids) or set(ids)!=set(classes): raise ArithmeticError('Peak export customer identity mismatch')
    reasons=Counter(); peak_values=[]; available=zero=0
    with (out/'customer_peak_consumption.csv').open('w',newline='',encoding='utf-8') as f, (out/'peak_missing_reasons.csv').open('w',newline='',encoding='utf-8') as missing:
        writer=csv.writer(f); writer.writerow(['SubscriptionNumber','peakCosumptionValue'])
        mw=csv.writer(missing); mw.writerow(['SubscriptionNumber','reason'])
        for ident,value,reason in zip(ids,values,selected['reason']):
            if value is None:
                reasons[reason]+=1; mw.writerow([ident,reason]); text=''
            else:
                if not math.isfinite(value) or value<0: raise ArithmeticError('Invalid peak output value')
                text=repr(float(value)); available+=1; zero+=value==0
                if ident in population: peak_values.append(float(text))
            writer.writerow([ident,text])
    reconciled=math.fsum(peak_values)
    if not math.isclose(reconciled,float(totals[peak_index]),rel_tol=1e-14,abs_tol=1e-8): raise ArithmeticError('Peak CSV reconciliation')
    with (out/'customer_peak_consumption.csv').open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=['SubscriptionNumber','peakCosumptionValue']: raise ArithmeticError('Peak CSV header')
        exported=list(reader)
    if [r['SubscriptionNumber'] for r in exported]!=ids: raise ArithmeticError('CSV ID roundtrip')
    for row,value in zip(exported,values):
        if (row['peakCosumptionValue']=='' if value is None else float(row['peakCosumptionValue'])==value): continue
        raise ArithmeticError('CSV value roundtrip')
    return {'date':peak_day.isoformat(),'total':float(totals[peak_index]),'population_customers':len(population),'output_customers':len(ids),'available_values':available,'valid_zeros':int(zero),'missing_values':sum(reasons.values()),'missing_reasons':dict(reasons),'top_five':[{'date':dates[i].isoformat(),'total':float(totals[i])} for i in sorted(range(len(dates)),key=lambda i:(-totals[i],dates[i]))[:5]],'csv_population_sum':reconciled,'csv_integrity_passed':True,'rounding':'Shortest round-trip float64 decimal (Python repr); no fixed decimal rounding. Compensated float64 totals select the peak before export.','policy':'Fixed full-target valid-billing population; exact ties choose earliest date. All output customers use that same date.'}


def write_peak_summary(out, manifest):
    p=manifest['peak']; c=manifest['configuration']; a=manifest['source_audit']; e=manifest['export']
    lines=['# Modeled population daily peak', '',f"Target: {c['target_start']} through {date.fromisoformat(c['target_end_exclusive'])-timedelta(days=1)}, inclusive; Asia/Tehran civil days.",f"Selected date: **{p['date']}**. Units: **{c['consumption_unit']} per day**, preserving original bill totals without conversion.",f"Input: {a['customers']:,} distinct customers, {a['rows']:,} bills. Selected output: {p['output_customers']:,} customers; accepted/fully reconciled bills: {e['bill_reconciliation_passed']:,}.",f"Fixed peak-selection population: {p['population_customers']:,} fully covered customers. Source coverage: {manifest['selection']['source_coverage_counts']}. This is a modeled population peak, not a full-city peak.",f"Peak total: {p['total']!r}. Exported population sum: {p['csv_population_sum']!r}.",'', '## Highest five daily totals','']
    lines += [f"- {r['date']}: {r['total']!r}" for r in p['top_five']]
    lines += ['',f"Missing output values: {p['missing_values']:,}; reasons: {p['missing_reasons']}. Customer-level reasons are in peak_missing_reasons.csv. Available: {p['available_values']:,}; retained zeros: {p['valid_zeros']:,}.",p['policy'],p['rounding'],'','## Verification and review',f"Full-bill reconciliation passed: {e['bill_reconciliation_passed']:,}; maximum absolute discrepancy: {e['max_bill_abs_discrepancy']!r}. Full/target identities passed: {e['full_target_export_identities_passed']}. CSV identity, unique row, finite nonnegative value and round-trip reconciliation checks passed: {p['csv_integrity_passed']}.",'Review F1: narrowly classified availability fallback; operational/checkpoint/configuration errors propagate. F2: advancing bill cursor replaces retained customer DataFrames. F3: reject blank/whitespace and multiline physical CSV records before normalization. See handoff/peak_review_resolutions.md and verification artifacts.','Optional O1–O3 are deferred: the current target remains 1403, metadata remains provisional and RSS measurement is available locally.','No measured daily accuracy is claimed. Existing cohort ISD, exposure adaptation, uniform full-bill fallback and missing-value policies remain unchanged. Physical units, billing semantics, weather representativeness and customer daily accuracy remain unconfirmed. No hourly conversion, external data or city scaling was applied.','','## Runtime and reproducibility',f"Wall seconds: {manifest['wall_seconds']:.6f}; peak process RSS bytes: {manifest['peak_rss_bytes']:,}.",f"Stage times: {manifest['stage_wall_seconds']}",'Run from the IDE with run_pipeline.py; defaults select all available input customers. production=False retains the provisional semantic gates.','Configuration and hashes (SHA256):','```json',json.dumps({'configuration':c,'inputs':manifest['inputs'],'source':manifest['code'],'dependencies':manifest['dependencies']},indent=2),'```']
    (out/'peak_summary.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
