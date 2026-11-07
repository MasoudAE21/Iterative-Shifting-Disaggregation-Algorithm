"""Fit an annual station-consumption curve for retrospective disaggregation."""
import numpy as np
import pandas as pd
from .data import sha256


def fourier_basis(dates, period, harmonics):
    days = (pd.DatetimeIndex(pd.to_datetime(dates)) - pd.Timestamp('2000-01-01')).days.to_numpy()
    phase = 2 * np.pi * days / period
    return np.column_stack([np.ones(len(days))] + [f(k * phase) for k in range(1, harmonics + 1) for f in (np.sin, np.cos)])


def fit_tbs_fourier(path, dates, cfg):
    cfg.validate()
    station = pd.read_csv(path).dropna(how='all')
    source_dates = pd.to_datetime(station.date_gregorian, errors='raise').dt.normalize()
    if source_dates.isna().any() or source_dates.duplicated().any():
        raise ValueError('TBS dates must be present and unique')
    values = pd.to_numeric(station.consumption_m3, errors='raise').to_numpy(dtype=float)
    if np.isinf(values).any() or (values < 0).any():
        raise ValueError('TBS consumption must be finite and nonnegative or missing')
    mask = (source_dates >= pd.Timestamp(cfg.target_start)) & (source_dates < pd.Timestamp(cfg.target_end_exclusive)) & np.isfinite(values)
    basis = fourier_basis(source_dates[mask], cfg.tbs_fourier_period_days, cfg.tbs_fourier_harmonics)
    if len(basis) < basis.shape[1]:
        raise ValueError('Insufficient TBS observations for Fourier fit')
    coefficients, _, rank, _ = np.linalg.lstsq(basis, values[mask], rcond=None)
    if rank != basis.shape[1]:
        raise ValueError('Rank-deficient TBS Fourier fit')
    predicted = fourier_basis(dates, cfg.tbs_fourier_period_days, cfg.tbs_fourier_harmonics) @ coefficients
    return predicted, dict(source_sha256=sha256(path), period_days=cfg.tbs_fourier_period_days,
        harmonics=cfg.tbs_fourier_harmonics, coefficients=coefficients.tolist(),
        origin='2000-01-01', observations=int(mask.sum()),
        fit_start=str(source_dates[mask].min().date()), fit_end=str(source_dates[mask].max().date()),
        rmse=float(np.sqrt(np.mean((basis @ coefficients - values[mask]) ** 2))),
        evaluation='TBS is a model input; same-period comparison is in-sample',
        extrapolation='Periodic curve; no clipping')

