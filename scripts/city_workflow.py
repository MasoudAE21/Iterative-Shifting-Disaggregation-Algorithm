"""Configuration-only city simulation, audit and reusable report commands."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import psutil

from isd.config import Config
from isd.data import read_bills, sha256, date_ordinal, coverage_classes
from isd.bill_window import resolve_window, apply_bill_window
from isd.customer_floor import normalize_consumption, attach_customer_floors
from isd.weather import read_weather, daily_integral
from isd.pipeline import run, write_json, source_fingerprint
from isd.city_reports import export_city_reports, report_windows
from scripts.run_hyperparameter_experiments import validate_allocations


def absolute(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT/path


def load_settings(path):
    settings = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    allowed = {'bills_path', 'weather_path', 'output_directory', 'simulation', 'pilot', 'reports'}
    if set(settings)-allowed:
        raise ValueError(f'Unknown workflow fields: {sorted(set(settings)-allowed)}')
    cfg = Config(**settings['simulation'])
    cfg.validate()
    if cfg.tbs_path is not None or 'fourier' in cfg.feature_preset:
        raise ValueError('City g013 workflow does not use Town_Q TBS; supply city truth under reports.measured_city_daily_csv')
    if cfg.divide_consumption_by_unit_count:
        raise ValueError('Final city customer totals require divide_consumption_by_unit_count=false')
    if cfg.peak_mode != 'individual' or cfg.max_customers is not None:
        raise ValueError('City simulation requires peak_mode=individual and max_customers=null; use pilot for sampling')
    if cfg.resume:
        raise ValueError('Fresh timestamped city runs require resume=false')
    if cfg.target_start != cfg.simulation_start or cfg.target_end_exclusive != cfg.simulation_end_exclusive:
        raise ValueError('Save the entire simulation: target bounds must equal simulation bounds')
    # Dates define the saved grid; reject inconsistent reports before fitting.
    report_windows(settings['reports'], cfg.as_dict())
    for key in ['bills_path', 'weather_path']:
        if not absolute(settings[key]).is_file():
            raise FileNotFoundError(f'{key}: {absolute(settings[key])}')
    return settings, cfg


def preflight(settings, cfg):
    """Use the same normalization, boundary and floor logic as the actual solver."""
    bills = absolute(settings['bills_path']); weather = absolute(settings['weather_path'])
    raw, audit = read_bills(bills, cfg)
    source = normalize_consumption(raw, cfg)
    seconds, values, metadata = read_weather(weather)
    if isinstance(values, pd.DataFrame):
        if cfg.weather_adapter != 'daily_date_labels_v1' or cfg.provider_variable_definition != 'daily_mean_apparent_temperature_and_max_wind':
            raise ValueError('Daily weather adapter configuration mismatch')
        if metadata.get('timezone') != cfg.timezone and not cfg.allow_daily_timezone_mismatch:
            raise ValueError('Weather timezone differs; configure date-label alignment explicitly')
    window_audit = {}
    if cfg.bill_boundary_policy != 'keep':
        source, window_audit = apply_bill_window(source, cfg, *resolve_window(seconds, values, cfg))
    source = attach_customer_floors(source, cfg)
    accepted = source[source.record_status == 'accepted']
    if accepted.empty:
        raise ValueError('No accepted bills after normalization and boundary handling')
    start, end = date_ordinal(cfg.target_start), date_ordinal(cfg.target_end_exclusive)
    domain_start = min(start, int(accepted.start_ordinal.min()))
    domain_end = max(end, int(accepted.end_ordinal.max()))
    aligned = daily_integral(seconds, values, np.arange(domain_start, domain_end), cfg.timezone)
    missing_weather = aligned.loc[aligned.weather_status != 'complete', 'date_gregorian'].astype(str).tolist()
    if missing_weather:
        raise ValueError(f'Weather missing on {len(missing_weather)} required dates; first dates: {missing_weather[:8]}')
    classes = coverage_classes(source, start, end)
    total_customers = len(classes)
    if cfg.max_customers is not None:
        total_customers = min(total_customers, cfg.max_customers)
    days = end-start
    floors = accepted[['SubscriptionNumber', 'floor_source']].drop_duplicates().floor_source.value_counts()
    coverage = {day: int(accepted.loc[(accepted.start_ordinal <= date_ordinal(day)) &
                       (accepted.end_ordinal > date_ordinal(day)), 'SubscriptionNumber'].nunique())
                for day in settings['reports'].get('requested_dates', [])}
    parent = absolute(settings['output_directory'])
    disk_parent = parent
    while not disk_parent.exists():
        disk_parent = disk_parent.parent
    warnings = []
    fallback = int(floors.get('insufficient_summer_fallback', 0))
    if fallback:
        warnings.append(f'{fallback} customers use insufficient-summer-history floors; review the supplied bill history.')
    if cfg.consumption_types is None and len(source.ConsumptionType.dropna().unique()) == 1:
        warnings.append('Only one ConsumptionType is present; input does not establish inclusion of all city types.')
    if any(count < len(classes) for count in coverage.values()):
        warnings.append('Some customers lack requested-date coverage; report values will remain blank.')
    report = {'bills_path': str(bills), 'bills_sha256': sha256(bills), 'weather_path': str(weather),
              'weather_sha256': sha256(weather), 'source_rows': len(source), 'input_customers': len(classes),
              'selected_customer_limit': cfg.max_customers, 'target_days': days,
              'maximum_selected_customer_days': total_customers*days,
              'accepted_bill_days_all_input': int(accepted.day_count.sum()),
              'source_audit': audit, 'bill_window_audit': window_audit,
              'bill_status_counts': source.record_status.value_counts().to_dict(),
              'consumption_type_counts': source.ConsumptionType.value_counts().to_dict(),
              'full_target_customers_all_input': sum(kind == 'full' for kind, _ in classes.values()),
              'floor_source_customer_counts': floors.to_dict(), 'requested_date_covered_customers_all_input': coverage,
              'available_ram_bytes': psutil.virtual_memory().available,
              'free_output_disk_bytes': shutil.disk_usage(disk_parent).free,
              'resource_note': 'Customer-day count is exact for the grid size limit. Runtime, RAM and compressed disk use require the pilot; no linear scaling guarantee.',
              'warnings': warnings}
    return report


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]


def report_settings(settings):
    result = dict(settings['reports'])
    if result.get('measured_city_daily_csv'):
        result['measured_city_daily_csv'] = str(absolute(result['measured_city_daily_csv']))
        if not Path(result['measured_city_daily_csv']).is_file():
            raise FileNotFoundError(result['measured_city_daily_csv'])
    return result


def simulate(settings, cfg, pilot=False):
    cfg = replace(cfg, max_customers=settings.get('pilot', {}).get('max_customers', 1000)) if pilot else cfg
    cfg.validate()
    if pilot and cfg.max_customers is None:
        raise ValueError('Pilot requires a positive max_customers limit')
    reporting = report_settings(settings)
    print('Auditing bill coverage, summer history and weather...', flush=True)
    audit = preflight(settings, cfg)
    base = absolute(settings['output_directory'])
    out = base/('pilot_' if pilot else 'run_')/stamp()
    out.mkdir(parents=True)
    write_json(out/'workflow_settings.json', settings)
    write_json(out/'preflight.json', audit)
    write_json(out/'resolved_config.json', cfg.as_dict())
    # Capture the implementation for provenance without copying inputs or old outputs.
    snapshot = out/'source'
    for path in [ROOT/'run_pipeline.py', *sorted((ROOT/'isd').glob('*.py')), *sorted((ROOT/'scripts').glob('*.py'))]:
        target = snapshot/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    write_json(out/'source_fingerprint.json', source_fingerprint(ROOT))
    for warning in audit['warnings']:
        print('Preflight note:', warning, flush=True)
    print(f'Starting {"pilot" if pilot else "full city"} run: {out}', flush=True)
    import isd.solver as solver
    sweep_name = 'reference_sweep' if cfg.engine == 'reference' else 'scaled_sweep'
    original = getattr(solver, sweep_name)
    completed = 0
    def progress(*args, **kwargs):
        nonlocal completed
        result = original(*args, **kwargs)
        completed += 1
        print(f'Completed sweep {completed}/{cfg.n_lr_models*cfg.n_disagg_cycles}', flush=True)
        return result
    setattr(solver, sweep_name, progress)
    try:
        manifest = run(ROOT, cfg, out, bills_path=absolute(settings['bills_path']), weather_path=absolute(settings['weather_path']))
    finally:
        setattr(solver, sweep_name, original)
    print('Validating saved bill allocations...', flush=True)
    validation = validate_allocations(out)
    if validation['fallback_reason'] is not None:
        raise ValueError(f"Solver fallback: {validation['fallback_reason']}")
    if not manifest.get('all_zero_fast_path') and len(manifest.get('cycles', [])) != cfg.n_lr_models*cfg.n_disagg_cycles:
        raise ValueError('Not all configured model cycles completed')
    if audit['bills_sha256'] != sha256(absolute(settings['bills_path'])) or audit['weather_sha256'] != sha256(absolute(settings['weather_path'])):
        raise ValueError('Input changed during run; do not accept this simulation')
    write_json(out/'validation.json', validation)
    resources = {'wall_seconds': manifest['wall_seconds'], 'peak_rss_bytes': manifest['peak_rss_bytes'],
                 'saved_files_bytes_before_reports': sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),
                 'customers': manifest['peak']['output_customers'],
                 'customer_days': manifest['peak']['output_customers']*audit['target_days']}
    write_json(out/'resource_summary.json', resources)
    # Mark validated simulation complete BEFORE rendering optional reports. A report
    # failure never requires a simulation rerun; use the reports command on this run.
    write_json(out/'simulation_complete.json', {'status': 'validated', 'pilot': pilot, 'resources': resources})
    write_json(base/('latest_pilot.json' if pilot else 'latest_run.json'), {'run_directory': str(out.resolve())})
    if reporting.get('automatic_after_simulation', True):
        if pilot:
            # User-selected city IDs may not be part of the deterministic pilot.
            reporting['profile_customers'] = []
        destination = out/'reports'/stamp()
        export_city_reports(out, destination, reporting)
        print(f'Reports: {destination}', flush=True)
    print(f'Validated simulation: {out}', flush=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preflight', 'pilot', 'run', 'reports'])
    parser.add_argument('--config', type=Path, default=ROOT/'configs/city_final.json')
    parser.add_argument('--run-dir', type=Path, help='Existing completed run for reports; otherwise latest full city run')
    args = parser.parse_args()
    if args.command == 'reports':
        # Reports do not require original bills/weather to remain at their input paths.
        settings = json.loads(args.config.read_text(encoding='utf-8-sig'))
        run_dir = absolute(args.run_dir) if args.run_dir else Path(json.loads((absolute(settings['output_directory'])/'latest_run.json').read_text())['run_directory'])
        # Town_Q experiment completion lives one level above the model directory.
        if not (run_dir/'simulation_complete.json').exists() and not (run_dir.parent/'completion.json').exists():
            raise ValueError('Reports require a completed simulation; pass its model/run directory')
        destination = run_dir/'reports'/stamp()
        export_city_reports(run_dir, destination, report_settings(settings))
        print(f'Reports: {destination}', flush=True)
        return
    settings, cfg = load_settings(args.config)
    if args.command == 'preflight':
        audit = preflight(settings, cfg)
        destination = absolute(settings['output_directory'])/'preflight'/stamp()
        destination.mkdir(parents=True)
        write_json(destination/'preflight.json', audit)
        print(json.dumps(audit, indent=2, default=str))
        print(f'Preflight: {destination}', flush=True)
    else:
        simulate(settings, cfg, pilot=args.command == 'pilot')


if __name__ == '__main__':
    main()
