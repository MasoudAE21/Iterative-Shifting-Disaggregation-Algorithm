"""Edit this function to experiment with Town weather features."""
import numpy as np
from numbers import Integral


def moving_average(values, n):
    """Trailing n-day mean, including today; return a float NumPy array.

    Input must be a one-dimensional series in consecutive daily order.
    The first n-1 days retain their own value until a full window exists.
    If n exceeds the series length, every day retains its own value.
    Missing values within a full window propagate; they are not filled.
    """
    if isinstance(n, (bool, np.bool_)) or not isinstance(n, Integral) or n < 1:
        raise ValueError('Moving-average window n must be a positive integer')
    values = np.asarray(values, dtype=float)
    if values.ndim != 1:
        raise ValueError('Moving-average input must be one-dimensional')
    result = values.copy()
    if n <= len(values):
        result[n-1:] = np.convolve(values, np.ones(n) / n, mode='valid')
    return result

def hdd(temperature_c, base_c):
    """Heating degree feature using an explicit Celsius base (e.g. 5)."""
    return np.maximum(base_c - np.asarray(temperature_c, dtype=float), 0)


def town_features(daily, include_fourier=False):
    """Return any named daily features, with the intercept first.

    Use town_tbs_fourier_v1 to include the fitted TBS curve below.
    Edit the returned dictionary to combine it with weather features.
    Scaling is automatic. Replace HDD65 with HDD5 to test a 5 C threshold.
    Combine independent features (e.g. HDD5 + wind, HDD0, or HDD5 * wind).
    HDD5 + HDD10 are redundant if all fitting temperatures are below 5 C.
    """
    temperature = daily.apparent_temperature_mean_C.to_numpy(dtype=float)
    wind = daily.wind_max_kmh.to_numpy(dtype=float) / 1.609
    wind_multiplier = np.where(
        wind <= 8,
        (152 + wind) / 160,
        (72 + wind) / 80,
    )
    # hdd45 = np.maximum(45 - (temperature * 1.8 + 32), 0)
    hdd65 = np.maximum(65 - (temperature * 1.8 + 32), 0)
    fourier = daily["TBS_fourier"].to_numpy(dtype=float) if include_fourier else None
    return {
        "intercept": np.ones(len(daily)),
        **({"TBS_fourier": fourier} if include_fourier else {}),
        # "temp": temperature,
        # "temp_ma7": moving_average(temperature, 7),
        "HDD65_ma3": moving_average(hdd65, 3),
        # "HDD65_ma14": moving_average(hdd65, 14),
        # "HDD10": hdd(temperature, 10),
        # "HDD5": hdd(temperature, 5),
        # "HDD0": hdd(temperature, 0),
        "HDD65": hdd65,
        # "HDD45": hdd45,
        # "HDD35": np.maximum(35 - (temperature * 1.8 + 32), 0),
        "CDD65": np.maximum((temperature * 1.8 + 32) - 65, 0),
        'HDDpW65': hdd65 * wind_multiplier,
        # 'HDDsW65': hdd65 + wind_multiplier,
        # 'HDDpW45': hdd45 * wind_multiplier,
        # 'HDDsW45': hdd45 + wind_multiplier,
        # "wind_max": wind,
        
    }
