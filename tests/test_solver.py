import math
from dataclasses import replace
import numpy as np
import pytest
from isd.config import Config
from isd.solver import State,solve,interval_update,reference_sweep,scaled_sweep,lstsq_diagnostics,initialize,aggregate_kernel

def cfg(**kw): return Config(mode='paper_reference',feature_preset='paper_section3_v1',checkpoint=False,engine='reference',**kw)
def state(starts,lengths,totals,n):
    return State(np.array(starts,np.int64),np.array(lengths,np.int64),np.array(totals,float),np.r_[0,np.cumsum(lengths)].astype(np.int64),n)

def test_hand_calculated_update():
    new,y,noop=interval_update(np.array([3.,3.]),np.array([5.,7.]),np.array([7.,5.]),6,cfg())
    np.testing.assert_allclose(new,[3.1,2.9],rtol=0,atol=1e-14); np.testing.assert_allclose(y,[5.1,6.9]); assert not noop

def test_sequential_latest_aggregate():
    st=state([0,0],[2,2],[6,6],2); c=cfg(alpha=1)
    a=initialize(st,c); y,_=aggregate_kernel(a,st.starts,st.lengths,st.offsets,2); prediction=np.array([8.,4.]); prediction.setflags(write=False)
    reference_sweep(a,y,prediction,st,c)
    np.testing.assert_allclose(a,[5,1,3,3]); np.testing.assert_allclose(y,[8,4]); np.testing.assert_array_equal(prediction,[8,4])

@pytest.mark.parametrize('alpha',[0.,.05,1.])
def test_conservation_zero_single_adjacent_cross_customer_overlaps(alpha):
    st=state([0,2,0,4],[2,2,4,1],[6,0,20,3],5)
    X=np.column_stack([np.ones(5),[4,0,2,7,1]])
    r=solve(st,X,cfg(alpha=alpha,n_lr_models=3,n_disagg_cycles=4))
    assert np.all(r.allocations>=0); np.testing.assert_array_equal(r.allocations[2:4],[0,0]); assert r.allocations[-1]==3
    for k,b in enumerate(st.totals): assert math.fsum(r.allocations[st.offsets[k]:st.offsets[k+1]])==pytest.approx(b,abs=1e-12)
    checked,_=aggregate_kernel(r.allocations,st.starts,st.lengths,st.offsets,5); np.testing.assert_allclose(r.y,checked)
    assert len(r.iterations)==3 and len(r.cycles)==12
    if alpha==0: np.testing.assert_allclose(r.allocations,initialize(st,cfg()))

def test_zero_residual_keeps_current_nonuniform():
    old=np.array([1.,5.]); new,y,noop=interval_update(old,np.array([3.,9.]),np.array([-1.,0.]),6,cfg())
    assert noop; np.testing.assert_array_equal(new,old); np.testing.assert_array_equal(y,[3,9])
    new,_,noop=interval_update(old,np.array([1.,5.]),np.full(2,1e-16),6,cfg()); assert noop

@pytest.mark.parametrize('engine',['reference','scaled'])
def test_all_zero_no_regression(engine):
    st=state([0,1],[3,2],[0,0],3)
    r=solve(st,np.ones((3,1)),replace(cfg(),engine=engine))
    assert r.all_zero_fast_path and not r.iterations; np.testing.assert_array_equal(r.y,[0,0,0])

def test_rank_deficiency_minimum_norm_and_adapted_rejection():
    X=np.column_stack([np.ones(40),np.ones(40)*10,np.zeros(40)])
    b,p,d=lstsq_diagnostics(X,np.arange(40.),np.ones(40,bool),cfg())
    assert d['rank']==1 and math.isinf(d['condition_number']) and d['zero_columns']==[2]; assert np.isfinite(p).all()
    with pytest.raises(ValueError,match='fit_unavailable'): lstsq_diagnostics(X,np.arange(40.),np.ones(40,bool),Config())
    with pytest.raises(ValueError,match='fit_unavailable'): lstsq_diagnostics(np.ones((5,1)),np.ones(5),np.ones(5,bool),Config(feature_preset='intercept_only_v1'))
    X=np.column_stack([np.ones(40),np.linspace(0,1,40),np.linspace(0,1,40)+1e-13*np.sin(np.arange(40))])
    with pytest.raises(ValueError,match='fit_unavailable'): lstsq_diagnostics(X,np.arange(40.),np.ones(40,bool),Config())

def test_materially_negative_other_fails():
    with pytest.raises(ArithmeticError): interval_update(np.array([4.]),np.array([3.]),np.array([2.]),4,cfg())

def test_reference_scaled_and_checkpoint_resume(tmp_path):
    st=state([0,3,1,4],[3,4,3,3],[7,11,9,0],7); X=np.column_stack([np.ones(7),[4,0,8,1,9,3,2]])
    c=cfg(n_lr_models=3,n_disagg_cycles=3); ref=solve(st,X,c)
    scaled=solve(st,X,replace(c,engine='scaled')); np.testing.assert_allclose(scaled.allocations,ref.allocations,atol=1e-10,rtol=1e-10)
    ck=tmp_path/'checkpoint.npz'; solve(st,X,replace(c,checkpoint=True),checkpoint_path=ck,stop_after_cycles=4)
    resumed=solve(st,X,replace(c,checkpoint=True,resume=True),checkpoint_path=ck)
    np.testing.assert_array_equal(resumed.allocations,ref.allocations); np.testing.assert_array_equal(resumed.y,ref.y); assert len(resumed.iterations)==3 and len(resumed.cycles)==9
    with pytest.raises(ValueError,match='mismatch'): solve(st,X,replace(c,checkpoint=True,resume=True,alpha=.1),checkpoint_path=ck)

def test_adapted_engine_equivalence_and_exposure():
    n=60; st=state([0,20,0],[20,40,60],[40,80,100],n); mask=np.ones(n,bool)
    X=np.column_stack([np.ones(n),np.sin(np.arange(n)/3)])
    c=Config(engine='reference',checkpoint=False,n_lr_models=2,n_disagg_cycles=2)
    ref=solve(st,X,c,mask); fast=solve(st,X,replace(c,engine='scaled'),mask)
    np.testing.assert_allclose(ref.allocations,fast.allocations,atol=1e-8,rtol=1e-10)


def test_known_truth_experiments_are_finite_and_separately_labeled():
    from isd.experiments import synthetic_experiment
    report=synthetic_experiment()
    assert len(report)==12 and report.scenario.nunique()==4
    assert np.isfinite(report.aggregate_wape).all()
    assert (report.zero_only_customers==1).all()
    assert report.truth_source.str.startswith('Known synthetic').all()


def test_extremely_small_residuals_preserve_arithmetic_equivalence():
    n=40; count=80; totals=np.linspace(1,900,count); st=state([0]*count,[n]*count,totals,n)
    X=np.column_stack([np.ones(n),np.sin(np.arange(n)/7)])
    c=cfg(n_lr_models=10,n_disagg_cycles=10); ref=solve(st,X,c); fast=solve(st,X,replace(c,engine='scaled'))
    np.testing.assert_allclose(ref.allocations,fast.allocations,atol=1e-8,rtol=1e-10)
