"""Independent raw-bill inspection: no workflow filtering or customer quarantine.

Every CSV row counts as a bill, including overlapping/duplicate rows, long bills,
zero bills, and signed consumption. Both endpoints are inclusive. Invalid dates
or nonfinite/non-numeric totals fail explicitly rather than silently losing rows.
"""
import argparse
import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_bill_date(value):
    """Accept canonical ISO or the explicit US-style date format in Town exports."""
    if '/' in value:
        return datetime.strptime(value, '%m/%d/%Y').date()
    return date.fromisoformat(value)


def export_uniform(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Input and output paths must differ')
    events = defaultdict(lambda: [0, Decimal(0)])
    customer_intervals = defaultdict(list)
    bills = 0
    with localcontext() as context:
        context.prec = 40
        with source.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            if not {'SubscriptionNumber', 'FromDate', 'ToDate', 'Consumption'} <= set(reader.fieldnames or []):
                raise ValueError('Required columns: SubscriptionNumber, FromDate, ToDate, Consumption')
            for row_number, row in enumerate(reader, 2):
                try:
                    start = parse_bill_date(row['FromDate'])
                    end = parse_bill_date(row['ToDate'])
                    total = Decimal(row['Consumption'])
                    if end < start or not total.is_finite():
                        raise ValueError('Reversed dates or nonfinite consumption')
                    stop = end + timedelta(days=1)
                    if not row['SubscriptionNumber'].strip():
                        raise ValueError('Missing customer identifier')
                except (ValueError, TypeError, InvalidOperation, OverflowError) as error:
                    raise ValueError(f'Invalid bill at CSV record {row_number}: {error}') from error
                daily = total / Decimal((stop - start).days)
                events[start][0] += 1
                events[start][1] += daily
                events[stop][0] -= 1
                events[stop][1] -= daily
                customer_intervals[row['SubscriptionNumber']].append((start, stop))
                bills += 1
        if not bills:
            raise ValueError('No bills in input')
        customer_events = defaultdict(int)
        for intervals in customer_intervals.values():
            merged = []
            for start, stop in sorted(intervals):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
                else:
                    merged.append((start, stop))
            for start, stop in merged:
                customer_events[start] += 1
                customer_events[stop] -= 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        first, stop = min(events), max(events)
        with destination.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['date', 'number_of_bills', 'number_of_customers', 'uniform_consumption'])
            day, count, consumption = first, 0, Decimal(0)
            customers = 0
            while day < stop:
                delta_count, delta_total = events.get(day, (0, Decimal(0)))
                count += delta_count
                consumption += delta_total
                customers += customer_events[day]
                if count == 0:
                    consumption = Decimal(0)
                writer.writerow([day.isoformat(), count, customers, str(consumption)])
                day += timedelta(days=1)
        return bills, (stop - first).days


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bills', type=Path, default=ROOT / 'data/prepared/bill_Customers_Town_Q_full_year.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/town_uniform/full_year_daily_uniform.csv')
    args = parser.parse_args()
    bills, days = export_uniform(args.bills, args.output)
    print(f'Wrote {days} days from all {bills} bills to {args.output}')


if __name__ == '__main__':
    main()
