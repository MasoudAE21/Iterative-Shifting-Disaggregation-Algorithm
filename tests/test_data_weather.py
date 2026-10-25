from dataclasses import replace
from datetime import datetime,timezone,timedelta
import csv
import numpy as np
import pandas as pd
import pytest
from isd.config import Config
from isd.data import COLUMNS,normalize_frame,audit_normalized,coverage_classes,date_ordinal,calendar_check,jalali_date
from isd.weather import daily_integral,weather_features,build_design

def frame(rows): return pd.DataFrame(rows,columns=COLUMNS)
def row(c,a,b,total): return [c,a,b,str(total),'40','1','6']


def test_prepare_state_verbose_sample_preserves_state(tmp_path):
    import json
    from isd.data import prepare_state

    bills = normalize_frame(frame([
        row('00000000001', '2025-01-20', '2025-01-22', 30),
        row('00000000002', '2025-01-21', '2025-01-22', 0),
        row('00000000003', '2025-01-20', '2025-01-20', 5),
    ]))
    origin = date_ordinal('2025-01-20')
    path = tmp_path / 'nested' / 'state.json'
    quiet = prepare_state(bills, origin, 3, sample_path=path)
    assert not path.exists()
    verbose = prepare_state(bills, origin, 3, verbose=True, sample_path=path, sample_size=2)
    for name in ('starts', 'lengths', 'totals', 'offsets'):
        np.testing.assert_array_equal(getattr(quiet, name), getattr(verbose, name))
    assert quiet.identity_token == verbose.identity_token
    sample = json.loads(path.read_text(encoding='utf-8'))
    assert sample['total_bills'] == 3 and sample['sample_bill_count'] == 2
    assert sample['total_allocation_values'] == 6
    assert sample['sample_arrays'] == {
        'starts': [0, 1], 'lengths': [3, 2], 'totals': [30., 0.], 'offsets': [0, 3, 5],
    }
    assert sample['bills'][1]['SubscriptionNumber'] == '00000000002'
    assert sample['bills'][1]['start_date'] == '2025-01-21'
    assert sample['bills'][1]['end_date_exclusive'] == '2025-01-23'
    assert sample['bills'][1]['allocation_offset_start'] == 3
    prepare_state(bills, origin, 3, verbose=True, sample_path=path, sample_size=10)
    assert json.loads(path.read_text())['sample_bill_count'] == 3


def test_prepare_state_verbose_invalid_sample_size_does_not_write(tmp_path):
    from isd.data import prepare_state

    bills = normalize_frame(frame([row('00000000001', '2025-01-20', '2025-01-20', 1)]))
    path = tmp_path / 'state.json'
    for size in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match='sample_size'):
            prepare_state(bills, date_ordinal('2025-01-20'), 1,
                          verbose=True, sample_path=path, sample_size=size)
    assert not path.exists()
def test_ids_dates_source_rows_and_chunk_stability():
    raw=frame([row('00000000001','2025-01-20','2025-01-20',0),row('00000000002','2025-01-21','2025-01-23',9)])
    whole=normalize_frame(raw,'hash'); a=normalize_frame(raw.iloc[:1],'hash'); b=normalize_frame(raw.iloc[1:],'hash',row_start=3)
    assert whole.SubscriptionNumber.iloc[0]=='00000000001'; assert whole.source_row.tolist()==[2,3]; assert whole.bill_id.tolist()==a.bill_id.tolist()+b.bill_id.tolist(); assert whole.day_count.tolist()==[1,3]
    shuffled=whole.sample(frac=1,random_state=5).sort_values(['SubscriptionNumber','start_ordinal','end_ordinal','bill_id'])
    assert shuffled.bill_id.tolist()==whole.bill_id.tolist()

@pytest.mark.parametrize('a,b,total',[('01/20/2025','2025-01-21','5'),('2025-02-30','2025-03-01','5'),('2025-03-02','2025-03-01','5'),('2025-01-20','2025-01-21','-1'),('2025-01-20','2025-01-21','NaN')])
def test_invalid_quarantine(a,b,total):
    df=normalize_frame(frame([row('00000000001',a,b,total)])); audited,ledger=audit_normalized(df)
    assert audited.record_status.iloc[0]!='accepted'; assert ledger['invalid_rows']==1

def test_adjacent_overlap_duplicate_missing_policy():
    rows=[row('00000000001','2025-01-20','2025-02-10',10),row('00000000001','2025-02-11','2025-03-20',20),row('00000000002','2025-02-01','2025-02-10',0),row('00000000003','2025-01-20','2025-02-10',5),row('00000000003','2025-02-10','2025-03-20',6),row('00000000004','2025-04-01','2025-04-02',3)]
    df,ledger=audit_normalized(normalize_frame(frame(rows))); classes=coverage_classes(df,date_ordinal('2025-01-20'),date_ordinal('2025-03-21'))
    assert classes['00000000001']==('full',60); assert classes['00000000002']==('partial',10); assert classes['00000000003']==('none',0); assert classes['00000000004']==('none',0)
    assert ledger['same_customer_overlap_pairs']==1
    duplicate=normalize_frame(frame([rows[0],rows[0]])); d,stats=audit_normalized(duplicate); assert not (d.record_status=='accepted').any()
    d,stats=audit_normalized(duplicate,deduplicate_confirmed=True); assert (d.record_status=='accepted').sum()==1 and stats['record_status_counts']['removed_exact_duplicate']==1

def test_target_calendar_year_mapping_and_60_dates():
    info=calendar_check(Config()); assert info['days']==60 and not info['intended_year_confirmed']
    assert jalali_date(date_ordinal('2025-01-20'))=='1403-11-01'; assert jalali_date(date_ordinal('2025-03-20'))=='1403-12-30'
    with pytest.raises(ValueError): calendar_check(Config(target_start='2024-01-20'))
    with pytest.raises(ValueError,match='Production'): Config(production=True).validate()

def hourly_linear():
    start=datetime(2025,1,19,19,tzinfo=timezone.utc).timestamp(); seconds=start+np.arange(28)*3600
    t=(seconds-start)/3600; values=np.column_stack([t,100+t,np.full(28,12.874752)])
    return seconds,values

def test_weather_half_hour_boundary_integral_and_units():
    seconds,values=hourly_linear(); daily=daily_integral(seconds,values,[date_ordinal('2025-01-20')])
    assert daily.weather_status.iloc[0]=='complete'; assert daily.temperature_mean_C.iloc[0]==pytest.approx(13.5); assert daily.apparent_temperature_mean_C.iloc[0]==pytest.approx(113.5)
    assert daily.wind_mean_mph.iloc[0]==pytest.approx(8); assert daily.utc_day_start.iloc[0]=='2025-01-19T20:30:00+00:00'; assert daily.coverage_seconds.iloc[0]==86400
    features=weather_features(daily); assert features['HDD65'][0]==pytest.approx(65-(1.8*13.5+32)); assert features['HDDW65'][0]==pytest.approx(features['HDD65'][0])

@pytest.mark.parametrize('case',['missing_internal','missing_start','missing_end'])
def test_weather_missing_not_extrapolated(case):
    seconds,values=hourly_linear()
    index=np.arange(len(seconds)); index=np.delete(index,10) if case=='missing_internal' else index[3:] if case=='missing_start' else index[:-3]
    result=daily_integral(seconds[index],values[index],[date_ordinal('2025-01-20')]); assert result.weather_status.iloc[0]=='unavailable'; assert np.isnan(result.temperature_mean_C.iloc[0])

def test_wind_threshold_and_transform_after_mean():
    daily=pd.DataFrame({'temperature_mean_F':[30,30,30,65],'wind_mean_mph':[0,8,16,0]})
    f=weather_features(daily); np.testing.assert_allclose(f['HDDW65'][:3]/f['HDD65'][:3],[.95,1,1.1]); assert f['HDD65'][3]==0
    # Mean of threshold-crossing hourly HDD differs from transformation of daily mean.
    assert np.mean(np.maximum(65-np.array([60,70]),0))==2.5; assert f['HDD65'][3]!=2.5

def test_adapted_center_then_exposure():
    daily=pd.DataFrame({'temperature_mean_F':np.arange(60)+20.,'wind_mean_mph':np.ones(60)})
    mask=np.arange(60)<40; g=np.r_[np.ones(40),np.full(20,.5)]
    X,meta=build_design(daily,'winter_hdd65_v1',mask,'provisional_cohort_isd',g)
    assert X[0,0]==1 and X[-1,0]==.5; assert np.mean(X[mask,1])==pytest.approx(0,abs=1e-15); assert np.std(X[mask,1])==pytest.approx(1)
    U,_=build_design(daily,'winter_hdd65_v1',mask,'provisional_cohort_isd',g,False); np.testing.assert_allclose(X[40:],U[40:]*.5)


def test_array_traversal_matches_original_group_oracle():
    from isd import data_reference
    rows=[row('00000000001','2025-01-20','2025-02-10',10),row('00000000001','2025-02-11','2025-03-20',20),row('00000000002','2025-01-01','2025-01-05',2),row('00000000002','2025-01-07','2025-02-10',5),row('00000000003','2025-01-20','2025-02-20',5),row('00000000003','2025-02-01','2025-03-20',6)]
    raw=normalize_frame(frame(rows)); new,a=audit_normalized(raw); old,b=data_reference.audit_normalized(raw)
    assert {key: a[key] for key in b} == b; assert a['internal_target_gap_customers'] == 0
    assert new.record_status.tolist()==old.record_status.tolist()
    lo,hi=date_ordinal('2025-01-20'),date_ordinal('2025-03-21')
    assert coverage_classes(new,lo,hi)==data_reference.coverage_classes(old,lo,hi)
    assert isinstance(new.ConsumptionType.iloc[0],str)


@pytest.mark.parametrize('first_end,second_start,invalid', [
    ('2025-02-01', '2025-02-03', True),   # One missing target day.
    ('2025-01-19', '2025-01-21', True),   # Gap includes target start.
    ('2025-03-19', '2025-03-21', True),   # Gap includes last target day.
    ('2025-01-18', '2025-01-20', False),  # Gap ends at target start.
    ('2025-03-20', '2025-03-22', False),  # Gap starts at target end.
    ('2025-02-01', '2025-02-02', False),  # Adjacent bills.
    ('2025-01-10', '2025-04-01', True),   # Gap spans entire target.
])
def test_internal_target_gap_quarantines_history(first_end, second_start, invalid):
    rows = [row('00000000001', '2025-01-01', first_end, 10),
            row('00000000001', second_start, '2025-04-10', 20)]
    audited, ledger = audit_normalized(normalize_frame(frame(rows)))
    assert ledger['internal_target_gap_customers'] == int(invalid)
    if invalid:
        assert (audited.record_status == 'quarantined_customer').all()
        assert (audited.exclusion_reason == 'internal_target_gap').all()
        classes = coverage_classes(audited, date_ordinal('2025-01-20'), date_ordinal('2025-03-21'))
        assert classes['00000000001'] == ('none', 0)
    else:
        assert (audited.record_status == 'accepted').all()


def test_gap_policy_uses_ingestion_config_and_keeps_edge_missing_partial(tmp_path):
    from isd.data import read_bills
    rows = [row('00000000001', '2025-01-01', '2025-01-05', 10),
            row('00000000001', '2025-01-07', '2025-02-01', 20),
            row('00000000002', '2025-01-03', '2025-01-08', 0)]
    path = tmp_path / 'bills.csv'
    frame(rows).to_csv(path, index=False)
    cfg = Config(target_start='2025-01-01', target_end_exclusive='2025-01-10', ingestion_chunk_size=1)
    audited, ledger = read_bills(path, cfg)
    assert ledger['internal_target_gap_customers'] == 1
    classes = coverage_classes(audited, date_ordinal(cfg.target_start), date_ordinal(cfg.target_end_exclusive))
    assert classes['00000000001'] == ('none', 0)
    assert classes['00000000002'] == ('partial', 6)


def test_internal_gap_exports_nulls_with_explicit_reason(tmp_path):
    from isd.pipeline import canonical, export_outputs
    rows = [row('00000000001', '2025-01-20', '2025-02-01', 10),
            row('00000000001', '2025-02-03', '2025-03-20', 20)]
    audited, _ = audit_normalized(normalize_frame(frame(rows)))
    audited = canonical(audited)
    origin = date_ordinal('2025-01-20')
    classes = coverage_classes(audited, origin, origin + 60)
    daily = pd.DataFrame({'temperature_mean_F': [40.] * 60,
                          'wind_mean_mph': [1.] * 60,
                          'weather_status': ['complete'] * 60})
    export_outputs(audited, classes, daily, origin, Config(), tmp_path, 'gap-test',
                   audited.iloc[:0], None, {}, {'fallback_reason': 'fit_unavailable', 'fit_dates': []})
    target = pd.read_parquet(tmp_path / 'target_customer_daily.parquet')
    assert len(target) == 60
    assert target.estimated_consumption.isna().all()
    assert (target.reason == 'internal_target_gap').all()


def test_daily_integral_plotting_preserves_values_and_target(tmp_path):
    import xml.etree.ElementTree as ET
    seconds, values = hourly_linear()
    days = [date_ordinal('2025-01-20'), date_ordinal('2025-01-21')]
    plain = daily_integral(seconds, values, days)
    plotted = daily_integral(seconds, values, days, plot_directory=tmp_path,
                             target_start='2025-01-20', target_end_exclusive='2025-01-21')
    pd.testing.assert_frame_equal(plain, plotted, check_exact=True)
    paths = list(tmp_path.glob('*.svg'))
    assert len(paths) == 3
    for path in paths:
        root = ET.parse(path).getroot()
        points = root.findall('.//{http://www.w3.org/2000/svg}circle')
        assert len(points) == 1
        assert points[0][0].text.startswith('2025-01-20:')


def test_weather_plots_do_not_bridge_missing_days(tmp_path):
    import xml.etree.ElementTree as ET
    from isd.weather import save_daily_weather_plots
    daily = pd.DataFrame({'date_gregorian': ['2025-01-19', '2025-01-20', '2025-01-22', '2025-01-23'],
                          'temperature_mean_C': [999, 1, 3, 999],
                          'apparent_temperature_mean_C': [999, 1, 3, 999],
                          'wind_mean_kmh': [999, 1, 3, 999]})
    paths = save_daily_weather_plots(daily, tmp_path, '2025-01-20', '2025-01-23')
    for path in paths:
        root = ET.parse(path).getroot()
        curve = root.find('.//{http://www.w3.org/2000/svg}path').attrib['d']
        assert curve.count('M') == 2 and 'L' not in curve
        assert len(root.findall('.//{http://www.w3.org/2000/svg}circle')) == 2
        assert '1 unavailable day(s)' in path.read_text(encoding='utf-8')
