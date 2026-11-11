from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from isd.config import Config
from isd.customer_floor import attach_customer_floors, normalize_consumption
from isd.data import COLUMNS, normalize_frame, prepare_state, date_ordinal
from isd.solver import solve


def bills():
    return normalize_frame(pd.DataFrame([
        ['00000000001', '2024-05-22', '2024-06-10', 40, 40, 2, 6],
        ['00000000001', '2024-06-11', '2024-06-30', 80, 40, 2, 6],
        ['00000000001', '2024-10-01', '2024-10-10', 10, 40, 2, 6],
        ['00000000001', '2024-10-11', '2024-10-20', 0, 40, 2, 6],
        ['00000000002', '2024-09-02', '2024-09-30', 58, 40, 1, 6],
    ], columns=COLUMNS))


def test_weighted_baseline_threshold_and_feasibility():
    cfg = Config(customer_summer_floor=True)
    result = attach_customer_floors(bills(), cfg)
    assert result.summer_covered_days.tolist() == [30, 30, 30, 30, 29]
    np.testing.assert_allclose(result.summer_daily_baseline, [10/3]*4 + [2])
    np.testing.assert_allclose(result.daily_floor, [2, .95*10/3, 1, 0, .2])
    assert result.floor_feasibility_adjusted.tolist() == [True, False, True, True, False]
    assert result.floor_source.iloc[-1] == 'insufficient_summer_fallback'
    lower = attach_customer_floors(bills(), replace(cfg, summer_min_covered_days=29, summer_floor_fraction=.5))
    assert lower.daily_floor.iloc[-1] == 1
    higher = attach_customer_floors(bills(), replace(cfg, summer_min_covered_days=31))
    np.testing.assert_allclose(higher.daily_floor, [.2, .4, .1, 0, .2])


def test_unit_normalization_and_provenance():
    source = bills()
    cfg = Config(customer_summer_floor=True, divide_consumption_by_unit_count=True)
    normalized = normalize_consumption(source, cfg)
    np.testing.assert_allclose(normalized.Consumption, [20, 40, 5, 0, 58])
    pd.testing.assert_series_equal(source.raw_Consumption, normalized.raw_Consumption)
    np.testing.assert_allclose(normalized.consumption_before_unit_normalization, source.Consumption)
    floor = attach_customer_floors(normalized, cfg)
    assert floor.summer_daily_baseline.iloc[0] == pytest.approx(5/3)
    np.testing.assert_array_equal(normalize_consumption(source, Config()).Consumption, source.Consumption)
    for invalid in (0, -1, 1.5, np.nan):
        bad = source.copy()
        bad.loc[0, 'UnitCount'] = invalid
        with pytest.raises(ValueError, match='UnitCount'):
            normalize_consumption(bad, cfg)


@pytest.mark.parametrize('initialization', ['uniform', 'seasonal_reference'])
def test_solver_floor_conservation_engines_and_checkpoint(tmp_path, initialization):
    cfg = Config(customer_summer_floor=True, initialization=initialization,
                 individual_reference_strength=.03, n_lr_models=2, n_disagg_cycles=2)
    source = attach_customer_floors(bills(), cfg)
    origin = int(source.start_ordinal.min())
    n = int(source.end_ordinal.max()) - origin
    state = prepare_state(source, origin, n)
    design = np.column_stack([np.ones(n), np.sin(np.arange(n)/13)])
    weights = 1 + np.arange(n) % 17
    ref = solve(state, design, replace(cfg, engine='reference'), reference_weights=weights)
    fast = solve(state, design, cfg, reference_weights=weights)
    np.testing.assert_allclose(ref.allocations, fast.allocations, atol=1e-12)
    for k, total in enumerate(state.totals):
        a = fast.allocations[state.offsets[k]:state.offsets[k+1]]
        assert a.sum() == pytest.approx(total)
        assert a.min() >= state.daily_floors[k] - 1e-12
    checkpoint = tmp_path / 'checkpoint.npz'
    solve(state, design, cfg, checkpoint_path=checkpoint, stop_after_cycles=1, reference_weights=weights)
    resumed = solve(state, design, replace(cfg, resume=True), checkpoint_path=checkpoint, reference_weights=weights)
    np.testing.assert_array_equal(fast.allocations, resumed.allocations)
    state.daily_floors = state.daily_floors.copy()
    state.daily_floors[1] *= .9
    with pytest.raises(ValueError, match='mismatch'):
        solve(state, design, replace(cfg, resume=True), checkpoint_path=checkpoint, reference_weights=weights)


@pytest.mark.parametrize('kwargs', [dict(summer_floor_fraction=1.1), dict(summer_floor_fraction=float('nan')),
    dict(summer_min_covered_days=0), dict(summer_min_covered_days=True),
    dict(summer_min_covered_days=1.5), dict(divide_consumption_by_unit_count='No')])
def test_configuration_validation(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs).validate()


@pytest.mark.parametrize('normalize', [False, True])
def test_summer_pipeline_and_daily_floor_export(tmp_path, normalize):
    from datetime import datetime, timedelta
    from isd.pipeline import run
    data = tmp_path / 'data' / 'prepared'
    data.mkdir(parents=True)
    pd.DataFrame([
        ['00000000001', '2024-06-01', '2024-06-30', 60, 40, 2, 6],
        ['00000000001', '2024-07-01', '2024-07-31', 124, 40, 2, 6],
    ], columns=COLUMNS).to_csv(data / 'bill_Customers_Town_Q.csv', index=False)
    with (data / 'open-meteo-fixture.csv').open('w', encoding='utf-8') as f:
        f.write('latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n34,50,1435,0,GMT,GMT\n\ntime,temperature_2m (°C),apparent_temperature (°C),wind_speed_10m (km/h)\n')
        for i in range(65*24):
            dt = datetime(2024, 5, 31) + timedelta(hours=i)
            f.write(f'{dt:%Y-%m-%dT%H:%M},20,20,10\n')
    pd.DataFrame({'date_gregorian': pd.date_range('2024-06-01', '2024-07-31'),
                  'consumption_m3': 3}).to_csv(data / 'station.csv', index=False)
    cfg = Config(customer_summer_floor=True, divide_consumption_by_unit_count=normalize,
                 target_start='2024-06-01', target_end_exclusive='2024-08-01',
                 target_year_confirmed=True, bill_window='target', feature_preset='intercept_only_v1',
                 tbs_path='data/prepared/station.csv', checkpoint=False, max_customers=None,
                 n_lr_models=1, n_disagg_cycles=2)
    out = tmp_path / 'out'
    run(tmp_path, cfg, out)
    scale = 2 if normalize else 1
    ledger = pd.read_parquet(out / 'normalized_bills.parquet')
    np.testing.assert_allclose(ledger.summer_daily_baseline, 184/61/scale)
    comparison = pd.read_csv(out / 'simulation_daily_comparison.csv')
    np.testing.assert_allclose(comparison.total_floor_consumption_m3,
                               [2/scale]*30 + [.95*184/61/scale]*31)
    full = pd.read_parquet(out / 'full_bill_daily.parquet')
    assert full.estimated_consumption.sum() == pytest.approx(184/scale)
    assert (comparison.final_algorithm_consumption_m3 >= comparison.total_floor_consumption_m3 - 1e-10).all()
