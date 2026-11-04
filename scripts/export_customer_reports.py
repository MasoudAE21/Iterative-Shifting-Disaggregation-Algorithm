"""Export both peak definitions from a saved run, without fitting again."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isd.customer_reports import export_daily_csv, export_peak_reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/customer_reports.json'))
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding='utf-8'))
    run = Path(settings['run_directory'])
    destination = Path(settings['output_directory'])
    if destination.resolve() == run.resolve():
        raise ValueError('Use a separate report directory to preserve accepted outputs')
    windows = dict(settings['peak_windows'])
    cfg = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))['configuration']
    if settings.get('include_all_simulation', True):
        windows['all_simulation'] = [cfg['simulation_start'], cfg['simulation_end_exclusive']]
    enabled = settings.get('export_customer_daily_csv', False)
    if not isinstance(enabled, bool):
        raise ValueError('export_customer_daily_csv must be boolean')
    report = export_peak_reports(run, destination, windows)
    report['daily_csv'] = export_daily_csv(run / 'target_customer_daily.parquet',
        destination / 'customer_daily_csv', enabled=enabled)
    (destination / 'report_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
