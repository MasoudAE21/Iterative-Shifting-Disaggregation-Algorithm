"""Run immutable branch snapshots and export comparable TBS/customer reports."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
from itertools import product
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import uuid
import zipfile

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
GRID_PARAMETERS = ('n_lr_models', 'n_disagg_cycles', 'alpha')


def expand_model_grid(settings):
    """Expand shared scalar/list settings; per-model scalar overrides take precedence."""
    shared = settings['shared_parameters']

    def validate_value(key, value):
        if key in ('n_lr_models', 'n_disagg_cycles'):
            valid = type(value) is int and value > 0
        else:
            valid = type(value) in (int, float) and np.isfinite(value) and 0 <= value <= 1
        if not valid:
            raise ValueError(f'{key}: expected a positive integer' if key != 'alpha'
                             else 'alpha: expected a finite number between 0 and 1')

    for key, value in shared.items():
        if isinstance(value, list) and key not in GRID_PARAMETERS:
            raise ValueError(f'Shared lists are supported only for {", ".join(GRID_PARAMETERS)}; got {key}')
        if key in GRID_PARAMETERS:
            choices = value if isinstance(value, list) else [value]
            if not choices:
                raise ValueError(f'{key}: list must not be empty')
            for choice in choices:
                validate_value(key, choice)
    names = [model['name'] for model in settings['models']]
    if not names or len(names) != len(set(names)):
        raise ValueError('Model names must be unique and nonempty')
    expanded = []
    for model in settings['models']:
        name = model['name']
        if not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Model name must be a folder name')
        for key, value in model['parameters'].items():
            if isinstance(value, list):
                raise ValueError(f'{name}.{key}: model parameters must be scalar; put lists in shared_parameters')
            if key in GRID_PARAMETERS:
                validate_value(key, value)
        effective = {**shared, **model['parameters']}
        keys = [key for key in GRID_PARAMETERS if key in effective]
        choices = [list(dict.fromkeys(effective[key])) if isinstance(effective[key], list)
                   else [effective[key]] for key in keys]
        combinations = list(product(*choices))
        for index, values in enumerate(combinations, start=1):
            parameters = {**effective, **dict(zip(keys, values))}
            run_name = f'{name}__g{index:03d}' if len(combinations) > 1 else name
            expanded.append({**model, 'name': run_name, 'base_model': name, 'parameters': parameters})
    if len({model['name'] for model in expanded}) != len(expanded):
        raise ValueError('Expanded run names collide; rename the base models')
    return expanded


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def metric_scores(frame, truth_scale=1.0):
    """Paired finite observations; MAPE omits measured zeros, R2 may be undefined."""
    if not np.isfinite(truth_scale) or truth_scale <= 0:
        raise ValueError('Truth scale must be finite and positive')
    actual = frame.tbs_daily_m3.to_numpy(dtype=float) * truth_scale
    predicted = frame.final_algorithm_consumption_m3.to_numpy(dtype=float)
    valid = np.isfinite(actual) & np.isfinite(predicted)
    y, pred = actual[valid], predicted[valid]
    nonzero = y != 0
    denominator = float(np.sum((y - y.mean()) ** 2)) if len(y) else 0
    pred_centered = pred - pred.mean() if len(pred) else pred
    pred_variance = float(np.sum(pred_centered ** 2))
    pearson = (float(np.clip(np.dot(y - y.mean(), pred_centered) /
                            np.sqrt(denominator * pred_variance), -1, 1))
               if len(y) >= 2 and denominator > 0 and pred_variance > 0 else None)
    return {
        'window_days': len(frame), 'matched_days': int(valid.sum()),
        'missing_pair_days': int((~valid).sum()),
        'mape_days': int(nonzero.sum()), 'zero_tbs_days': int((~nonzero).sum()),
        'mape_percent': float(100 * np.mean(np.abs((pred[nonzero] - y[nonzero]) / y[nonzero]))) if nonzero.any() else None,
        'rmse_m3': float(np.sqrt(np.mean((pred - y) ** 2))) if len(y) else None,
        'r2': float(1 - np.sum((pred - y) ** 2) / denominator) if len(y) >= 2 and denominator > 0 else None,
        'pearson_r': pearson,
    }


def metric_reports(frame, windows, exclusions, truth_scales=(1.0, 0.75)):
    dates = pd.to_datetime(frame.date_gregorian)
    excluded = dates.isin(pd.to_datetime(exclusions))
    rows = []
    masks = {}
    for name, bounds in windows.items():
        mask = pd.Series(True, index=frame.index) if bounds is None else dates.between(*bounds)
        masks[name] = mask & ~excluded
        for scale in truth_scales:
            rows.append(dict(window=name, truth_scale=scale, truth_reference=f'{scale:g} x TBS',
                             start=str(dates[mask].min().date()),
                             end_inclusive=str(dates[mask].max().date()),
                             excluded_days=int((mask & excluded).sum()),
                             **metric_scores(frame.loc[masks[name]], scale)))
    return rows, masks


def update_tbs_summary(folder, comparison, exclusions, truth_scales=(1.0, 0.75)):
    """Apply the experiment exclusions to the pipeline's built-in TBS summary too."""
    path = folder / 'run_manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    frame = comparison.loc[~comparison.date_gregorian.isin(pd.to_datetime(exclusions))]
    valid = np.isfinite(frame.tbs_daily_m3) & np.isfinite(frame.final_algorithm_consumption_m3)
    paired = frame.loc[valid]
    delta = paired.final_algorithm_consumption_m3 - paired.tbs_daily_m3
    info = manifest['tbs_comparison']
    info.update(comparison_days=len(frame),
                missing_tbs_days=int(frame.tbs_daily_m3.isna().sum()),
                missing_tbs_dates=frame.loc[frame.tbs_daily_m3.isna(), 'date_gregorian'].dt.strftime('%Y-%m-%d').tolist(),
                modeled_total_matched_m3=float(paired.final_algorithm_consumption_m3.sum()) if len(paired) else None,
                tbs_total_matched_m3=float(paired.tbs_daily_m3.sum()) if len(paired) else None,
                bias_m3=float(delta.mean()) if len(paired) else None,
                mae_m3=float(delta.abs().mean()) if len(paired) else None,
                **metric_scores(frame),
                excluded_metric_dates=exclusions,
                metric_scope='Full simulation with experiment date exclusions')
    info['truth_reference_metrics'] = [dict(truth_scale=scale, **metric_scores(frame, scale))
                                       for scale in truth_scales]
    write_json(path, manifest)


def select_customers(available, fixed, count, seed):
    available, fixed = set(map(str, available)), list(dict.fromkeys(map(str, fixed)))
    missing = sorted(set(fixed) - available)
    if missing:
        raise ValueError(f'Requested customers absent from run: {missing}')
    candidates = sorted(available - set(fixed))
    if count < 0 or count > len(candidates):
        raise ValueError('Not enough additional customers for random selection')
    return fixed + random.Random(seed).sample(candidates, count)


def add_uniform_allocations(daily, ledger):
    """Allocate each accepted effective bill total evenly over its bill days."""
    bills = ledger.loc[ledger.record_status == 'accepted'].set_index('bill_id')
    supported = daily.bill_id.notna() & daily.bill_id.ne('')
    if not daily.loc[supported, 'bill_id'].isin(bills.index).all():
        raise ValueError('Customer daily data references an unknown accepted bill')
    daily = daily.copy()
    daily['uniform_consumption_m3'] = daily.bill_id.map(bills.Consumption / bills.day_count)
    return daily


def validate_allocations(folder):
    """Independently reconcile saved bill-day values without unfiltered TBS metrics."""
    manifest = json.loads((folder / 'run_manifest.json').read_text(encoding='utf-8'))
    cfg = manifest['configuration']
    ledger = pd.read_parquet(folder / 'normalized_bills.parquet')
    bills = ledger[ledger.record_status == 'accepted'].set_index('bill_id').sort_index()
    keys = ['SubscriptionNumber', 'start_ordinal', 'end_ordinal', 'Consumption']
    digest = hashlib.sha256(bills[keys].to_csv().encode()).hexdigest()
    starts = bills.start_ordinal.to_numpy(dtype=np.int64)
    ends = bills.end_ordinal.to_numpy(dtype=np.int64)
    lengths = bills.day_count.to_numpy(dtype=np.int64)
    if not np.array_equal(ends - starts, lengths):
        raise ValueError('Bill dates and lengths disagree')
    totals = bills.Consumption.to_numpy(dtype=float)
    means = totals / lengths
    offsets = np.r_[0, np.cumsum(lengths)]
    seen = np.zeros(int(offsets[-1]), dtype=bool)
    sums = np.zeros(len(bills))
    source_starts, source_ends = starts, ends
    if {'raw_FromDate', 'raw_ToDate'} <= set(bills.columns):
        date_format = cfg.get('bill_date_format', '%Y-%m-%d')
        source_starts = pd.to_datetime(bills.raw_FromDate, format=date_format).to_numpy(dtype='datetime64[D]').astype(np.int64)
        source_ends = pd.to_datetime(bills.raw_ToDate, format=date_format).to_numpy(dtype='datetime64[D]').astype(np.int64) + 1
    minimum_ratio = float('inf')
    for batch in pq.ParquetFile(folder / 'full_bill_daily.parquet').iter_batches(
            columns=['bill_id', 'SubscriptionNumber', 'date_gregorian', 'estimated_consumption'], batch_size=100000):
        frame = batch.to_pandas()
        values = frame.estimated_consumption.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError('Nonfinite or negative bill allocation')
        indices = bills.index.get_indexer(frame.bill_id)
        if np.any(indices < 0):
            raise ValueError('Daily allocation references unknown bill')
        if not np.array_equal(frame.SubscriptionNumber.to_numpy(), bills.SubscriptionNumber.to_numpy()[indices]):
            raise ValueError('Allocation assigned to another customer')
        days = pd.to_datetime(frame.date_gregorian).to_numpy(dtype='datetime64[D]').astype(np.int64)
        if np.any((days < starts[indices]) | (days >= ends[indices])
                  | (days < source_starts[indices]) | (days >= source_ends[indices])):
            raise ValueError('Allocation outside its bill period')
        slots = offsets[indices] + days - starts[indices]
        if seen[slots].any() or len(np.unique(slots)) != len(slots):
            raise ValueError('Duplicate bill-day allocation')
        seen[slots] = True
        sums += np.bincount(indices, weights=values, minlength=len(bills))
        floors = (bills.daily_floor.to_numpy(dtype=float)[indices] if 'daily_floor' in bills
                  else cfg['redistribution_floor'] * means[indices])
        if np.any(values < floors - cfg['reconciliation_atol'] - cfg['reconciliation_rtol'] * totals[indices]):
            raise ValueError('Daily floor violated')
        positive = means[indices] > 0
        if positive.any():
            minimum_ratio = min(minimum_ratio, float(np.min(values[positive] / means[indices[positive]])))
    if not seen.all():
        raise ValueError('Missing saved bill-days')
    error = np.abs(sums - totals)
    if not (error <= cfg['reconciliation_atol'] + cfg['reconciliation_rtol'] * totals).all():
        raise ValueError('Saved allocations do not conserve bill totals')
    return dict(ledger_sha256=digest, bills=len(bills), max_bill_error=float(error.max()),
                checked_bill_days=int(seen.size), outside_bill_days=0, duplicate_bill_days=0, missing_bill_days=0,
                minimum_daily_bill_mean_ratio=minimum_ratio if np.isfinite(minimum_ratio) else None,
                null_customer_days=pq.read_table(folder / 'target_customer_daily.parquet',
                    columns=['estimated_consumption']).column(0).null_count,
                wall_seconds=manifest['wall_seconds'],
                fallback_reason=manifest['model_diagnostics']['fallback_reason'])


def plot_profiles(path, series, title, columns=3):
    """Dependency-free PNG line charts; missing values leave gaps."""
    panel_w = 640
    font = ImageFont.load_default(size=16)
    small = ImageFont.load_default(size=13)
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    legend_columns = (1 if any(measure.textlength(c[0], font=small) > 250
                              for _, curves in series for c in curves) else 2)
    legend_rows = max((len(curves) + legend_columns - 1) // legend_columns for _, curves in series)
    panel_h = 280 + max(0, legend_rows - 1) * 20
    rows = (len(series) + columns - 1) // columns
    image = Image.new('RGB', (columns * panel_w, rows * panel_h + 65), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((18, 12), title, fill='black', font=font)
    colors = ['#245cb3', '#d15b20', '#338866', '#963db3']
    for index, (label, curves) in enumerate(series):
        x0 = (index % columns) * panel_w + 80
        y0 = (index // columns) * panel_h + 112
        width, height = panel_w - 110, 155
        dates = pd.DatetimeIndex(sorted(set().union(*(set(c[1]) for c in curves))))
        first, last = dates.min(), dates.max()
        span = max((last - first).days, 1)
        finite = np.concatenate([np.asarray(c[2], dtype=float) for c in curves])
        ymax = max(float(np.nanmax(finite)) if np.isfinite(finite).any() else 0, 1)
        draw.text((x0, y0 - 40), label + ' (m3/day)', fill='black', font=font)
        for tick in range(4):
            yy = y0 + height * (1 - tick / 3)
            draw.line((x0, yy, x0 + width, yy), fill='#dddddd')
            draw.text((x0 - 72, yy - 6), f'{ymax * tick / 3:.1f}', fill='#444444', font=small)
        draw.line((x0, y0, x0, y0 + height, x0 + width, y0 + height), fill='black')
        for k, (name, curve_dates, values) in enumerate(curves):
            color = '#555555' if name == 'Uniform bill allocation' else colors[k % len(colors)]
            draw.text((x0 + (k % legend_columns) * 260,
                       y0 + height + 35 + (k // legend_columns) * 20), name, fill=color, font=small)
            previous = None
            for day, value in zip(pd.to_datetime(curve_dates), values):
                if not np.isfinite(value):
                    previous = None
                    continue
                point = (x0 + (day - first).days / span * width, y0 + height * (1 - value / ymax))
                if previous is not None:
                    draw.line((previous, point), fill=color, width=2)
                previous = point
        draw.text((x0, y0 + height + 9), first.strftime('%Y-%m-%d'), fill='black', font=small)
        draw.text((x0 + width - 90, y0 + height + 9), last.strftime('%Y-%m-%d'), fill='black', font=small)
    image.save(path)


def worker(snapshot, output, settings_path):
    # This process imports only the selected branch's scientific implementation.
    sys.path.insert(0, str(snapshot))
    from dataclasses import replace
    from run_pipeline import CONFIG
    from isd.pipeline import run
    import isd.solver as solver

    settings = json.loads(settings_path.read_text(encoding='utf-8'))
    cfg = replace(CONFIG, **settings['parameters'])
    cfg.validate()
    write_json(output / 'resolved_config.json', cfg.as_dict())
    # Instrument the existing sweep without modifying the branch's calculations.
    sweep_name = 'reference_sweep' if cfg.engine == 'reference' else 'scaled_sweep'
    original = getattr(solver, sweep_name)
    completed = 0

    def progress(*args, **kwargs):
        nonlocal completed
        result = original(*args, **kwargs)
        completed += 1
        model, cycle = divmod(completed - 1, cfg.n_disagg_cycles)
        print(f'LR model {model + 1}/{cfg.n_lr_models} | disagg sweep {cycle + 1}/{cfg.n_disagg_cycles} '
              f'done | total {completed}/{cfg.n_lr_models * cfg.n_disagg_cycles}', flush=True)
        return result

    setattr(solver, sweep_name, progress)
    manifest = run(snapshot, cfg, output, bills_path=Path(settings['bills_path']),
                   weather_path=Path(settings['weather_path']))
    if manifest['model_diagnostics'].get('fallback_reason'):
        raise RuntimeError(f"Model fell back: {manifest['model_diagnostics']}")
    if len(manifest.get('cycles', [])) != cfg.n_lr_models * cfg.n_disagg_cycles:
        raise RuntimeError('Requested cycles did not complete')


def snapshot_branch(branch, destination, coverage_policy=None):
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', branch + '^{commit}'], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', '--format=zip', commit, 'isd', 'configs', 'run_pipeline.py',
                                       'README.md', 'requirements.txt', 'tests', 'scripts', 'handoff'], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        source.extractall(destination)
    if coverage_policy == 'observed_support_isd_v1':
        # Apply the same reviewed support-policy change to both scientific branches.
        # Keep the patch and its hash alongside the immutable base commit.
        config_source = (destination / 'isd/config.py').read_text(encoding='utf-8')
        if 'observed_support_isd_v1' not in config_source:
            patch = ROOT / 'patches/observed_support_isd.patch'
            subprocess.run(['git', 'apply', '--directory', destination.relative_to(ROOT).as_posix(), str(patch)],
                           cwd=ROOT, check=True)
            shutil.copy2(patch, destination / 'source_patch.diff')
        if 'observed_support_isd_v1' not in (destination / 'isd/pipeline.py').read_text(encoding='utf-8'):
            raise ValueError('Branch does not implement the requested coverage policy')
    roster = ROOT / 'data/prepared/Customers_Town_Q.csv'
    if roster.exists():
        (destination / 'data/prepared').mkdir(parents=True)
        shutil.copy2(roster, destination / 'data/prepared' / roster.name)
    return commit


def snapshot_working_tree(branch, destination):
    """Freeze current source, including uncommitted files, with content hashes."""
    current = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if branch != current:
        raise ValueError(f'working_tree source requires current branch {branch}; current branch is {current}')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    paths = subprocess.check_output([
        'git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--',
        'isd', 'configs', 'run_pipeline.py', 'README.md', 'requirements.txt', 'tests', 'scripts', 'handoff',
    ], cwd=ROOT).decode('utf-8').split('\0')
    hashes = {}
    for relative in sorted(set(filter(None, paths))):
        source = ROOT / relative
        if not source.is_file():  # A locally deleted tracked file stays deleted.
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        target.write_bytes(content)
        hashes[relative] = hashlib.sha256(content).hexdigest()
    roster = ROOT / 'data/prepared/Customers_Town_Q.csv'
    if roster.exists():
        target = destination / 'data/prepared' / roster.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(roster, target)
    write_json(destination / 'working_tree_snapshot.json', dict(
        source='working_tree', branch=branch, base_commit=commit, files=hashes))
    return commit


def export_model_reports(folder, model, settings, selected):
    name = model['name']
    manifest = json.loads((folder / 'run_manifest.json').read_text(encoding='utf-8'))
    cfg = manifest['configuration']
    daily = pq.read_table(folder / 'target_customer_daily.parquet',
                          filters=[('SubscriptionNumber', 'in', selected)]).to_pandas()
    daily['date_gregorian'] = pd.to_datetime(daily.date_gregorian)
    daily = daily.sort_values(['SubscriptionNumber', 'date_gregorian'])
    if daily.duplicated(['SubscriptionNumber', 'date_gregorian']).any():
        raise ValueError('Duplicate customer days')
    expected_days = len(pd.date_range(cfg['target_start'], cfg['target_end_exclusive'], inclusive='left'))
    if not daily.groupby('SubscriptionNumber').size().reindex(selected).eq(expected_days).all():
        raise ValueError('Incomplete selected customer grid')
    daily = add_uniform_allocations(daily, pd.read_parquet(folder / 'normalized_bills.parquet'))
    daily.to_csv(folder / 'customer_daily_estimates.csv', index=False)
    curves = [(ident, [(name, part.date_gregorian, part.estimated_consumption.to_numpy()),
                       ('Uniform bill allocation', part.date_gregorian, part.uniform_consumption_m3.to_numpy())])
              for ident in selected for part in [daily[daily.SubscriptionNumber == ident]]]
    plot_profiles(folder / 'customer_profiles.png', curves, name + ': daily consumption profiles')
    comparison = pd.read_csv(folder / 'simulation_daily_comparison.csv', parse_dates=['date_gregorian'])
    scales = settings.get('truth_scales', [1.0, 0.75])
    scores, masks = metric_reports(comparison, settings['metric_windows'], settings['excluded_metric_dates'], scales)
    update_tbs_summary(folder, comparison, settings['excluded_metric_dates'], scales)
    for scale in scales:
        comparison[f'truth_tbs_x{scale:g}_m3'] = scale * comparison.tbs_daily_m3
    for window, mask in masks.items():
        comparison['metric_include_' + window] = mask
    comparison.to_csv(folder / 'metric_daily_pairs.csv', index=False)
    role = 'TBS is a model input; in-sample' if 'fourier' in cfg['feature_preset'] else 'TBS used for evaluation only'
    for row in scores:
        row.update(model=name, branch=model['branch'], commit=model['commit'], tbs_role=role,
                   wall_seconds=manifest['wall_seconds'], **json.loads((folder / 'job.json').read_text())['parameters'])
    pd.DataFrame(scores).to_csv(folder / 'metrics.csv', index=False)
    write_json(folder / 'metrics.json', scores)
    print(pd.DataFrame(scores)[['model', 'window', 'truth_scale', 'matched_days', 'mape_percent',
                                'rmse_m3', 'r2', 'pearson_r']].to_string(index=False), flush=True)
    return daily, comparison, scores


def run_experiments(config_path):
    settings = json.loads(config_path.read_text(encoding='utf-8-sig'))
    models = expand_model_grid(settings)
    print(f'Experiment plan: {len(models)} model runs across {len(settings["models"])} model entries', flush=True)
    batch = ROOT / settings['output_directory'] / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    write_json(batch / 'experiment_config.json', settings)
    write_json(batch / 'experiment_plan.json', models)
    shutil.copy2(Path(__file__), batch / 'runner.py')
    seed = settings['random_seed'] if settings['random_seed'] is not None else random.SystemRandom().randrange(2**63)
    selected, metrics, provenance, profiles, aggregates = None, [], [], {}, []
    working_snapshot = None
    for model in models:
        source = model.get('source', 'branch')
        if source not in ('branch', 'working_tree'):
            raise ValueError(f'Unknown model source: {source}')
        if source == 'working_tree':
            if working_snapshot is None:
                working_snapshot = batch / 'working_source'
                working_snapshot.mkdir()
                working_branch = model['branch']
                working_commit = snapshot_working_tree(working_branch, working_snapshot)
            elif model['branch'] != working_branch:
                raise ValueError('All working_tree models must use the current branch')
    for run_index, model in enumerate(models, start=1):
        name = model['name']
        if not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Model name must be a folder name')
        folder = batch / name
        snapshot = folder / 'source'
        snapshot.mkdir(parents=True)
        parameters = {**settings['shared_parameters'], **model['parameters'],
                      'tbs_path': str((ROOT / settings['tbs_path']).resolve())}
        if model.get('source', 'branch') == 'working_tree':
            shutil.copytree(working_snapshot, snapshot, dirs_exist_ok=True)
            commit = working_commit
        else:
            commit = snapshot_branch(model['branch'], snapshot, parameters.get('coverage_policy'))
        if parameters.get('resume'):
            raise ValueError('Each experiment starts fresh; resume must be false')
        job = dict(parameters=parameters, bills_path=str((ROOT / settings['bills_path']).resolve()),
                   weather_path=str((ROOT / settings['weather_path']).resolve()))
        write_json(folder / 'job.json', job)
        print(f'Run {run_index}/{len(models)}: {name} at {commit[:12]} | '
              f'LR={parameters.get("n_lr_models", "branch default")}, '
              f'cycles={parameters.get("n_disagg_cycles", "branch default")}, '
              f'alpha={parameters.get("alpha", "branch default")} -> {folder}', flush=True)
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(snapshot),
                   str(folder), str(folder / 'job.json')]
        with (folder / 'terminal.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            if process.wait():
                raise RuntimeError(f'Experiment failed; see {folder / "terminal.log"}')
        manifest = json.loads((folder / 'run_manifest.json').read_text(encoding='utf-8'))
        cfg = manifest['configuration']
        source = folder / 'target_customer_daily.parquet'
        available = pq.read_table(source, columns=['SubscriptionNumber']).column(0).unique().to_pylist()
        if selected is None:
            selected = select_customers(available, settings['customers'], settings['random_customer_count'], seed)
            write_json(batch / 'customer_selection.json', dict(seed=seed, fixed=settings['customers'],
                       random=selected[len(settings['customers']):], selected=selected))
        elif set(selected) - set(available):
            raise ValueError('Customer population differs between models')
        daily, comparison, scores = export_model_reports(folder, dict(model, commit=commit), settings, selected)
        profiles[name] = daily
        metrics.extend(scores)
        # Independently check all saved bill allocations, not just selected customers.
        audit = validate_allocations(folder)
        if audit['fallback_reason']:
            raise ValueError('Unexpected model fallback')
        patch_path = snapshot / 'source_patch.diff'
        provenance.append(dict(model=name, branch=model['branch'], commit=commit, validation=audit,
                               source=model.get('source', 'branch'),
                               working_tree_snapshot_sha256=hashlib.sha256(
                                   (snapshot / 'working_tree_snapshot.json').read_bytes()).hexdigest()
                               if (snapshot / 'working_tree_snapshot.json').exists() else None,
                               source_patch_sha256=hashlib.sha256(patch_path.read_bytes()).hexdigest()
                               if patch_path.exists() else None))
        aggregates.append((name, comparison.date_gregorian, comparison.final_algorithm_consumption_m3.to_numpy()))
        pd.DataFrame(metrics).to_csv(batch / 'metrics.csv', index=False)
        write_json(batch / 'validation.json', provenance)
    if len({p['validation']['ledger_sha256'] for p in provenance}) != 1:
        raise ValueError('Models used different effective bill ledgers')
    finish_reports(batch, settings, selected, profiles, aggregates, comparison, metrics, provenance)
    print(f'Completed experiment reports: {batch}', flush=True)


def finish_reports(batch, settings, selected, profiles, aggregates, comparison, metrics, provenance):
    joined = []
    charts = []
    for ident in selected:
        curves = []
        for name, daily in profiles.items():
            part = daily[daily.SubscriptionNumber == ident]
            curves.append((name, part.date_gregorian, part.estimated_consumption.to_numpy()))
            joined.append(part.assign(model=name))
        uniform = next(iter(profiles.values()))
        uniform = uniform[uniform.SubscriptionNumber == ident]
        for daily in profiles.values():
            other = daily[daily.SubscriptionNumber == ident]
            if not np.allclose(uniform.uniform_consumption_m3, other.uniform_consumption_m3, equal_nan=True):
                raise ValueError('Uniform customer allocations differ between models')
        curves.append(('Uniform bill allocation', uniform.date_gregorian, uniform.uniform_consumption_m3.to_numpy()))
        charts.append((ident, curves))
    pd.concat(joined, ignore_index=True).to_csv(batch / 'customer_daily_estimates.csv', index=False)
    plot_profiles(batch / 'customer_profiles_comparison.png', charts, 'Customer daily profiles: comparison across models')
    truth_curves = [(f'{scale:g} x TBS', comparison.date_gregorian, scale * comparison.tbs_daily_m3.to_numpy())
                    for scale in settings.get('truth_scales', [1.0, 0.75])]
    plot_profiles(batch / 'aggregate_tbs_comparison.png', [('Aggregate vs TBS', [*aggregates, *truth_curves])],
                  'Aggregate daily consumption over the full simulation', columns=1)
    pd.DataFrame(metrics).to_csv(batch / 'metrics.csv', index=False)
    write_report(batch, metrics, provenance, selected)
    write_json(batch / 'completion.json', dict(status='complete', selected_customers=len(selected), models=list(profiles)))


def regenerate_reports(batch):
    """Reuse saved estimates and customer selection; do not fit models again."""
    settings = json.loads((batch / 'experiment_config.json').read_text(encoding='utf-8'))
    settings.setdefault('truth_scales', [1.0, 0.75])
    provenance = json.loads((batch / 'validation.json').read_text(encoding='utf-8'))
    selected = json.loads((batch / 'customer_selection.json').read_text(encoding='utf-8'))['selected']
    if len({p['validation']['ledger_sha256'] for p in provenance}) != 1:
        raise ValueError('Models used different effective bill ledgers')
    metrics, profiles, aggregates = [], {}, []
    for model in provenance:
        daily, comparison, scores = export_model_reports(batch / model['model'],
            dict(name=model['model'], branch=model['branch'], commit=model['commit']), settings, selected)
        profiles[model['model']] = daily
        metrics.extend(scores)
        aggregates.append((model['model'], comparison.date_gregorian, comparison.final_algorithm_consumption_m3.to_numpy()))
    finish_reports(batch, settings, selected, profiles, aggregates, comparison, metrics, provenance)
    write_json(batch / 'experiment_config.json', settings)
    shutil.copy2(Path(__file__), batch / 'runner.py')
    print(f'Regenerated reports: {batch}', flush=True)


def write_report(batch, metrics, provenance, selected):
    lines = ['# Hyperparameter experiment', '',
             'TBS is the measured reference. Date windows include both endpoints. April 29–30, 2025 are excluded from scores only.',
             'Scores compare unchanged predictions against both TBS and 0.75 x TBS. Only the truth values are scaled.',
             'MAPE is a percentage and omits measured zeros. RMSE is in m3/day. R2 is undefined for constant or insufficient measurements.',
             'Pearson r measures correlation and is undefined if either series is constant or fewer than two pairs are available. Positive truth scaling leaves Pearson r unchanged.',
             'Uniform customer allocations use each accepted effective bill total divided by its bill days; they appear in grey and in the uniform_consumption_m3 CSV column.',
             'Only finite measured/predicted pairs are scored; missing pairs are counted in metrics.csv. Missing customer values stay blank and leave gaps in plots.',
             'Fourier TBS scores are in-sample because TBS is an input. Customer profiles are estimated; no customer daily truth is available.', '',
             '| Model | Window | Truth | Days | MAPE (%) | RMSE (m3/day) | R2 | Pearson r |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for row in metrics:
        values = [('undefined' if row[k] is None else f'{row[k]:.6f}') for k in ['mape_percent', 'rmse_m3', 'r2', 'pearson_r']]
        lines.append(f'| {row["model"]} | {row["window"]} | {row["truth_reference"]} | {row["matched_days"]} | ' + ' | '.join(values) + ' |')
    lines += ['', '## Validation', '']
    for item in provenance:
        a = item['validation']
        ratio = a['minimum_daily_bill_mean_ratio']
        floor_text = 'undefined (all zero bills)' if ratio is None else f'{ratio:.6g}'
        lines.append(f'- {item["model"]}: commit {item["commit"]}; {a["bills"]} bills; '
                     f'max bill discrepancy {a["max_bill_error"]:.3g} m3; '
                     f'minimum daily/bill-mean ratio {floor_text}; '
                     f'{a["null_customer_days"]} missing customer-days retained.')
        if 'checked_bill_days' in a:
            lines.append(f'  Checked {a["checked_bill_days"]} bill-days against original and effective bill periods: '
                         f'{a["outside_bill_days"]} outside, {a["duplicate_bill_days"]} duplicate, '
                         f'{a["missing_bill_days"]} missing.')
        if item.get('source_patch_sha256'):
            lines.append(f'  Support-policy source patch SHA256: {item["source_patch_sha256"]}.')
        if item.get('working_tree_snapshot_sha256'):
            lines.append(f'  Working-checkout snapshot (includes uncommitted changes), manifest SHA256: '
                         f'{item["working_tree_snapshot_sha256"]}. Base commit above is provenance only.')
    lines += ['', f'Selected {len(selected)} customers; selection and seed are in customer_selection.json.', '',
              '![Customer profiles](customer_profiles_comparison.png)', '',
              '![Aggregate vs TBS](aggregate_tbs_comparison.png)', '']
    (batch / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/hyperparameter_experiments.json')
    parser.add_argument('--worker', nargs=3, type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--dry-run', action='store_true', help='Print expanded parameter combinations without running models')
    parser.add_argument('--reports-only', type=Path, metavar='BATCH_DIRECTORY',
                        help='Regenerate reports from saved estimates without rerunning simulations')
    args = parser.parse_args()
    if args.worker:
        worker(*args.worker)
    elif args.reports_only:
        regenerate_reports(args.reports_only.resolve())
    elif args.dry_run:
        settings = json.loads(args.config.read_text(encoding='utf-8-sig'))
        models = expand_model_grid(settings)
        for index, model in enumerate(models, start=1):
            values = {key: model['parameters'][key] for key in GRID_PARAMETERS if key in model['parameters']}
            print(f'{index}/{len(models)}: {model["name"]} [{model["branch"]}] {json.dumps(values)}')
    else:
        run_experiments(args.config.resolve())


if __name__ == '__main__':
    main()
