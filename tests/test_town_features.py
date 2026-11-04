import numpy as np
import pandas as pd
import pytest
from isd.weather import build_design, export_weather_features
from isd.town_features import hdd, moving_average


def test_custom_names_and_combinations(monkeypatch):
    t = np.linspace(-10, 10, 58)
    wind = np.sin(np.arange(58)) + 2
    daily = pd.DataFrame({'apparent_temperature_mean_C': t, 'wind_max_kmh': wind})
    monkeypatch.setattr('isd.town_features.town_features', lambda daily: {
        'intercept': np.ones(58), 'HDD5': hdd(t, 5), 'wind': wind,
        'interaction': hdd(t, 5) * wind,
    })
    design, metadata = build_design(daily, 'town_custom_v1', np.ones(58, bool),
                                    'provisional_cohort_isd', np.ones(58))
    assert metadata['features'] == ['intercept', 'HDD5', 'wind', 'interaction']
    assert np.linalg.matrix_rank(design) == 4
    assert hdd(np.array([0, 5, 10]), 5).tolist() == [5, 0, 0]


def test_feature_csv_matches_unscaled_model_inputs(tmp_path, monkeypatch):
    daily = pd.DataFrame({'date_gregorian': pd.date_range('2025-01-01', periods=3),
                          'temperature_mean_C': [1, 2, 3],
                          'apparent_temperature_mean_C': [-2, 0, 4], 'wind_max_kmh': [10, 20, 30]})
    monkeypatch.setattr('isd.town_features.town_features', lambda d: {
        'intercept': np.ones(len(d)), 'custom_heating': hdd(d.apparent_temperature_mean_C, 5),
    })
    path = tmp_path / 'weather_features.csv'
    export_weather_features(daily, 'town_custom_v1', path)
    exported = pd.read_csv(path)
    assert exported.custom_heating.tolist() == [7, 5, 1]
    assert exported.temperature_mean_C.tolist() == [1, 2, 3]
    design, info = build_design(daily, 'town_custom_v1', np.ones(3, bool),
                                'provisional_cohort_isd', np.ones(3))
    assert np.allclose(design[:, 1], (exported.custom_heating-info['means'][1])/info['population_std'][1])
    assert exported.intercept.eq(1).all()


def test_moving_average_trailing_window_and_startup():
    source = np.array([1., 3., 8., 12., 21.])
    result = moving_average(source, 3)
    assert np.allclose(result, [1, 3, 4, 23/3, 41/3])
    assert source.tolist() == [1, 3, 8, 12, 21]
    changed_future = source.copy()
    changed_future[-1] = 999
    assert np.allclose(moving_average(changed_future, 3)[:-1], result[:-1])
    assert np.array_equal(moving_average(source, 1), source)
    assert np.array_equal(moving_average(source, 10), source)
    assert moving_average([], 3).size == 0
    assert np.allclose(moving_average(pd.Series(source), np.int64(3)), result)


@pytest.mark.parametrize('n', [0, -1, 2.5, True, '3'])
def test_moving_average_rejects_invalid_window(n):
    with pytest.raises(ValueError, match='positive integer'):
        moving_average([1, 2, 3], n)


def test_moving_average_missing_values_do_not_poison_later_windows():
    result = moving_average([1, np.nan, 3, 5, 7], 2)
    assert np.allclose(result, [1, np.nan, np.nan, 4, 6], equal_nan=True)
    with pytest.raises(ValueError, match='one-dimensional'):
        moving_average([[1, 2]], 2)


def test_moving_average_feature_export_and_design(tmp_path, monkeypatch):
    daily = pd.DataFrame({'date_gregorian': pd.date_range('2025-01-01', periods=4),
                          'apparent_temperature_mean_C': [1, 3, 8, 12], 'wind_max_kmh': [10]*4})
    monkeypatch.setattr('isd.town_features.town_features', lambda d: {
        'intercept': np.ones(len(d)), 'temp_ma3': moving_average(d.apparent_temperature_mean_C, 3),
    })
    path = tmp_path / 'weather_features.csv'
    export_weather_features(daily, 'town_custom_v1', path)
    assert np.allclose(pd.read_csv(path).temp_ma3, [1, 3, 4, 23/3])
    design, info = build_design(daily, 'town_custom_v1', np.ones(4, bool),
                                'provisional_cohort_isd', np.ones(4))
    assert info['features'] == ['intercept', 'temp_ma3']
    assert np.isfinite(design).all()
