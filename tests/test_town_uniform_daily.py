import csv
from decimal import Decimal

from scripts.town_uniform_daily import export_uniform


def test_all_bills_inclusive_overlap_gap_and_conservation(tmp_path):
    source = tmp_path / 'bills.csv'
    source.write_text('SubscriptionNumber,FromDate,ToDate,Consumption\n'
                      'A,1/1/2024,1/2/2024,10\n'
                      'A,2024-01-02,2024-01-02,3\n'
                      'B,1/2/2024,1/3/2024,4\n'
                      'B,1/5/2024,1/5/2024,0\n')
    output = tmp_path / 'daily.csv'
    assert export_uniform(source, output) == (4, 5)
    with output.open() as stream:
        rows = list(csv.DictReader(stream))
    assert [int(r['number_of_bills']) for r in rows] == [1, 3, 1, 0, 1]
    assert [int(r['number_of_customers']) for r in rows] == [1, 2, 1, 0, 1]
    assert [Decimal(r['uniform_consumption']) for r in rows] == [5, 10, 2, 0, 0]
    assert sum(Decimal(r['uniform_consumption']) for r in rows) == 17
