"""Strict ingestion, source-row identity, quarantine ledger and frozen cohorts."""
import csv, hashlib, re
from pathlib import Path
import numpy as np
import pandas as pd
import jdatetime
COLUMNS=['SubscriptionNumber','FromDate','ToDate','Consumption','ConsumptionType','UnitCount','Capacity']
EPOCH=pd.Timestamp('1970-01-01')

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def date_ordinal(text):
    from datetime import datetime
    value=datetime.strptime(text,'%Y-%m-%d').date()
    if value.isoformat()!=text: raise ValueError('Noncanonical date')
    return (value-EPOCH.date()).days

def jalali_date(ordinal):
    from datetime import timedelta
    return jdatetime.date.fromgregorian(date=EPOCH.date()+timedelta(days=int(ordinal))).isoformat()

def calendar_check(cfg):
    start=date_ordinal(cfg.target_start); end=date_ordinal(cfg.target_end_exclusive)
    if start>=end: raise ValueError('Empty target')
    candidate=cfg.target_jalali_year_candidate
    if cfg.target_year_confirmed:
        return {'candidate_year':candidate,'start_gregorian':cfg.target_start,
                'last_gregorian':str(pd.Timestamp(end-1,unit='D').date()),'days':end-start,
                'mapping_verified':True,'intended_year_confirmed':True,
                'start_jalali':jalali_date(start),'last_jalali':jalali_date(end-1)}
    expected_start=jdatetime.date(candidate,11,1).togregorian().isoformat()
    expected_end=jdatetime.date(candidate,12,30).togregorian().isoformat()
    if cfg.target_start!=expected_start or jalali_date(end-1)!=f'{candidate:04d}-12-30': raise ValueError('Target differs from provisional Jalali year mapping')
    return {'candidate_year':candidate,'start_gregorian':expected_start,'last_gregorian':expected_end,'days':end-start,'mapping_verified':True,'intended_year_confirmed':cfg.target_year_confirmed}

def normalize_frame(raw,source_hash='synthetic',source_file='fixture.csv',allow_sample=False,row_start=2):
    if list(raw.columns) != COLUMNS:
        raise ValueError('Exact seven columns required')
    raw = raw.astype('string[pyarrow]').copy()
    if any(raw[column].str.contains('[\r\n]', regex=True).fillna(False).any() for column in COLUMNS):
        raise ValueError('Multiline records unsupported: physical provenance requires audit')

    # Identity refers to the physical row in this exact source file.
    normalized = raw.copy()
    normalized['source_row'] = np.arange(row_start, row_start + len(normalized), dtype=np.int64)
    normalized['source_file'] = source_file
    normalized['source_file_sha256'] = source_hash
    normalized['bill_id'] = pd.array(
        [hashlib.sha256(f'{source_hash}:{source_row}'.encode()).hexdigest() for source_row in normalized.source_row],
        dtype='string[pyarrow]',
    )
    for column in COLUMNS[1:]:
        normalized['raw_' + column] = raw[column]
    normalized['record_status'] = 'accepted'
    normalized['exclusion_reason'] = pd.Series(
        [None] * len(normalized), index=normalized.index, dtype='string[pyarrow]'
    )

    valid_ids = raw.SubscriptionNumber.str.fullmatch(r'\d{11}')
    if allow_sample:
        valid_ids = valid_ids | raw.SubscriptionNumber.str.fullmatch(r'CUSTOMER_[A-Za-z0-9_]+')
    # Accumulate row failures while retaining the original records for auditing.
    invalid = ~valid_ids.fillna(False)
    for column in COLUMNS:
        invalid |= raw[column].isna() | (raw[column].str.strip() == '')
    for column in ['FromDate', 'ToDate']:
        valid_date_format = raw[column].str.fullmatch(r'\d{4}-\d{2}-\d{2}').fillna(False)
        parsed_dates = pd.to_datetime(raw[column], format='%Y-%m-%d', errors='coerce', exact=True)
        invalid |= ~valid_date_format | parsed_dates.isna()
        normalized['start_ordinal' if column == 'FromDate' else 'inclusive_end_ordinal'] = (
            (parsed_dates - EPOCH).dt.days
        ).astype('Int64')

    # Convert inclusive source endpoints to half-open intervals for array slicing.
    normalized['end_ordinal'] = normalized.inclusive_end_ordinal + 1
    normalized['day_count'] = normalized.end_ordinal - normalized.start_ordinal
    invalid |= (normalized.day_count <= 0).fillna(True)
    for column in COLUMNS[3:]:
        numeric_values = pd.to_numeric(raw[column], errors='coerce').astype('float64')
        invalid |= ~np.isfinite(numeric_values)
        if column == 'Consumption':
            invalid |= numeric_values < 0
        if column != 'ConsumptionType':
            normalized[column] = numeric_values
    normalized.loc[invalid, 'record_status'] = 'rejected_invalid'
    normalized.loc[invalid, 'exclusion_reason'] = 'invalid_field_or_interval'
    normalized['source_calendar'] = 'Gregorian_operational_unconfirmed'
    normalized['endpoint_convention'] = 'inclusive_provisional'
    normalized['consumption_unit'] = 'source_units_unknown'
    normalized['model_group_id'] = 'unassigned'
    return normalized


def audit_normalized(df, deduplicate_confirmed=False, *, cfg=None):
    """Quarantine ambiguous histories and internal gaps intersecting the target."""
    from .config import Config

    config = Config() if cfg is None else cfg
    target_start = date_ordinal(config.target_start)
    target_end = date_ordinal(config.target_end_exclusive)
    audited = df.copy()
    raw_columns = ['SubscriptionNumber'] + ['raw_' + column for column in COLUMNS[1:]]
    duplicate_rows = audited.duplicated(raw_columns, keep=False)
    excess_duplicates = audited.duplicated(raw_columns, keep='first')
    duplicate_customers = set(audited.loc[duplicate_rows, 'SubscriptionNumber'])
    if deduplicate_confirmed:
        audited.loc[excess_duplicates, 'record_status'] = 'removed_exact_duplicate'
        audited.loc[excess_duplicates, 'exclusion_reason'] = 'confirmed_exact_duplicate'
        duplicate_customers = set()

    accepted = audited[audited.record_status == 'accepted']
    ordered = accepted.sort_values(
        ['SubscriptionNumber', 'start_ordinal', 'end_ordinal'], kind='stable'
    )
    customer_ids = ordered.SubscriptionNumber.to_numpy()
    starts = ordered.start_ordinal.to_numpy(dtype=np.int64)
    ends = ordered.end_ordinal.to_numpy(dtype=np.int64)
    conflict_customers = set()
    target_gap_customers = set()
    overlap_pairs = 0
    gap_days = 0
    adjacent = 0
    current_customer = None
    active_endpoints = []
    furthest_end = None
    for customer, interval_start, interval_end in zip(customer_ids, starts, ends):
        if customer != current_customer:
            current_customer = customer
            active_endpoints = []
            furthest_end = None
        # Equal endpoints are adjacent: intervals are half-open.
        active_endpoints = [end for end in active_endpoints if end > interval_start]
        overlap_pairs += len(active_endpoints)
        if active_endpoints:
            conflict_customers.add(customer)
        active_endpoints.append(interval_end)
        if furthest_end is not None:
            if interval_start > furthest_end:
                gap_days += int(interval_start - furthest_end)
                # Only internal gaps overlapping the requested target invalidate history.
                if max(furthest_end, target_start) < min(interval_start, target_end):
                    target_gap_customers.add(customer)
            elif interval_start == furthest_end:
                adjacent += 1
        furthest_end = max(furthest_end, interval_end) if furthest_end is not None else interval_end

    invalid_customers = set(
        audited.loc[audited.record_status == 'rejected_invalid', 'SubscriptionNumber'].dropna()
    )
    quarantine = conflict_customers | duplicate_customers | invalid_customers | target_gap_customers
    # Preserve existing rejection statuses; quarantine the remaining accepted history.
    quarantine_mask = audited.SubscriptionNumber.isin(quarantine) & (audited.record_status == 'accepted')
    audited.loc[quarantine_mask, 'record_status'] = 'quarantined_customer'
    audited.loc[quarantine_mask, 'exclusion_reason'] = 'rejected_conflict'
    gap_only_customers = target_gap_customers - (conflict_customers | duplicate_customers | invalid_customers)
    audited.loc[quarantine_mask & audited.SubscriptionNumber.isin(gap_only_customers), 'exclusion_reason'] = 'internal_target_gap'
    counts = audited.record_status.value_counts().to_dict()
    volumes = {
        status: float(group.Consumption[np.isfinite(group.Consumption)].sum())
        for status, group in audited.groupby('record_status')
    }
    audit = {
        'rows': len(audited),
        'customers': int(audited.SubscriptionNumber.nunique()),
        'record_status_counts': counts,
        'volume_ledger_source_units': volumes,
        'quarantined_customers': len(quarantine),
        'exact_duplicate_excess_rows': int(excess_duplicates.sum()),
        'duplicate_confirmation': deduplicate_confirmed,
        'same_customer_overlap_pairs': overlap_pairs,
        'internal_gap_days_before_quarantine': gap_days,
        'internal_target_gap_customers': len(target_gap_customers),
        'adjacent_pairs': adjacent,
        'zero_bill_rows': int((audited.Consumption == 0).sum()),
        'negative_rows': int((audited.Consumption < 0).sum()),
        'invalid_rows': int((audited.record_status == 'rejected_invalid').sum()),
    }
    assert sum(counts.values()) == len(audited)
    return audited, audit


def read_bills(path, cfg, allow_sample=False):
    path = Path(path)
    source_hash = sha256(path)
    # Require one record per physical line so source-row identities stay accurate.
    with path.open(encoding='utf-8-sig', newline='') as f:
        if next(csv.reader(f)) != COLUMNS:
            raise ValueError('Unexpected bill header')
        for line_number, line in enumerate(f, 2):
            if not line.strip():
                raise ValueError(f'Blank physical CSV line {line_number}')
            try:
                fields = next(csv.reader([line], strict=True))
            except csv.Error as exc:
                raise ValueError(f'Multiline or invalid CSV at physical line {line_number}') from exc
            if len(fields) != len(COLUMNS):
                raise ValueError(f'CSV shape at physical line {line_number}')

    normalized_chunks = []
    next_source_row = 2
    for raw_chunk in pd.read_csv(
        path,
        encoding='utf-8-sig',
        dtype='string[pyarrow]',
        keep_default_na=False,
        chunksize=cfg.ingestion_chunk_size,
        on_bad_lines='error',
    ):
        normalized_chunk = normalize_frame(
            raw_chunk, source_hash, path.name, allow_sample, next_source_row
        )
        next_source_row += len(normalized_chunk)
        normalized_chunks.append(normalized_chunk)
    return audit_normalized(pd.concat(normalized_chunks, ignore_index=True), cfg=cfg)

def coverage_classes(df, start, end):
    result = {ident: ('none', 0) for ident in df.SubscriptionNumber.dropna().unique()}
    accepted = df[df.record_status == 'accepted'].sort_values(
        ['SubscriptionNumber', 'start_ordinal', 'end_ordinal'], kind='stable'
    )
    ids = accepted.SubscriptionNumber.to_numpy()
    starts = accepted.start_ordinal.to_numpy(dtype=np.int64)
    ends = accepted.end_ordinal.to_numpy(dtype=np.int64)
    current_customer = None
    covered_until = None
    covered_days = 0

    def finish(ident, n):
        if ident is not None:
            if n == end - start:
                result[ident] = ('full', int(n))
            elif n:
                result[ident] = ('partial', int(n))
            else:
                result[ident] = ('none', int(n))

    for ident, interval_start, interval_end in zip(ids, starts, ends):
        if ident != current_customer:
            finish(current_customer, covered_days)
            current_customer = ident
            covered_until = None
            covered_days = 0
        # Clip only for coverage counting; the original bill intervals stay intact.
        interval_start = max(int(interval_start), start)
        interval_end = min(int(interval_end), end)
        if interval_start >= interval_end:
            continue
        if covered_until is None or interval_start > covered_until:
            covered_days += interval_end - interval_start
            covered_until = interval_end
        elif interval_end > covered_until:
            covered_days += interval_end - covered_until
            covered_until = interval_end
    finish(current_customer, covered_days)
    return result

def hash_sample(identifiers,count,seed):
    order=sorted(identifiers,key=lambda x:(hashlib.sha256((seed+str(x)).encode()).hexdigest(),str(x)))
    return order if count is None else order[:count]

def prepare_state(
    bills, origin, n_days, *, verbose=False,
    sample_path='outputs/prepared_state_sample.json', sample_size=5,
):
    """Prepare ordered bill arrays; optionally write the first bills for inspection.

    sample_path is relative to the working directory unless absolute. The sample
    contains prepared inputs, not solver allocations, and replaces that file.
    """
    from .solver import State

    # Preserve the caller's canonical bill order for sequential solver updates.
    starts = bills.start_ordinal.to_numpy(dtype=np.int64) - origin
    lengths = bills.day_count.to_numpy(dtype=np.int64)
    offsets = np.concatenate(([0], np.cumsum(lengths, dtype=np.int64)))
    totals = bills.Consumption.to_numpy(dtype=np.float64)
    ordered_bill_ids = "|".join(bills.bill_id.astype(str))
    identity_token = hashlib.sha256(ordered_bill_ids.encode()).hexdigest()
    state = State(starts, lengths, totals, offsets, n_days, identity_token).validate()

    if verbose:
        import json
        from datetime import timedelta

        if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 1:
            raise ValueError('sample_size must be a positive integer')
        sample_count = min(sample_size, len(starts))
        origin_date = EPOCH.date() + timedelta(days=int(origin))
        records = []
        for index in range(sample_count):
            bill = bills.iloc[index]
            start = int(starts[index])
            length = int(lengths[index])
            records.append({
                'bill_index': index,
                'bill_id': str(bill.bill_id),
                'SubscriptionNumber': str(bill.SubscriptionNumber),
                'start_date': (origin_date + timedelta(days=start)).isoformat(),
                'end_date_exclusive': (origin_date + timedelta(days=start + length)).isoformat(),
                'timeline_start_index': start,
                'timeline_end_index_exclusive': start + length,
                'length_days': length,
                'bill_total': float(totals[index]),
                'allocation_offset_start': int(offsets[index]),
                'allocation_offset_end_exclusive': int(offsets[index + 1]),
            })
        sample = {
            'description': 'Prepared solver inputs only; daily allocations are not computed yet.',
            'selection': 'First bills in supplied solver order; not a representative sample.',
            'origin_date': origin_date.isoformat(),
            'origin_ordinal': int(origin),
            'n_days': int(n_days),
            'total_bills': len(starts),
            'total_allocation_values': int(offsets[-1]),
            'identity_token': identity_token,
            'sample_bill_count': sample_count,
            'sample_arrays': {
                'starts': starts[:sample_count].tolist(),
                'lengths': lengths[:sample_count].tolist(),
                'totals': totals[:sample_count].tolist(),
                'offsets': offsets[:sample_count + 1].tolist(),
            },
            'bills': records,
        }
        destination = Path(sample_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(sample, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return state
