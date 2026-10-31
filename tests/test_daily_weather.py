from dataclasses import replace
import numpy as np
import pytest
from isd.weather import read_weather, daily_integral, build_design
from isd.bill_window import resolve_window
from isd.data import date_ordinal, calendar_check
from isd.config import Config

def source(tmp_path, rows='2025-01-02,3,16.09344\n2025-01-03,5,20\n'):
    p=tmp_path/'daily.csv'
    p.write_text('latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n34,50,1333,0,GMT,GMT\n\ntime,apparent_temperature_mean (°C),wind_speed_10m_max (km/h)\n'+rows,encoding='utf-8')
    return p

def test_daily_values_are_not_integrated_or_relabelled(tmp_path):
    seconds, values, meta=read_weather(source(tmp_path))
    start=date_ordinal('2025-01-02')
    daily=daily_integral(seconds,values,np.arange(start,start+3))
    assert daily.apparent_temperature_mean_C.iloc[:2].tolist()==[3,5]
    assert daily.wind_max_mph.iloc[0]==pytest.approx(10)
    assert 'temperature_mean_C' not in daily and 'wind_mean_kmh' not in daily
    assert daily.weather_status.tolist()==['complete','complete','unavailable']
    assert resolve_window(seconds,values,Config())==(start,start+2)
    assert meta['elevation']=='1333'
    with pytest.raises(ValueError,match='explicit apparent'):
        build_design(daily.iloc[:2],'winter_hdd65_v1',np.ones(2,bool),'provisional_cohort_isd',np.ones(2))
    design, metadata=build_design(daily.iloc[:2],'daily_apparent_hdd65_v1',np.ones(2,bool),'provisional_cohort_isd',np.ones(2))
    assert np.isfinite(design).all()
    assert metadata['temperature_basis']=='daily_mean_apparent'

@pytest.mark.parametrize('rows', ['2025-01-02,3,10\n2025-01-02,5,20\n','2025-01-02,3,-1\n'])
def test_bad_daily_values_rejected(tmp_path,rows):
    with pytest.raises(ValueError):read_weather(source(tmp_path,rows))

def test_daily_gap_is_not_filled(tmp_path):
    sec,val,_=read_weather(source(tmp_path,'2025-01-02,3,10\n2025-01-04,4,12\n'))
    with pytest.raises(ValueError,match='internal gaps'):resolve_window(sec,val,Config())

def test_confirmed_target_has_58_days():
    cfg=replace(Config(),target_start='2025-01-02',target_end_exclusive='2025-03-01',target_year_confirmed=True)
    assert calendar_check(cfg)['days']==58
