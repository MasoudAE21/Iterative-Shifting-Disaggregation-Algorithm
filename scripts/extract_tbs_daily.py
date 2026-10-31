"""Extract midnight TBS readings into daily consumption (Gregorian and Shamsi).

Run: python scripts/extract_tbs_daily.py [input.tab] [-o output.csv]
Requires jdatetime. One streaming pass, O(n) time and O(1) working memory.
Consumption belongs to today: Vb(tomorrow midnight) - Vb(today midnight).
Missing next-day readings (including the final day) produce an empty cell.
Negative differences are preserved, since they may indicate a meter reset.
"""

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
import tempfile

import jdatetime


ROOT = Path(__file__).resolve().parents[1]


def extract_daily(source, destination):
    """Write a UTF-8 CSV atomically; reject invalid or unordered midnight data."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Input and output paths must differ')
    counts = dict(midnight_readings=0, removed_non_midnight=0,
                  calculated_days=0, missing_next_day=0, negative_days=0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with source.open(encoding='utf-8-sig', newline='') as incoming, \
                tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                            dir=destination.parent, delete=False) as outgoing:
            temporary = Path(outgoing.name)
            reader = csv.reader(incoming, delimiter='\t')
            headers = next(reader, [])
            if any(headers.count(name) != 1 for name in ('Time', 'Vb [m3]')):
                raise ValueError('Input must contain unique Time and Vb [m3] columns')
            time_index, volume_index = headers.index('Time'), headers.index('Vb [m3]')
            writer = csv.writer(outgoing)
            writer.writerow(['date_gregorian', 'date_shamsi', 'consumption_m3'])

            def emit(day, consumption):
                writer.writerow([day.isoformat(),
                                 jdatetime.date.fromgregorian(date=day).isoformat(),
                                 '' if consumption is None else format(consumption, 'f')])
                if consumption is None:
                    counts['missing_next_day'] += 1
                else:
                    counts['calculated_days'] += 1
                    counts['negative_days'] += consumption < 0

            previous = None
            for line, row in enumerate(reader, 2):
                if not row:
                    continue
                try:
                    timestamp = datetime.strptime(row[time_index].strip(), '%Y-%m-%d,%H:%M:%S')
                    if timestamp.hour or timestamp.minute or timestamp.second:
                        counts['removed_non_midnight'] += 1
                        continue
                    volume = Decimal(row[volume_index].strip())
                    if not volume.is_finite():
                        raise ValueError('Vb must be finite')
                except (ValueError, InvalidOperation, IndexError) as error:
                    raise ValueError(f'Invalid reading at line {line}: {error}') from error
                day = timestamp.date()
                if previous is not None:
                    prior_day, prior_volume = previous
                    interval = (day - prior_day).days
                    if interval <= 0:
                        raise ValueError(f'Midnight dates must increase strictly (line {line})')
                    consumption = None
                    if interval == 1:
                        # Enough precision to subtract the full supplied decimal values.
                        with localcontext() as context:
                            context.prec = max(volume.adjusted(), prior_volume.adjusted()) - min(
                                volume.as_tuple().exponent, prior_volume.as_tuple().exponent) + 2
                            consumption = volume - prior_volume
                    emit(prior_day, consumption)
                previous = day, volume
                counts['midnight_readings'] += 1
            if previous is None:
                raise ValueError('No midnight readings found')
            emit(previous[0], None)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path,
                        default=ROOT / 'data/raw/TBS_Town_Q_daily_raw.tab')
    parser.add_argument('-o', '--output', type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / 'data/prepared/TBS_Town_Q_daily_consumption.csv'
    counts = extract_daily(args.input, output)
    print(f'Created {output.resolve()}')
    print(', '.join(f'{key}={value}' for key, value in counts.items()))


if __name__ == '__main__':
    main()
