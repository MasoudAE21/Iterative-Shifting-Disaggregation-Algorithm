import numpy as np
import pandas as pd
import pytest

from isd.weather import model_weather_features, build_design

PRESET = 'paper_section3_daily_air_maxwind_v1'


def test_paper_daily_air_features_and_wind_conversion():
    daily = pd.DataFrame({
        'temperature_mean_C': [(45-32)/1.8, (55-32)/1.8, (75-32)/1.8, (45-32)/1.8],
        'apparent_temperature_mean_C': [-30., -30., -30., -30.],
        'wind_max_kmh': np.array([0., 8., 16., 16.]) * 1.609344,
    })
    features = model_weather_features(daily, PRESET)
    assert list(features) == ['intercept', 'HDD65', 'HDD55', 'HDDW65', 'CDD65']
    np.testing.assert_allclose(features.to_numpy(), [
        [1, 20, 10, 19, 0], [1, 10, 0, 10, 0], [1, 0, 0, 0, 10], [1, 20, 10, 22, 0],
    ], atol=1e-12)
    _, metadata = build_design(daily, PRESET, np.ones(4, bool),
                               'provisional_cohort_isd', np.ones(4))
    assert metadata['temperature_basis'] == 'daily_mean_air'
    assert metadata['wind_statistic'] == 'maximum'
    assert metadata['wind_formula_unit'] == 'mph'


def test_paper_daily_features_require_air_temperature():
    with pytest.raises(ValueError, match='mean air temperature'):
        model_weather_features(pd.DataFrame({'wind_max_kmh': [8.]}), PRESET)
