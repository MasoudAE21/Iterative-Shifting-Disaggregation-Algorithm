"""Self-contained regression fixture: pseudonymized complete real bill histories."""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from isd.config import Config
from isd.data import normalize_frame,audit_normalized,prepare_state,date_ordinal
from isd.weather import build_design
from isd.solver import solve

def test_pseudonymized_real_fixture_reference_scaled():
    fixture=Path(__file__).parent/'fixtures'
    raw=pd.read_csv(fixture/'cohort_equivalence_bills.csv',dtype=str,keep_default_na=False)
    bills,_=audit_normalized(normalize_frame(raw,allow_sample=True))
    bills=bills.sort_values(['SubscriptionNumber','start_ordinal','end_ordinal','bill_id']).reset_index(drop=True)
    daily=pd.read_csv(fixture/'cohort_equivalence_daily_weather.csv')
    origin=date_ordinal(daily.date_gregorian.iloc[0]);n=len(daily);counts=np.zeros(n,dtype=int)
    for a,b in zip(bills.start_ordinal.astype(int),bills.end_ordinal.astype(int)): counts[a-origin:b-origin]+=1
    g=counts/bills.SubscriptionNumber.nunique();days=np.arange(origin,origin+n);mask=(days>=date_ordinal('2025-01-20'))&(days<date_ordinal('2025-03-21'))
    c=Config(engine='reference',checkpoint=False)
    X,metadata=build_design(daily,c.feature_preset,mask,c.mode,g)
    state=prepare_state(bills,origin,n);ref=solve(state,X,c,mask);fast=solve(state,X,replace(c,engine='scaled'),mask)
    assert bills.SubscriptionNumber.nunique()==100 and len(bills)==198
    np.testing.assert_allclose(ref.allocations,fast.allocations,atol=1e-8,rtol=1e-10)
    np.testing.assert_array_equal(ref.y,fast.y)
