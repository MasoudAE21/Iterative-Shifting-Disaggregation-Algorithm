"""Check the external weather header contract independently of reader constants."""
import pytest

from isd.weather import read_weather


@pytest.mark.parametrize('unit', ['\u00b0C', '\u00b0F'])
def test_weather_celsius_header_contract(tmp_path, unit):
    path = tmp_path / 'weather.csv'
    path.write_text(
        'latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n'
        '34.41,50.49,1435,0,GMT,GMT\n\n'
        f'time,temperature_2m ({unit}),apparent_temperature ({unit}),wind_speed_10m (km/h)\n'
        '2025-01-20T00:00,5,3,10\n'
        '2025-01-20T01:00,6,4,11\n',
        encoding='utf-8',
    )
    if unit == '\u00b0F':
        with pytest.raises(ValueError, match='Weather headers/units changed'):
            read_weather(path)
    else:
        seconds, values, metadata = read_weather(path)
        assert seconds[1] - seconds[0] == 3600
        assert values.tolist() == [[5., 3., 10.], [6., 4., 11.]]


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'cp1252'])
def test_daily_weather_export_encodings(tmp_path, encoding):
    path = tmp_path / 'daily.csv'
    path.write_text(
        'latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n'
        '34.41,50.49,1435,0,GMT,GMT\n\n'
        'time,apparent_temperature_mean (\u00b0C),wind_speed_10m_max (km/h)\n'
        '2025-01-20,3,10\n', encoding=encoding,
    )
    _, daily, metadata = read_weather(path)
    assert daily.apparent_temperature_mean_C.tolist() == [3.]
    assert metadata['latitude'] == '34.41'
    assert metadata['source_encoding'] == ('cp1252' if encoding == 'cp1252' else 'utf-8-sig')


def test_spreadsheet_weather_export(tmp_path):
    path = tmp_path / 'weather.csv'
    path.write_text(
        'latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n'
        '34.41,50.49,1333,0,GMT,GMT\n,,,,,\n'
        'time,apparent_temperature_mean (\u00b0C),wind_speed_10m_max (km/h),,,\n'
        '11/1/2024,11.3,14.6,,,\n11/2/2024,12.8,21.5,,,\n', encoding='cp1252')
    _, daily, metadata = read_weather(path)
    assert str(daily.date_gregorian.iloc[0]) == '2024-11-01'
    assert metadata['source_date_format'] == '%m/%d/%Y'
    assert daily.apparent_temperature_mean_C.tolist() == [11.3, 12.8]


@pytest.mark.parametrize('air', ['7.5', 'nan', 'inf'])
def test_three_variable_daily_weather(tmp_path, air):
    from isd.weather import daily_integral
    from isd.data import date_ordinal
    path = tmp_path / 'daily.csv'
    path.write_text(
        'latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n'
        '34.69,50.86,939,0,GMT,GMT\n,,,,,\n'
        'time,temperature_2m_mean (°C),apparent_temperature_mean (°C),wind_speed_10m_max (km/h),,\n'
        f'1/20/2025,{air},3,12,,\n', encoding='cp1252')
    if air != '7.5':
        with pytest.raises(ValueError, match='Invalid daily weather'):
            read_weather(path)
        return
    sec, values, _ = read_weather(path)
    daily = daily_integral(sec, values, [date_ordinal('2025-01-20')],
        plot_directory=tmp_path / 'plots', target_start='2025-01-20', target_end_exclusive='2025-01-21')
    assert daily.temperature_mean_C.tolist() == [7.5]
    assert daily.temperature_mean_F.tolist() == [45.5]
    assert daily.apparent_temperature_mean_C.tolist() == [3.0]
    assert daily.wind_max_kmh.tolist() == [12.0]
    assert len(list((tmp_path / 'plots').glob('*.svg'))) == 3
