"""Point-value adapter; transform weather only AFTER local daily integration."""
from .errors import AvailabilityError
import csv, io
from datetime import datetime,timedelta,timezone,date
from zoneinfo import ZoneInfo
from pathlib import Path
import numpy as np
import pandas as pd
from .data import EPOCH
HEADERS=['time','temperature_2m (Ã‚Â°C)','apparent_temperature (Ã‚Â°C)','wind_speed_10m (km/h)']

def read_weather(path):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    if len(lines) < 5 or lines[2] != '':
        raise ValueError('Weather metadata shape')
    metadata = dict(zip(
        next(csv.reader([lines[0]])),
        next(csv.reader([lines[1]])),
    ))
    if metadata.get('timezone') != 'GMT' or metadata.get('utc_offset_seconds') != '0':
        raise ValueError('UTC adapter requires GMT metadata')

    observations = pd.read_csv(
        io.StringIO('\n'.join(lines[3:])),
        dtype={'time': 'string'},
        keep_default_na=False,
    )
    if list(observations.columns) != HEADERS:
        raise ValueError('Weather headers/units changed')
    if not observations.time.str.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}').all():
        raise ValueError('Weather datetime format')
    utc_instants = pd.to_datetime(
        observations.time, format='%Y-%m-%dT%H:%M', utc=True, errors='raise'
    )
    # Convert pandas' microsecond/nanosecond representation to Unix seconds.
    seconds = utc_instants.astype('int64').to_numpy() / (
        1e6 if utc_instants.dtype.unit == 'us' else 1e9
    )
    if np.any(np.diff(seconds) <= 0):
        raise ValueError('Duplicate or unordered weather timestamps')

    # Columns remain temperature (C), apparent temperature (C), wind (km/h).
    values = observations[HEADERS[1:]].astype(float).to_numpy()
    if not np.isfinite(values).all() or np.any(values[:, 2] < 0):
        raise ValueError('Invalid weather values')
    metadata.update({
        'provider_model': None,
        'retrieved_at': None,
        'provider_variable_definition': 'instant',
        'wind_formula_unit': 'mph',
        'wind_unit_provenance': 'NMGC Revised 2024 IRP, Appendix C-5, PDF page 69; formula matches paper Eq.16',
    })
    return seconds, values, metadata

def daily_integral(seconds, values, days, tz_name='Asia/Tehran', *, plot_directory=None, target_start=None, target_end_exclusive=None):
    seconds = np.asarray(seconds, float)
    values = np.asarray(values, float)
    local_timezone = ZoneInfo(tz_name)
    if len(seconds) < 2 or np.any(np.diff(seconds) <= 0):
        raise ValueError('Weather timestamp ordering')
    records = []
    for ordinal in days:
        local_date = EPOCH.date() + timedelta(days=int(ordinal))
        day_start_utc = datetime.combine(local_date, datetime.min.time(), local_timezone).astimezone(timezone.utc).timestamp()
        day_end_utc = datetime.combine(local_date + timedelta(days=1), datetime.min.time(), local_timezone).astimezone(timezone.utc).timestamp()
        # Include observations bracketing both local midnights for interpolation.
        start_bracket_index = np.searchsorted(seconds, day_start_utc, side='right') - 1
        end_bracket_index = np.searchsorted(seconds, day_end_utc, side='left')
        complete = start_bracket_index >= 0 and end_bracket_index < len(seconds)
        if complete:
            complete = bool(
                np.all(np.diff(seconds[start_bracket_index:end_bracket_index + 1]) <= 3600)
                and np.isfinite(values[start_bracket_index:end_bracket_index + 1]).all()
            )
        row = {
            'date_gregorian': local_date,
            'weather_location_id': 'open_meteo_34.411247_50.490566_1435',
            'coverage_seconds': day_end_utc - day_start_utc if complete else 0.0,
            'weather_status': 'complete' if complete else 'unavailable',
            'adapter_version': 'point_linear_integral_v1',
            'utc_day_start': datetime.fromtimestamp(day_start_utc, timezone.utc).isoformat(),
            'utc_day_end': datetime.fromtimestamp(day_end_utc, timezone.utc).isoformat(),
        }
        means = []
        for column_index, column_name in enumerate(['temperature_mean_C', 'apparent_temperature_mean_C', 'wind_mean_kmh']):
            if complete:
                interior_times = seconds[(seconds > day_start_utc) & (seconds < day_end_utc)]
                integration_times = np.concatenate(([day_start_utc], interior_times, [day_end_utc]))
                interpolated_values = np.interp(integration_times, seconds, values[:, column_index])
                # Divide the integrated area by duration to obtain a time-weighted mean.
                mean = float(np.trapezoid(interpolated_values, integration_times) / (day_end_utc - day_start_utc))
            else:
                mean = float('nan')
            row[column_name] = mean
            means.append(mean)
        row['temperature_mean_F'] = means[0] * 1.8 + 32
        row['wind_mean_mph'] = means[2] / 1.609344
        records.append(row)
    daily = pd.DataFrame(records)
    if plot_directory is not None:
        if target_start is None or target_end_exclusive is None:
            raise ValueError('Plotting requires explicit target_start and target_end_exclusive')
        save_daily_weather_plots(daily, plot_directory, target_start, target_end_exclusive)
    return daily


def save_daily_weather_plots(daily, directory, target_start, target_end_exclusive):
    """Save dependency-free SVG plots; missing target days break the lines."""
    from html import escape

    start = pd.Timestamp(target_start)
    end = pd.Timestamp(target_end_exclusive)
    if start >= end:
        raise ValueError('Plot target must be nonempty')
    dates = pd.date_range(start, end, freq='D', inclusive='left')
    target = daily.copy()
    target['date_gregorian'] = pd.to_datetime(target['date_gregorian'])
    target = target.set_index('date_gregorian').reindex(dates)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    plots = [
        ('temperature_mean_C', 'Daily mean temperature', 'Temperature (°C)', '#2563eb'),
        ('apparent_temperature_mean_C', 'Daily mean apparent temperature', 'Apparent temperature (°C)', '#c2410c'),
        ('wind_mean_kmh', 'Daily mean wind speed', 'Wind speed (km/h)', '#087f5b'),
    ]
    paths = []
    left, top, width, height = 100, 110, 930, 300
    for column, title, units, color in plots:
        values = target[column].to_numpy(dtype=float)
        finite = np.isfinite(values)
        low, high = (float(values[finite].min()), float(values[finite].max())) if finite.any() else (0., 1.)
        padding = max((high - low) * .1, .5)
        low -= padding
        high += padding
        def x_position(index):
            return left + width * index / (len(dates) - 1) if len(dates) > 1 else left + width / 2
        def y_position(value):
            return top + height * (high - value) / (high - low)
        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="510" viewBox="0 0 1100 510" role="img">',
            f'<title>{escape(title)}</title>',
            '<rect width="1100" height="510" fill="white"/>',
            '<g font-family="Arial, sans-serif" fill="#1f2937">',
            f'<text x="100" y="35" font-size="23" font-weight="bold">{escape(title)}</text>',
            f'<text x="100" y="62" font-size="15">{start:%Y-%m-%d} through {dates[-1]:%Y-%m-%d} (local calendar dates)</text>',
            f'<text x="100" y="91" font-size="14">{escape(units)}</text>',
        ]
        for tick in np.linspace(low, high, 6):
            y = y_position(tick)
            svg.append(f'<line x1="{left}" y1="{y}" x2="{left + width}" y2="{y}" stroke="#e5e7eb"/>')
            svg.append(f'<text x="88" y="{y + 5}" text-anchor="end" font-size="13">{tick:.2f}</text>')
        tick_indices = np.unique(np.linspace(0, len(dates) - 1, min(7, len(dates))).astype(int))
        for index in tick_indices:
            x = x_position(index)
            svg.append(f'<text x="{x}" y="439" text-anchor="middle" font-size="13">{dates[index]:%Y-%m-%d}</text>')
        # Start a new path segment after every unavailable day; never bridge gaps.
        commands = []
        previous_available = False
        for index, value in enumerate(values):
            if not np.isfinite(value):
                previous_available = False
                continue
            x, y = x_position(index), y_position(value)
            commands.append(f'{"L" if previous_available else "M"} {x:.3f} {y:.3f}')
            svg.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="3" fill="{color}"><title>{dates[index]:%Y-%m-%d}: {value!r}</title></circle>')
            previous_available = True
        svg.append(f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" stroke-width="2"/>')
        missing = int((~finite).sum())
        svg.append(f'<text x="100" y="480" font-size="13">{missing} unavailable day(s); missing values are not filled.</text>')
        svg.append('</g></svg>')
        path = directory / f'{column}.svg'
        path.write_text('\n'.join(svg) + '\n', encoding='utf-8')
        paths.append(path)
    return paths


def weather_features(daily):
    """Build weather features from daily mean temperature (°F) and wind (mph)."""
    temperature_f = daily.temperature_mean_F.to_numpy()
    wind_mph = daily.wind_mean_mph.to_numpy()
    hdd65 = np.maximum(65 - temperature_f, 0)
    hdd55 = np.maximum(55 - temperature_f, 0)
    cdd65 = np.maximum(temperature_f - 65, 0)
    wind_multiplier = np.where(
        wind_mph <= 8,
        (152 + wind_mph) / 160,
        (72 + wind_mph) / 80,
    )
    return {
        'intercept': np.ones(len(temperature_f)),
        'HDD65': hdd65,
        'HDD55': hdd55,
        'HDDW65': hdd65 * wind_multiplier,
        'CDD65': cdd65,
    }

def build_design(daily, preset, mask, mode, exposure, exposure_scaled=True, allow_zero_spread=False):
    presets = {
        'paper_section3_v1': ['intercept', 'HDD65', 'HDD55', 'HDDW65', 'CDD65'],
        'winter_hdd65_v1': ['intercept', 'HDD65'],
        'winter_hdd65_hddw65_v1': ['intercept', 'HDD65', 'HDDW65'],
        'intercept_only_v1': ['intercept'],
    }
    if preset not in presets:
        raise ValueError('Unregistered feature preset')
    columns = presets[preset]
    features = weather_features(daily)
    design = np.column_stack([features[c] for c in columns])
    metadata = {
        'features': columns,
        'means': [0.0] * len(columns),
        'population_std': [1.0] * len(columns),
        'exposure_scaled_design': mode != 'paper_reference' and exposure_scaled,
    }
    if not np.isfinite(design).all():
        raise AvailabilityError('weather_unavailable: whole interval requires weather')
    if mode != 'paper_reference':
        if np.sum(mask) == 0:
            raise AvailabilityError('fit_unavailable: empty fit mask')
        # Leave the intercept unchanged; derive scaling statistics from fit dates only.
        for column_index in range(1, len(columns)):
            mean = float(np.mean(design[mask, column_index]))
            std = float(np.std(design[mask, column_index], ddof=0))
            metadata['means'][column_index] = mean
            metadata['population_std'][column_index] = std
            if std <= 64 * np.finfo(float).eps * max(1, abs(mean)):
                if allow_zero_spread:
                    design[:, column_index] = 0
                    continue
                raise AvailabilityError('fit_unavailable: zero-spread feature')
            # Apply the same fit-date transformation across the full modeled domain.
            design[:, column_index] = (design[:, column_index] - mean) / std
        if exposure_scaled:
            # Exposure scales every column, including the intercept.
            design = exposure[:, None] * design
    return design, metadata
