"""Experiments with synthetic truth are distinct from real-data plausibility."""
from dataclasses import replace
import math
import numpy as np
import pandas as pd
from .config import Config
from .solver import State,solve,initialize,correct_roundoff

def synthetic_experiment(seed=17):
    rng=np.random.default_rng(seed); n=90; customers=24; weather=np.maximum(18+15*np.sin(np.arange(n)/8)+5*np.cos(np.arange(n)/3),0)
    report=[]
    for scenario in ['common_noiseless','heterogeneous_high_weather','weak_weather','synchronized_identical_bill_information']:
        truth=[]; starts=[]; lengths=[]; totals=[]; owners=[]
        for c in range(customers):
            if scenario=='common_noiseless': q=(c+1)/10*(1+weather)
            elif scenario=='heterogeneous_high_weather':
                q=np.maximum(0,rng.uniform(1,5)+rng.uniform(.2,2)*weather+rng.normal(0,2,n)); q[n//2:]*=rng.uniform(.4,1.3)
            elif scenario=='weak_weather': q=np.maximum(0,rng.uniform(10,20)+rng.normal(0,5,n))
            else:
                q=10+8*np.sin(np.arange(n)*2*np.pi/15+(c%2)*np.pi)
            if c==0: q=np.zeros(n)
            truth.append(q); d=0
            while d<n:
                l=min(15 if scenario=='synchronized_identical_bill_information' else int(rng.integers(7,23)),n-d)
                starts.append(d); lengths.append(l); totals.append(math.fsum(q[d:d+l])); owners.append(c); d+=l
        truth=np.array(truth); offsets=np.r_[0,np.cumsum(lengths)].astype(np.int64)
        st=State(np.array(starts,np.int64),np.array(lengths,np.int64),np.array(totals,float),offsets,n)
        cfg=Config(mode='paper_reference',feature_preset='paper_section3_v1',checkpoint=False)
        X=np.column_stack([np.ones(n),weather]); r=solve(st,X,cfg); uniform=initialize(st,cfg)
        weighted=np.empty_like(uniform)
        for k,total in enumerate(totals):
            d=starts[k];l=lengths[k];w=1+weather[d:d+l];weighted[offsets[k]:offsets[k+1]]=correct_roundoff(total*w/math.fsum(w),total,cfg)
        for method,a in [('isd_reference_equations',r.allocations),('uniform',uniform),('weather_weighted',weighted)]:
            estimate=np.zeros_like(truth)
            for k,c in enumerate(owners): estimate[c,starts[k]:starts[k]+lengths[k]]=a[offsets[k]:offsets[k+1]]
            total_true=truth.sum(axis=0); total_est=estimate.sum(axis=0); e=total_est-total_true
            denominator=total_true.sum(); positive=truth.sum(axis=1)>0
            individual_wape=np.sum(np.abs(estimate-truth),axis=1)[positive]/truth.sum(axis=1)[positive]
            report.append({'scenario':scenario,'method':method,'aggregate_mae':float(np.mean(np.abs(e))),'aggregate_rmse':float(np.sqrt(np.mean(e**2))),'aggregate_wape':float(np.abs(e).sum()/denominator) if denominator else None,'signed_bias':float(np.mean(e)),'peak_day_absolute_error':float(abs(total_est[np.argmax(total_true)]-total_true.max())),'peak_day_timing_error_days':int(np.argmax(total_est)-np.argmax(total_true)),'customer_mean_mae':float(np.mean(np.abs(estimate-truth))),'customer_median_wape_positive_only':float(np.median(individual_wape)),'customer_p90_wape_positive_only':float(np.percentile(individual_wape,90)),'zero_only_customers':int(np.sum(~positive)),'truth_source':'Known synthetic daily values; not evidence about local daily accuracy'})
    return pd.DataFrame(report)
