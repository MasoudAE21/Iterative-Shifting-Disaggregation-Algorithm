"""Section 3, Eqs. 9, 12, 18-23. One immutable prediction per outer fit.
Reference uses readable NumPy interval updates; scaled uses sequential Numba loops.
No customer batching, parallel sweeps, normal equations, or prediction mutation.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib, json, math, time
import numpy as np
from numba import njit
from .errors import AvailabilityError
from .config import Config
EPS=np.finfo(np.float64).eps

@dataclass
class State:
    starts: np.ndarray
    lengths: np.ndarray
    totals: np.ndarray
    offsets: np.ndarray
    n_days: int
    identity_token: str = ""
    def validate(self):
        if not (len(self.starts)==len(self.lengths)==len(self.totals)==len(self.offsets)-1): raise ValueError('State shape')
        if np.any(self.starts<0) or np.any(self.lengths<=0) or np.any(self.starts+self.lengths>self.n_days): raise ValueError('Interval outside domain')
        if not np.isfinite(self.totals).all() or np.any(self.totals<0): raise ValueError('Invalid total')
        if not np.array_equal(np.diff(self.offsets),self.lengths) or self.offsets[0]!=0: raise ValueError('Offsets')
        return self

@dataclass
class Result:
    allocations: np.ndarray
    y: np.ndarray
    prediction: np.ndarray
    iterations: list
    cycles: list
    zero_residual_noops: int
    all_zero_fast_path: bool
    wall_seconds: float

@njit(cache=True,fastmath=False)
def sum_compensated(x):
    total=0.0; correction=0.0
    for value in x:
        z=value-correction; nxt=total+z; correction=(nxt-total)-z; total=nxt
    return total

@njit(cache=True,fastmath=False)
def aggregate_kernel(a,starts,lengths,offsets,n):
    y=np.zeros(n); correction=np.zeros(n); count=np.zeros(n,np.int64)
    for k in range(len(starts)):
        for j in range(lengths[k]):
            d=starts[k]+j; value=a[offsets[k]+j]; z=value-correction[d]
            nxt=y[d]+z; correction[d]=(nxt-y[d])-z; y[d]=nxt; count[d]+=1
    return y,count

def correct_roundoff(a,total,cfg):
    delta=total-sum_compensated.py_func(a)
    if abs(delta)>cfg.reconciliation_atol+cfg.reconciliation_rtol*abs(total): raise ArithmeticError('Correction exceeds reconciliation threshold')
    k=int(np.argmax(a)); a[k]+=delta
    if not np.isfinite(a).all() or np.any(a<0): raise ArithmeticError('Invalid corrected allocation')
    return a

def interval_update(old,y,p,total,cfg):
    """Hand-checkable Eq. 20-23 update, returning new, restored y, no-op flag."""
    other=y-old
    tol=64*EPS*np.maximum(1,np.maximum(np.abs(y),np.abs(old)))
    if np.any(other < -tol): raise ArithmeticError('Aggregate minus bill is materially negative')
    other=np.maximum(other,0)
    if total==0: new=np.zeros_like(old); noop=False
    else:
        e=np.maximum(p-other,0)
        if not np.isfinite(e).all(): raise ArithmeticError('Nonfinite residual')
        scale=max(1,float(np.max(np.abs(p))),float(np.max(np.abs(other))))
        s=sum_compensated.py_func(e); threshold=64*EPS*len(e)*scale
        noop=s<=threshold
        if noop: new=old.copy()
        else:
            weights=e/np.max(e); z=total*(weights/sum_compensated.py_func(weights))
            new=correct_roundoff((1-cfg.alpha)*old+cfg.alpha*z,total,cfg)
    return new,other+new,noop

def reference_sweep(a,y,p,state,cfg):
    noops=0
    for k in range(len(state.starts)):
        d=int(state.starts[k]); l=int(state.lengths[k]); o=int(state.offsets[k])
        new,restored,noop=interval_update(a[o:o+l].copy(),y[d:d+l],p[d:d+l],state.totals[k],cfg)
        a[o:o+l]=new; y[d:d+l]=restored; noops+=noop
    return int(noops)

@njit(cache=True,fastmath=False)
def scaled_sweep(a,y,p,starts,lengths,totals,offsets,alpha,atol,rtol):
    noops=0
    for k in range(len(starts)):
        l=lengths[k]; d=starts[k]; o=offsets[k]; total=totals[k]
        other=np.empty(l); e=np.empty(l); scale=1.0; maxe=0.0
        for j in range(l):
            old=a[o+j]; yy=y[d+j]; v=yy-old; tol=64*EPS*max(1.0,abs(yy),abs(old))
            if v < -tol: raise ArithmeticError('Aggregate minus bill is materially negative')
            other[j]=max(v,0.0); scale=max(scale,abs(p[d+j]),abs(other[j]))
            e[j]=max(p[d+j]-other[j],0.0); maxe=max(maxe,e[j])
            if not np.isfinite(e[j]): raise ArithmeticError('Nonfinite residual')
        if total==0:
            for j in range(l): a[o+j]=0.0; y[d+j]=other[j]
            continue
        if sum_compensated(e)<=64*EPS*l*scale:
            noops+=1
            for j in range(l): y[d+j]=other[j]+a[o+j]
            continue
        for j in range(l): e[j]/=maxe
        denom=sum_compensated(e)
        for j in range(l): z=total*(e[j]/denom); a[o+j]=(1-alpha)*a[o+j]+alpha*z
        delta=total-sum_compensated(a[o:o+l])
        if abs(delta)>atol+rtol*abs(total): raise ArithmeticError('Correction exceeds threshold')
        largest=0
        for j in range(1,l):
            if a[o+j]>a[o+largest]: largest=j
        a[o+largest]+=delta
        for j in range(l):
            if not np.isfinite(a[o+j]) or a[o+j]<0: raise ArithmeticError('Invalid allocation')
            y[d+j]=other[j]+a[o+j]
    return noops

@njit(cache=True,fastmath=False)
def conservation_kernel(a,totals,offsets,atol,rtol):
    maximum=0.0
    for k in range(len(totals)):
        delta=abs(sum_compensated(a[offsets[k]:offsets[k+1]])-totals[k]); maximum=max(maximum,delta)
        if delta>atol+rtol*abs(totals[k]): raise ArithmeticError('Bill conservation failure')
    for value in a:
        if not np.isfinite(value) or value<0: raise ArithmeticError('Allocation invariant failure')
    return maximum

def initialize(state,cfg,storage=None):
    size=int(state.offsets[-1])
    if storage and size*8>cfg.memmap_threshold_mb*1024**2:
        a=np.memmap(storage,dtype=np.float64,mode='w+',shape=(size,))
    else: a=np.empty(size,dtype=np.float64)
    for k,total in enumerate(state.totals):
        o=int(state.offsets[k]); l=int(state.lengths[k]); a[o:o+l]=total/l
        correct_roundoff(a[o:o+l],total,cfg)
    return a

def lstsq_diagnostics(X,y,mask,cfg):
    fit=X[mask]; response=y[mask]; n,p=fit.shape
    if n==0: raise AvailabilityError('fit_unavailable: No fit rows')
    rcond=cfg.regression_rcond if cfg.regression_rcond is not None else max(n,p)*EPS
    beta,_,rank,singular=np.linalg.lstsq(fit,response,rcond=rcond)
    predicted=X@beta
    if not np.isfinite(beta).all() or not np.isfinite(predicted).all(): raise ArithmeticError('Nonfinite OLS')
    cond=float(singular[0]/singular[-1]) if rank==p else float('inf')
    info={'rank':int(rank),'columns':p,'n_fit':n,'rcond':rcond,'singular_values':singular.tolist(),'condition_number':cond,'condition_number_infinite':not math.isfinite(cond),'residual_norm':float(np.linalg.norm(response-fit@beta)),'column_ranges':[[float(np.min(fit[:,j])),float(np.max(fit[:,j]))] for j in range(p)],'zero_columns':np.flatnonzero(np.all(fit==0,axis=0)).tolist(),'beta':beta.tolist()}
    if cfg.mode=='provisional_cohort_isd' and (rank!=p or n<max(30,5*p) or cond>1e8): raise AvailabilityError('fit_unavailable: rank/count/condition gate')
    return beta,predicted,info

def state_lock(state,X,mask,cfg):
    h=hashlib.sha256(); h.update(state.identity_token.encode())
    for a in [state.starts,state.lengths,state.totals,state.offsets,X,mask]: h.update(np.ascontiguousarray(a).tobytes())
    settings=cfg.as_dict(); settings.pop('resume'); settings.pop('checkpoint'); settings.pop('engine')
    h.update(json.dumps(settings,sort_keys=True).encode()); return h.hexdigest()

def solve(state,X,cfg,fit_mask=None,checkpoint_path=None,storage=None,stop_after_cycles=None,exposure=None):
    start=time.perf_counter(); cfg.validate(); state.validate()
    X=np.asarray(X,dtype=np.float64)
    if X.ndim!=2 or X.shape[0]!=state.n_days or not np.isfinite(X).all(): raise ValueError('Invalid design')
    mask=np.ones(state.n_days,bool) if fit_mask is None else np.asarray(fit_mask,dtype=bool)
    if mask.shape!=(state.n_days,): raise ValueError('Fit mask shape')
    if cfg.mode=='paper_reference' and not mask.all(): raise ValueError('Reference fits all domain days')
    X=X.copy(); X.setflags(write=False); mask=mask.copy(); mask.setflags(write=False)
    lock=state_lock(state,X,mask,cfg); aggregate=aggregate_kernel.py_func if cfg.engine=='reference' else aggregate_kernel
    a=initialize(state,cfg,storage); y,count=aggregate(a,state.starts,state.lengths,state.offsets,state.n_days)
    iterations=[]; cycles=[]; noops=0; resume_data=None
    if cfg.resume:
        if not checkpoint_path or not Path(checkpoint_path).exists(): raise ValueError('No resume checkpoint')
        loaded=np.load(checkpoint_path,allow_pickle=False)
        resume_data={name:loaded[name].copy() for name in loaded.files}
        loaded.close()
        if str(resume_data['lock'])!=lock: raise ValueError('Checkpoint input/design/config mismatch')
        a[:]=resume_data['a']; y=resume_data['y'].copy(); iterations=json.loads(str(resume_data['iterations'])); cycles=json.loads(str(resume_data['cycles'])); noops=int(resume_data['noops'])
    if np.all(state.totals==0):
        return Result(a,y,np.zeros_like(y),[],[],0,True,time.perf_counter()-start)
    executed=0; first_r=int(resume_data['outer']) if resume_data is not None else 0
    for r in range(first_r,cfg.n_lr_models):
        if resume_data is not None and r==first_r:
            beta=resume_data['beta']; p=resume_data['prediction'].copy(); info=json.loads(str(resume_data['fit_info'])); first_j=int(resume_data['next_cycle']); old_y=resume_data['old_y']; old_a=resume_data['old_a']; outer_noops=int(resume_data['outer_noops'])
        else:
            old_y=y.copy(); old_a=a.copy(); outer_noops=0; first_j=0
            beta,p,info=lstsq_diagnostics(X,y,mask,cfg)
        p.setflags(write=False); immutable_hash=hashlib.sha256(p.tobytes()).hexdigest()
        for j in range(first_j,cfg.n_disagg_cycles):
            if cfg.engine=='reference': n=reference_sweep(a,y,p,state,cfg)
            else: n=scaled_sweep(a,y,p,state.starts,state.lengths,state.totals,state.offsets,cfg.alpha,cfg.reconciliation_atol,cfg.reconciliation_rtol)
            noops+=n; outer_noops+=n
            max_bill=conservation_kernel(a,state.totals,state.offsets,cfg.reconciliation_atol,cfg.reconciliation_rtol)
            checked,count=aggregate(a,state.starts,state.lengths,state.offsets,state.n_days)
            discrepancy=np.abs(checked-y); gamma=count*EPS/(1-count*EPS); bound=gamma*np.abs(checked)+count*cfg.reconciliation_atol
            if np.any(discrepancy>bound): raise ArithmeticError('Aggregate drift exceeds summation bound')
            if hashlib.sha256(p.tobytes()).hexdigest()!=immutable_hash: raise ArithmeticError('Prediction mutated')
            y=checked
            cycles.append({'outer':r,'cycle':j,'zero_residual_noops':int(n),'max_bill_abs_error':float(max_bill),'max_aggregate_discrepancy':float(discrepancy.max()),'max_aggregate_bound':float(bound.max())})
            executed+=1
            if cfg.checkpoint and checkpoint_path:
                tmp=Path(str(checkpoint_path)+'.tmp')
                with tmp.open('wb') as f: np.savez(f,lock=lock,a=a,y=y,prediction=p,beta=beta,outer=r,next_cycle=j+1,old_y=old_y,old_a=old_a,outer_noops=outer_noops,noops=noops,iterations=json.dumps(iterations),cycles=json.dumps(cycles),fit_info=json.dumps(info),fit_mask=mask,design=X,g=np.ones(state.n_days) if exposure is None else exposure,source_order_identity=state.identity_token,config_json=json.dumps(cfg.as_dict()))
                tmp.replace(checkpoint_path)
            if stop_after_cycles and executed>=stop_after_cycles: return Result(a,y,p,iterations,cycles,noops,False,time.perf_counter()-start)
        diff_y=y-old_y; diff_a=a-old_a
        info.update({'outer':r,'max_y_change_fit':float(np.max(np.abs(diff_y[mask]))),'relative_y_change_fit':float(np.linalg.norm(diff_y[mask])/max(np.linalg.norm(old_y[mask]),EPS)),'max_allocation_change':float(np.max(np.abs(diff_a))),'relative_allocation_change':float(np.linalg.norm(diff_a)/max(np.linalg.norm(old_a),EPS)),'negative_predicted_days':int(np.sum(p<0)),'zero_residual_noops':outer_noops,'final_fit_residual_norm':float(np.linalg.norm(y[mask]-p[mask]))})
        iterations.append(info)
        resume_data=None
    return Result(a,y,p,iterations,cycles,noops,False,time.perf_counter()-start)
