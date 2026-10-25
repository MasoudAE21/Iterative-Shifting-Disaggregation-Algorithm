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
