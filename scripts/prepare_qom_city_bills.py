"""Filter the full billing export by the supplied city subscription roster."""
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    roster = ROOT/'data/raw/qom_city_customers.csv'
    source = ROOT/'data/raw/new_bill_1403.csv'
    output = ROOT/'data/prepared/qom_city_bills_1403.csv'
    with roster.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['SubscriptionNumber']:
            raise ValueError('Roster must have only the SubscriptionNumber column')
        ids = [row['SubscriptionNumber'].strip().lstrip('\ufeff') for row in reader]
    if any(not re.fullmatch(r'\d{11}', ident) for ident in ids):
        raise ValueError('Roster contains blank or invalid subscription numbers')
    wanted = set(ids)
    matched, type40 = set(), set()
    counts = Counter()
    source_rows = normalized_bom_rows = 0
    temporary = output.with_suffix('.csv.tmp')
    with source.open(encoding='utf-8-sig', newline='') as inp, temporary.open('w', encoding='utf-8', newline='') as out:
        reader = csv.DictReader(inp)
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            source_rows += 1
            ident = row['SubscriptionNumber'].lstrip('\ufeff')
            if ident not in wanted:
                continue
            normalized_bom_rows += ident != row['SubscriptionNumber']
            row['SubscriptionNumber'] = ident
            writer.writerow(row)
            matched.add(ident)
            counts[row['ConsumptionType']] += 1
            if row['ConsumptionType'] == '40':
                type40.add(ident)
    if not matched:
        raise ValueError('No roster customers matched; configuration left unchanged')
    # Independently read the prepared output before making it the configured input.
    with temporary.open(encoding='utf-8', newline='') as stream:
        verified = Counter()
        for row in csv.DictReader(stream):
            assert row['SubscriptionNumber'] in wanted
            verified[row['ConsumptionType']] += 1
    assert verified == counts
    temporary.replace(output)
    for name, values in [('qom_city_customers_without_bills.csv', wanted-matched),
                         ('qom_city_customers_without_type40_bills.csv', wanted-type40)]:
        with (output.parent/name).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['SubscriptionNumber'])
            writer.writerows([ident] for ident in sorted(values))
    report = dict(source=str(source), source_sha256=digest(source), roster=str(roster),
                  roster_sha256=digest(roster), output=str(output), output_sha256=digest(output),
                  roster_rows=len(ids), roster_unique_customers=len(wanted),
                  duplicate_roster_rows=len(ids)-len(wanted), source_bills=source_rows,
                  output_bills=sum(counts.values()), matched_customers=len(matched),
                  customers_without_bills=len(wanted-matched), type40_customers=len(type40),
                  customers_without_type40_bills=len(wanted-type40), bills_by_type=dict(counts),
                  removed_customer_id_bom_rows=normalized_bom_rows)
    (output.parent/'qom_city_bills_1403_preparation.json').write_text(json.dumps(report, indent=2)+'\n')
    config_path = ROOT/'configs/city_final.json'
    config = json.loads(config_path.read_text())
    config['bills_path'] = output.relative_to(ROOT).as_posix()
    config_path.write_text(json.dumps(config, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
