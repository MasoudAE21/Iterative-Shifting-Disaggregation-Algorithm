"""Import -> audit -> weather -> population -> full ISD -> reconcile -> export."""
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import hashlib, importlib.metadata, json, math, os, platform, threading, time, uuid
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import psutil
from .errors import AvailabilityError
from .config import Config
from .data import read_bills,sha256,date_ordinal,jalali_date,calendar_check,coverage_classes,hash_sample,prepare_state,EPOCH
from .weather import read_weather,daily_integral,build_design,weather_features
from .solver import initialize,solve,lstsq_diagnostics,aggregate_kernel,correct_roundoff

class PeakMemory:
    """Sample process RSS during the context and record its elapsed time."""

    def __enter__(self):
        self.peak = 0
        self.done = threading.Event()
        self.start = time.perf_counter()
        self.process = psutil.Process()

        def sample():
            while not self.done.is_set():
                self.peak = max(self.peak, self.process.memory_info().rss)
                self.done.wait(.02)

        self.thread = threading.Thread(target=sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.peak = max(self.peak, self.process.memory_info().rss)
        self.done.set()
        self.thread.join()
        self.seconds = time.perf_counter() - self.start

def clean_json(value):
    """Normalize nested metadata, mapping nonfinite floats to JSON null."""
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value

def write_json(path, value):
    """Write normalized metadata as indented UTF-8 JSON."""
    Path(path).write_text(
        json.dumps(clean_json(value), indent=2, ensure_ascii=False, allow_nan=False),
        encoding='utf-8',
    )

def source_fingerprint(root):
    """Hash the selected project files and their combined path-to-hash mapping."""
    paths = (
        [root/'run_pipeline.py', root/'requirements.txt', root/'README.md']
        + sorted((root/'isd').glob('*.py'))
        + sorted((root/'tests').glob('*.py'))
        + sorted((root/'configs').glob('*.json'))
        + sorted((root/'scripts').glob('*.py'))
    )
    file_hashes = {
        str(path.relative_to(root)): sha256(path)
        for path in paths if path.exists()
    }
    combined_hash = hashlib.sha256(
        json.dumps(file_hashes, sort_keys=True).encode()
    ).hexdigest()
    return {'source_sha256': combined_hash, 'files': file_hashes}

class RowWriter:
    """Buffer rows for chunked Parquet output; count includes buffered rows."""

    def __init__(self, path, schema, chunk):
        self.writer = pq.ParquetWriter(path, schema, compression='zstd')
        self.schema = schema
        self.chunk = chunk
        self.rows = []
        self.count = 0

    def append(self, row):
        self.rows.append(row)
        self.count += 1
        if len(self.rows) >= self.chunk:
            self.flush()

    def flush(self):
        if self.rows:
            self.writer.write_table(
                pa.Table.from_pylist(self.rows, schema=self.schema),
                row_group_size=self.chunk,
            )
            self.rows = []

    def close(self):
        self.flush()
        self.writer.close()

def schema_for(kind):
    """Return the bill-daily schema, or the target-customer schema otherwise."""
    string = pa.string()
    day = pa.date32()
    number = pa.float64()
    if kind == 'bill_daily':
        return pa.schema([
            ('run_id', string),
            ('model_group_id', string),
            ('bill_id', string),
            ('SubscriptionNumber', string),
            ('source_row', pa.int64()),
            ('date_gregorian', day),
            ('estimated_consumption', number),
            ('method', string),
            ('estimate_status', string),
        ])
    return pa.schema([
        ('run_id', string),
        ('SubscriptionNumber', string),
        ('date_gregorian', day),
        ('date_jalali', string),
        ('estimated_consumption', number),
        ('bill_id', string),
        ('model_group_id', string),
        ('coverage_class', string),
        ('method', string),
        ('estimate_status', string),
        ('reason', string),
    ])

def canonical(df):
    """Order bills by customer and interval, with a fresh positional index."""
    return df.sort_values(
        ['SubscriptionNumber', 'start_ordinal', 'end_ordinal', 'bill_id'],
        kind='stable',
    ).reset_index(drop=True)

def population(df, cfg):
    """Return selected bill records, customer coverage classes, and diagnostics.

    Coverage uses accepted bills within the target window. Selection retains all
    records for each chosen customer, including rejected and out-of-target bills.
    """
    target_start, target_end_exclusive = (
        date_ordinal(cfg.target_start), date_ordinal(cfg.target_end_exclusive)
    )
    classes = coverage_classes(df, target_start, target_end_exclusive)
    full_coverage_customers = [
        customer_id
        for customer_id, (coverage_class, covered_days) in classes.items()
        if coverage_class == 'full'
    ]
    eligible_customers = (
        list(classes) if cfg.sample_scope == 'universe' else full_coverage_customers
    )
    selected_ids = hash_sample(eligible_customers, cfg.max_customers, cfg.sample_seed)
    selected = canonical(df[df.SubscriptionNumber.isin(selected_ids)].copy())
    selected_classes = {customer_id: classes[customer_id] for customer_id in selected_ids}
    return selected, selected_classes, {
        'source_customers': len(classes),
        'source_coverage_counts': dict(Counter(
            coverage_kind for coverage_kind, covered_days in classes.values()
        )),
        'source_balanced_candidates': len(full_coverage_customers),
        'selection': 'SHA256(seed + SubscriptionNumber) ascending; all bills retained',
        'seed': cfg.sample_seed,
        'sample_scope': cfg.sample_scope,
        'selected_customers': len(selected_ids),
        'selected_coverage_counts': dict(Counter(
            coverage_kind for coverage_kind, covered_days in selected_classes.values()
        )),
        'selected_covered_customer_days': sum(
            covered_days for coverage_kind, covered_days in selected_classes.values()
        ),
        'selected_null_customer_days': sum(
            target_end_exclusive - target_start - covered_days
            for coverage_kind, covered_days in selected_classes.values()
        ),
    }

def allocate_model(accepted, classes, daily, origin, cfg, out):
    """Prepare the modeled population and solve, allowing cohort availability fallback.

    Returns modeled bills, optional solver result, bill-ID-to-position lookup,
    diagnostics, optional design matrix, fit-day mask, and daily exposure.
    Uniform fallback allocations are produced later during export.
    """
    cfg.validate()
    if cfg.resume and (not cfg.checkpoint or not (out / 'checkpoint.npz').exists()):
        raise ValueError('No resume checkpoint')
    target_start, target_end_exclusive = (
        date_ordinal(cfg.target_start), date_ordinal(cfg.target_end_exclusive)
    )
    n_days = len(daily)
    # Retain full bill intervals; the mask restricts regression observations only.
    if cfg.mode == 'paper_reference':
        modeled = accepted.copy()
        cohort_ids = set(accepted.SubscriptionNumber)
        fit_mask = np.ones(n_days, bool)
    else:
        cohort_ids = {
            customer_id for customer_id, (coverage_class, _) in classes.items()
            if coverage_class == 'full'
        }
        modeled = accepted[accepted.SubscriptionNumber.isin(cohort_ids)].reset_index(drop=True)
        fit_mask = (
            (np.arange(origin, origin + n_days) >= target_start)
            & (np.arange(origin, origin + n_days) < target_end_exclusive)
        )
    diagnostics = {
        'modeled_customers': len(cohort_ids),
        'modeled_bills': len(modeled),
        'fallback_reason': None,
    }
    result = None
    design = None
    feature_info = None
    covered_customers = np.zeros(n_days, np.int64)
    # Accepted within-customer bills do not overlap, so bill support counts customers.
    for bill_start, bill_end in zip(modeled.start_ordinal.astype(int), modeled.end_ordinal.astype(int)):
        covered_customers[bill_start - origin:bill_end - origin] += 1
    exposure = covered_customers / len(cohort_ids) if cohort_ids else np.zeros(n_days)
    if cfg.mode == 'paper_reference':
        exposure = np.ones(n_days)
    else:
        fit_mask &= (
            (covered_customers == len(cohort_ids))
            & (daily.weather_status.to_numpy() == 'complete')
        )
    if len(modeled):
        state = prepare_state(modeled, origin, n_days)
        try:
            design, feature_info = build_design(
                daily, cfg.feature_preset, fit_mask, cfg.mode, exposure,
                cfg.exposure_scaled, allow_zero_spread=bool(np.all(state.totals == 0)),
            )
            # Record rank diagnostics without performing an additional regression.
            singular_values = np.linalg.svd(design[fit_mask], compute_uv=False)
            rcond = (
                cfg.regression_rcond if cfg.regression_rcond is not None
                else max(int(fit_mask.sum()), design.shape[1]) * np.finfo(float).eps
            )
            rank = int(np.sum(singular_values > rcond * singular_values[0])) if len(singular_values) else 0
            diagnostics['initial_rank'] = {
                'rank': rank,
                'columns': design.shape[1],
                'n_fit': int(fit_mask.sum()),
                'singular_values': singular_values.tolist(),
                'diagnostic_only_svd_no_extra_regression': True,
            }
            result = solve(
                state, design, cfg, fit_mask,
                out / 'checkpoint.npz' if cfg.checkpoint else None,
                out / 'allocations.memmap', exposure=exposure,
            )
        except AvailabilityError as e:
            if cfg.mode == 'paper_reference' or cfg.resume:
                raise
            diagnostics['fallback_reason'] = (
                'weather_unavailable' if 'weather_unavailable' in str(e)
                else 'fit_unavailable'
            )
            diagnostics['fallback_detail'] = str(e)
        diagnostics['allocated_model_interval_days'] = int(state.offsets[-1])
    else:
        diagnostics['fallback_reason'] = 'fit_unavailable'
        diagnostics['allocated_model_interval_days'] = 0
    diagnostics.update({
        'feature_scaling': feature_info,
        'exposure_scaled_design': cfg.mode != 'paper_reference' and cfg.exposure_scaled,
        'fit_dates': [str(fit_date) for fit_date in daily.loc[fit_mask, 'date_gregorian']],
        'g': exposure.tolist(),
        'n_cohort_covered': covered_customers.tolist(),
    })
    bill_lookup = (
        {str(bill_id): bill_index for bill_index, bill_id in enumerate(modeled.bill_id)}
        if result is not None else {}
    )
    return (modeled, result, bill_lookup, diagnostics, design, fit_mask, exposure)

def export_outputs(selected, classes, daily, origin, cfg, out, run_id, modeled, result, lookup, diagnostics):
    """Write reconciled bill allocations, target customer days, and aggregate summaries.

    Returns export audit statistics and baseline comparisons. Accepted bills
    without solver allocations receive uniform full-interval fallback.
    """
    # Prepare full-domain totals and output writers.
    accepted = selected[selected.record_status == 'accepted'].reset_index(drop=True)
    n_days = len(daily)
    target_start = date_ordinal(cfg.target_start)
    target_end_exclusive = date_ordinal(cfg.target_end_exclusive)
    model_offsets = np.concatenate(([0], np.cumsum(modeled.day_count.to_numpy(dtype=np.int64))))
    dates = [
        EPOCH.date() + timedelta(days=int(day_ordinal))
        for day_ordinal in range(origin, origin + n_days)
    ]
    combined_sum = np.zeros(n_days)
    uniform_sum = np.zeros(n_days)
    weighted_sum = np.zeros(n_days)
    fallback_sum = np.zeros(n_days)
    model_sum = np.zeros(n_days)
    covered_customers = np.zeros(n_days, np.int64)
    zero_customers = np.zeros(n_days, np.int64)
    reconciliation_errors = []
    method_bill_counts = Counter()
    method_interval_days = Counter()
    bill_writer = RowWriter(out / 'full_bill_daily.parquet', schema_for('bill_daily'), cfg.row_group_size)
    reconciliation_schema = pa.schema([
        ('run_id', pa.string()),
        ('bill_id', pa.string()),
        ('SubscriptionNumber', pa.string()),
        ('source_row', pa.int64()),
        ('bill_total', pa.float64()),
        ('full_daily_sum', pa.float64()),
        ('signed_discrepancy', pa.float64()),
        ('absolute_discrepancy', pa.float64()),
        ('target_daily_sum', pa.float64()),
        ('outside_target_sum', pa.float64()),
        ('method', pa.string()),
        ('passed', pa.bool_()),
    ])
    reconciliation_writer = RowWriter(out / 'bill_reconciliation.parquet', reconciliation_schema, cfg.row_group_size)
    features = weather_features(daily)
    weights = 1 + features['HDD65']
    weather_weights_available = np.isfinite(weights).all()

    # Expand fallback allocations one bill at a time.
    def allocation(r):
        length = int(r.day_count)
        day_index = int(r.start_ordinal) - origin
        total = float(r.Consumption)
        if str(r.bill_id) in lookup:
            bill_index = lookup[str(r.bill_id)]
            allocations = result.allocations[model_offsets[bill_index]:model_offsets[bill_index + 1]]
            method = (
                'paper_reference_isd' if cfg.mode == 'paper_reference'
                else 'cohort_exposure_isd' if cfg.exposure_scaled
                else 'cohort_masked_unscaled_isd'
            )
            reason = 'none'
        else:
            allocations = correct_roundoff(np.full(length, total / length), total, cfg)
            method = 'uniform_full_interval'
            reason = (
                diagnostics['fallback_reason']
                if classes[str(r.SubscriptionNumber)][0] == 'full' and diagnostics['fallback_reason']
                else 'partial_target_coverage'
            )
        return (allocations, day_index, method, reason)

    # Reconcile each complete bill before exporting its daily allocations.
    for r in accepted.itertuples(index=False):
        allocations, day_index, method, reason = allocation(r)
        length = len(allocations)
        total = float(r.Consumption)
        method_bill_counts[method] += 1
        method_interval_days[method] += length
        uniform = correct_roundoff(np.full(length, total / length), total, cfg)
        if weather_weights_available:
            bill_weights = weights[day_index:day_index + length]
            weighted = correct_roundoff(total * (bill_weights / math.fsum(bill_weights)), total, cfg)
        else:
            weighted = np.full(length, np.nan)
        combined_sum[day_index:day_index + length] += allocations
        uniform_sum[day_index:day_index + length] += uniform
        weighted_sum[day_index:day_index + length] += weighted
        covered_customers[day_index:day_index + length] += 1
        if total == 0:
            zero_customers[day_index:day_index + length] += 1
        if method.endswith('_isd'):
            model_sum[day_index:day_index + length] += allocations
        else:
            fallback_sum[day_index:day_index + length] += allocations
        target_slice_start = max(0, target_start - int(r.start_ordinal))
        target_slice_end = min(length, target_end_exclusive - int(r.start_ordinal))
        target_bill_sum = (
            math.fsum(allocations[target_slice_start:target_slice_end])
            if target_slice_end > target_slice_start else 0.0
        )
        full_bill_sum = math.fsum(allocations)
        outside_target_sum = full_bill_sum - target_bill_sum
        discrepancy = full_bill_sum - total
        passed = abs(discrepancy) <= cfg.reconciliation_atol + cfg.reconciliation_rtol * abs(total)
        if not passed or np.any(allocations < 0) or (not np.isfinite(allocations).all()):
            raise ArithmeticError('Export conservation/nonnegativity')
        reconciliation_writer.append({
            'run_id': run_id,
            'bill_id': str(r.bill_id),
            'SubscriptionNumber': str(r.SubscriptionNumber),
            'source_row': int(r.source_row),
            'bill_total': total,
            'full_daily_sum': full_bill_sum,
            'signed_discrepancy': discrepancy,
            'absolute_discrepancy': abs(discrepancy),
            'target_daily_sum': target_bill_sum,
            'outside_target_sum': outside_target_sum,
            'method': method,
            'passed': passed,
        })
        reconciliation_errors.append(abs(discrepancy))
        for day_offset, value in enumerate(allocations):
            bill_writer.append({
                'run_id': run_id,
                'model_group_id': 'shared_population' if method.endswith('_isd') else 'fallback',
                'bill_id': str(r.bill_id),
                'SubscriptionNumber': str(r.SubscriptionNumber),
                'source_row': int(r.source_row),
                'date_gregorian': dates[day_index + day_offset],
                'estimated_consumption': float(value),
                'method': method,
                'estimate_status': 'recorded_zero' if total == 0 else 'estimated',
            })
    bill_writer.close()
    reconciliation_writer.close()

    # Emit every selected customer and target day, preserving unavailable values.
    target_writer = RowWriter(out / 'target_customer_daily.parquet', schema_for('target'), cfg.row_group_size)
    target_sum = np.zeros(target_end_exclusive - target_start)
    target_numeric_rows = target_null_rows = 0
    quarantined_customers = set(selected.loc[selected.record_status != 'accepted', 'SubscriptionNumber'])
    gap_customers = set(selected.loc[selected.exclusion_reason == 'internal_target_gap', 'SubscriptionNumber'])
    records = iter(accepted.itertuples(index=False))
    current = next(records, None)
    target_dates = [EPOCH.date() + timedelta(days=int(day_index)) for day_index in range(target_start, target_end_exclusive)]
    jalali = [jalali_date(day_index) for day_index in range(target_start, target_end_exclusive)]
    for customer_id in sorted(classes):
        values = [None] * (target_end_exclusive - target_start)
        bill_ids = [None] * (target_end_exclusive - target_start)
        daily_methods = ['none'] * (target_end_exclusive - target_start)
        reasons = [
            'internal_target_gap' if customer_id in gap_customers
            else 'rejected_conflict' if customer_id in quarantined_customers
            else 'no_target_bill'
        ] * (target_end_exclusive - target_start)
        recorded_zero = [False] * (target_end_exclusive - target_start)
        while current is not None and str(current.SubscriptionNumber) == str(customer_id):
            r = current
            current = next(records, None)
            allocations, day_index, method, reason = allocation(r)
            for day in range(max(target_start, int(r.start_ordinal)), min(target_end_exclusive, int(r.end_ordinal))):
                target_index = day - target_start
                if values[target_index] is not None:
                    raise ArithmeticError('Unresolved overlap in customer export')
                values[target_index] = float(allocations[day - int(r.start_ordinal)])
                bill_ids[target_index] = str(r.bill_id)
                daily_methods[target_index] = method
                reasons[target_index] = reason
                recorded_zero[target_index] = r.Consumption == 0
        for day_offset, value in enumerate(values):
            if value is None:
                target_null_rows += 1
            else:
                target_numeric_rows += 1
                target_sum[day_offset] += value
            target_writer.append({
                'run_id': run_id,
                'SubscriptionNumber': str(customer_id),
                'date_gregorian': target_dates[day_offset],
                'date_jalali': jalali[day_offset],
                'estimated_consumption': value,
                'bill_id': bill_ids[day_offset],
                'model_group_id': (
                    'shared_population' if daily_methods[day_offset].endswith('_isd')
                    else 'fallback' if value is not None else None
                ),
                'coverage_class': classes[customer_id][0],
                'method': daily_methods[day_offset],
                'estimate_status': (
                    'unavailable' if value is None
                    else 'recorded_zero' if recorded_zero[day_offset] else 'estimated'
                ),
                'reason': reasons[day_offset],
            })
    target_writer.close()

    # Align by date even when the domain excludes unsupported target days.
    for day_offset, day in enumerate(range(target_start, target_end_exclusive)):
        expected = combined_sum[day - origin] if origin <= day < origin + n_days else 0
        if not np.isclose(target_sum[day_offset], expected, atol=1e-07, rtol=1e-10):
            raise ArithmeticError('Customer/aggregate target identity')
    last_prediction = result.prediction if result is not None else np.full(n_days, np.nan)
    aggregate = pd.DataFrame({
        'run_id': run_id,
        'date_gregorian': dates,
        'cohort_isd_sum': model_sum,
        'observed_partial_or_failed_uniform_sum': fallback_sum,
        'combined_observed_support_sum': combined_sum,
        'uniform_baseline_sum': uniform_sum,
        'weather_weighted_baseline_sum': weighted_sum,
        'predicted_profile_last_outer': last_prediction,
        'n_customers_covered': covered_customers,
        'n_bills_covered': covered_customers,
        'n_zero_customers': zero_customers,
        'missing_customer_count': len(classes) - covered_customers,
        'coverage_fraction': covered_customers / max(1, len(classes)),
        'fit_eligible': [result is not None and str(date) in diagnostics['fit_dates'] for date in dates],
        'weather_status': daily.weather_status,
        'extrapolation_flag': [
            not target_start <= origin + domain_index < target_end_exclusive
            for domain_index in range(n_days)
        ],
    })
    aggregate.to_parquet(out / 'aggregate_daily.parquet', index=False)
    aggregate.to_csv(out / 'aggregate_daily_summary.csv', index=False)
    # Baseline differences describe allocation shape, not measured daily error.
    comparison = []
    target_mask = (
        (np.arange(origin, origin + n_days) >= target_start)
        & (np.arange(origin, origin + n_days) < target_end_exclusive)
    )
    for name, baseline_sum in [('uniform', uniform_sum), ('weather_weighted_baseload1_hdd65', weighted_sum)]:
        baseline_difference = combined_sum[target_mask] - baseline_sum[target_mask]
        comparison.append({
            'baseline': name,
            'target_aggregate_mean_absolute_difference': (
                float(np.mean(np.abs(baseline_difference))) if len(baseline_difference) else None
            ),
            'target_aggregate_max_absolute_difference': (
                float(np.max(np.abs(baseline_difference))) if len(baseline_difference) else None
            ),
            'target_baseline_total_source_units': float(np.sum(baseline_sum[target_mask])),
            'target_pipeline_total_source_units': float(np.sum(combined_sum[target_mask])),
            'interpretation': 'Shape difference, not measured error; no independent daily truth',
        })
    pd.DataFrame(comparison).to_csv(out / 'baseline_comparison.csv', index=False)
    audit = {
        'full_bill_daily_rows': bill_writer.count,
        'target_customer_daily_rows': target_writer.count,
        'target_numeric_rows': target_numeric_rows,
        'target_null_rows': target_null_rows,
        'bill_reconciliation_passed': len(reconciliation_errors),
        'max_bill_abs_discrepancy': max(reconciliation_errors, default=0),
        'methods_bill_counts': dict(method_bill_counts),
        'methods_interval_days': dict(method_interval_days),
        'allocated_interval_days': int(accepted.day_count.sum()),
        'total_bill_consumption_source_units': float(accepted.Consumption.sum()),
        'full_allocation_sum': float(combined_sum.sum()),
        'full_target_export_identities_passed': True,
        'baseline_definitions': {
            'uniform': 'B/L on complete bill interval',
            'weather_weighted': 'B * (1+HDD65) / sum_interval(1+HDD65); fixed, no regression or shifting',
            'ols': 'last immutable aggregate prediction; diagnostic, not bill reconciled',
        },
    }
    return (audit, comparison)

def run(root, cfg, output_dir=None, bills_path=None, weather_path=None, preloaded=None):
    """Execute ingestion, modeling, exports, and provenance recording.

    Writes artifacts to the output directory and returns the run manifest.
    Preloaded data must already be audited for the supplied configuration.
    """
    root = Path(root).resolve()
    cfg.validate()
    calendar_mapping = calendar_check(cfg)
    run_id = uuid.uuid4().hex
    out = Path(output_dir) if output_dir else root / 'outputs' / 'ide_pilot'
    out.mkdir(parents=True, exist_ok=True)
    # Invalidate prior completion artifacts while retaining resume state.
    for name in (
        'run_manifest.json',
        'run_summary.csv',
        'peak_summary.md',
        'customer_peak_consumption.csv',
        'target_customer_daily.parquet',
        'peak_missing_reasons.csv',
        'peak_daily_totals.csv',
    ):
        (out / name).unlink(missing_ok=True)
    bills_path = Path(bills_path) if bills_path else root / 'data' / 'bill_1403.csv'
    weather_path = Path(weather_path) if weather_path else next((root / 'data').glob('open-meteo*.csv'))
    with PeakMemory() as memory:
        stage_seconds = {}
        stage_rss = {}
        available_ram = psutil.virtual_memory().available
        stage_started_at = time.perf_counter()
        # Load audited bills, then select customers and the full bill domain.
        if preloaded is None:
            source, audit = read_bills(bills_path, cfg)
        else:
            source, audit = preloaded
        stage_seconds['import_audit_seconds'] = time.perf_counter() - stage_started_at
        stage_rss['after_import'] = memory.process.memory_info().rss
        stage_started_at = time.perf_counter()
        selected, classes, selection = population(source, cfg)
        stage_seconds['population_seconds'] = time.perf_counter() - stage_started_at
        accepted = selected[selected.record_status == 'accepted']
        target_start = date_ordinal(cfg.target_start)
        target_end_exclusive = date_ordinal(cfg.target_end_exclusive)
        origin = int(accepted.start_ordinal.min()) if len(accepted) else target_start
        domain_end = int(accepted.end_ordinal.max()) if len(accepted) else target_end_exclusive
        stage_started_at = time.perf_counter()
        # Integrate weather across the domain and plot the requested target dates.
        seconds, values, weather_metadata = read_weather(weather_path)
        if cfg.provider_variable_definition != 'instant' or cfg.weather_adapter != 'point_linear_integral_v1':
            raise ValueError('Unimplemented weather adapter; period orientation required')
        daily = daily_integral(
            seconds,
            values,
            np.arange(origin, domain_end),
            cfg.timezone,
            plot_directory=out / 'weather_plots',
            target_start=cfg.target_start,
            target_end_exclusive=cfg.target_end_exclusive,
        )
        daily.to_parquet(out / 'daily_weather.parquet', index=False)
        stage_seconds['weather_seconds'] = time.perf_counter() - stage_started_at
        normalized_bills = selected.copy()
        for field, ordinal_column in [('start_day', 'start_ordinal'), ('end_day_exclusive', 'end_ordinal')]:
            normalized_bills[field] = pd.to_datetime(
                normalized_bills[ordinal_column], unit='D', origin='unix', errors='coerce'
            ).dt.date
        stage_started_at = time.perf_counter()
        # Solve the modeled population and label all normalized bill records.
        (
            modeled,
            result,
            bill_lookup,
            diagnostics,
            design,
            fit_mask,
            exposure,
        ) = allocate_model(accepted, classes, daily, origin, cfg, out)
        stage_seconds['model_seconds'] = time.perf_counter() - stage_started_at
        stage_rss['after_solve_checkpoint'] = memory.process.memory_info().rss
        normalized_bills['model_group_id'] = np.where(
            normalized_bills.bill_id.astype(str).isin(bill_lookup),
            'shared_population',
            np.where(normalized_bills.record_status == 'accepted', 'fallback', None),
        )
        normalized_bills.to_parquet(out / 'normalized_bills.parquet', index=False)
        stage_started_at = time.perf_counter()
        # Export reconciled allocations before computing customer peaks.
        export_audit, baselines = export_outputs(
            selected,
            classes,
            daily,
            origin,
            cfg,
            out,
            run_id,
            modeled,
            result,
            bill_lookup,
            diagnostics,
        )
        stage_seconds['export_seconds'] = time.perf_counter() - stage_started_at
        stage_rss['after_full_and_target_export'] = memory.process.memory_info().rss
        from .peak import export_peak
        stage_started_at = time.perf_counter()
        peak = export_peak(out, classes, cfg)
        stage_seconds['peak_export_seconds'] = time.perf_counter() - stage_started_at
        # Record input hashes, source versions, configuration, and diagnostics.
        input_files = (
            [bills_path, weather_path]
            + list((root / 'data').glob('ISD_Independent_Review.docx'))
            + list((root / 'data').glob('ISD_Implementation_Handoff.docx'))
            + list((root / 'data').glob('An Iterative*.pdf'))
        )
        input_hashes = {p.name: sha256(p) for p in input_files}
        if len(source) and input_hashes[bills_path.name] != str(source.source_file_sha256.iloc[0]):
            raise RuntimeError('Source changed after ingestion')
        schema_lock = (
            json.loads((root / 'handoff' / 'data_schema.json').read_text(encoding='utf-8'))
            if (root / 'handoff' / 'data_schema.json').exists() else None
        )
        schema_hash_match = (
            all(
                input_hashes.get(locked_file['filename'], locked_file['sha256'])
                == locked_file['sha256']
                for locked_file in schema_lock['files']
            ) if schema_lock else None
        )
        manifest = {
            'run_id': run_id,
            'configuration': cfg.as_dict(),
            'inputs': input_hashes,
            'audit_hash_lock_matched': schema_hash_match,
            'code': source_fingerprint(root),
            'dependencies': {p: importlib.metadata.version(p) for p in [
                'numpy',
                'pandas',
                'pyarrow',
                'numba',
                'llvmlite',
                'jdatetime',
                'jalali-core',
                'tzdata',
                'psutil',
            ]},
            'python': platform.python_version(),
            'calendar_mapping': calendar_mapping,
            'source_audit': audit,
            'selection': selection,
            'date_domain_half_open': [
                str(EPOCH.date() + timedelta(days=origin)),
                str(EPOCH.date() + timedelta(days=domain_end)),
            ],
            'weather_metadata': weather_metadata,
            'weather_daily_complete': int((daily.weather_status == 'complete').sum()),
            'weather_daily_unavailable': int((daily.weather_status != 'complete').sum()),
            'model_diagnostics': diagnostics,
            'export': export_audit,
            'peak': peak,
            'memory_stage_rss_bytes': stage_rss,
            'available_ram_at_start': available_ram,
            'stage_wall_seconds': stage_seconds,
            'warnings': [
                'Provisional semantics and intended target year unconfirmed.',
                'Recorded consumption units and physical interpretation are unknown.',
                'No independent daily measurements supplied: consistency, plausibility and sensitivity only.',
                'Deterministic customer hash sample is not proof of representativeness.',
                'Combined observed-support aggregate mixes cohort ISD and uniform fallback; not citywide demand.',
                'Exposure scaling outside fit window assumes equal average weather response.',
            ],
        }
        if result:
            manifest['iterations'] = result.iterations
            manifest['cycles'] = result.cycles
            manifest['zero_residual_noops'] = result.zero_residual_noops
            manifest['all_zero_fast_path'] = result.all_zero_fast_path
            pd.DataFrame(result.iterations).drop(
                columns=['column_ranges', 'beta', 'singular_values', 'zero_columns'],
                errors='ignore',
            ).to_csv(out / 'iteration_summary.csv', index=False)
        else:
            manifest['zero_residual_noops'] = 0
    # Final summaries are written after the measured context exits.
    manifest['wall_seconds'] = memory.seconds
    manifest['peak_rss_bytes'] = memory.peak
    write_json(out / 'run_manifest.json', manifest)
    from .peak import write_peak_summary
    write_peak_summary(out, manifest)
    pd.DataFrame([{
        'customers': len(classes),
        'bills': len(accepted),
        'model_customers': diagnostics['modeled_customers'],
        'model_bills': diagnostics['modeled_bills'],
        'allocated_interval_days': export_audit['allocated_interval_days'],
        'model_interval_days': diagnostics['allocated_model_interval_days'],
        'wall_seconds': memory.seconds,
        'peak_rss_bytes': memory.peak,
        **{stage_name: elapsed_seconds for stage_name, elapsed_seconds in stage_seconds.items()},
    }]).to_csv(out / 'run_summary.csv', index=False)
    print(f"Completed {out}: {len(classes)} customers, {len(accepted)} bills, {export_audit['allocated_interval_days']} bill-days, {memory.seconds:.2f}s", flush=True)
    return manifest
