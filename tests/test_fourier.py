import numpy as np
import pandas as pd
import pytest
from dataclasses import replace
from run_pipeline import CONFIG
from isd.fourier import fourier_basis, fit_tbs_fourier


def test_recovers_curve_with_missing_observation(tmp_path):
    dates = pd.date_range('2024-01-01', periods=366)
    expected = fourier_basis(dates, 365.2425, 3) @ np.array([100, 10, 20, 3, 4, 1, 2])
    observed = expected.copy()
    observed[10] = np.nan
    path = tmp_path / 'tbs.csv'
    pd.DataFrame({'date_gregorian': dates, 'consumption_m3': observed}).to_csv(path, index=False)
    cfg = replace(CONFIG, feature_preset='tbs_fourier_v1')
    result, info = fit_tbs_fourier(path, dates, cfg)
    np.testing.assert_allclose(result, expected, atol=1e-10)
    assert info['observations'] == 365
    pd.DataFrame({'date_gregorian': dates[:3], 'consumption_m3': observed[:3]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match='Insufficient'):
        fit_tbs_fourier(path, dates, cfg)


def test_combined_fourier_and_town_features():
    from isd.weather import model_weather_features, build_design
    daily = pd.DataFrame({
        'apparent_temperature_mean_C': [1., 3., 7., 2.],
        'wind_max_kmh': [2., 9., 5., 12.],
        'TBS_fourier': [100., 120., 90., 110.],
    })
    baseline = model_weather_features(daily, 'town_custom_v1')
    combined = model_weather_features(daily, 'town_tbs_fourier_v1')
    pd.testing.assert_frame_equal(combined.drop(columns='TBS_fourier'), baseline)
    np.testing.assert_array_equal(combined.TBS_fourier, daily.TBS_fourier)
    design, metadata = build_design(daily, 'town_tbs_fourier_v1', np.ones(4, bool),
                                    'provisional_cohort_isd', np.ones(4))
    assert np.isfinite(design).all()
    assert metadata['features'][1] == 'TBS_fourier'
    np.testing.assert_allclose(design[:, 1].mean(), 0, atol=1e-12)
    with pytest.raises(ValueError, match='tbs_path'):
        replace(CONFIG, feature_preset='town_tbs_fourier_v1', tbs_path=None).validate()
