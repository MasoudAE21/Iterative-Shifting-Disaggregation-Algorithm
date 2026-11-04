"""IDE entry point. Edit CONFIG and OUTPUT_DIRECTORY, then click Run.
Optional CLI: python run_pipeline.py --config configs/smoke.json --output outputs/smoke
"""
import argparse
import json
from dataclasses import replace
from pathlib import Path
from isd.config import Config
from isd.pipeline import run
ROOT = Path(__file__).resolve().parent
# Full available input, provisional daily estimates; semantic production gates remain closed.
CONFIG = Config(
    target_start='2023-12-01',
    target_end_exclusive='2025-05-01',
    target_year_confirmed=True,
    endpoint_confirmed=True,
    day_basis_confirmed=True,
    consumption_unit='m3',
    feature_preset='town_custom_v1',
    weather_adapter='daily_date_labels_v1',
    provider_variable_definition='daily_mean_apparent_temperature_and_max_wind',
    allow_daily_timezone_mismatch=True,
    max_customers=None,
    alpha=0.05,
    n_lr_models=10,
    n_disagg_cycles=10,
    peak_mode='population',
    export_customer_daily_csv=False,  # True writes customer_daily_csv/YYYY-MM.csv.
    bill_boundary_policy='monthly_weighted',
    bill_window='target',
    simulation_start='2023-12-01',
    simulation_end_exclusive='2025-05-01',
    max_bill_days=150,
    bill_duration_scope='boundary',
    bill_date_format='%m/%d/%Y',
    tbs_path='data/prepared/TBS_Town_Q_daily_consumption.csv',
)
# Set peak_mode='individual' to export each customer's own peak value and date.
OUTPUT_DIRECTORY = ROOT / 'outputs' / 'town_full_year'
BILLS_PATH = ROOT / 'data/prepared/bill_Customers_Town_Q_full_year.csv'

def main():
    """Resolve optional CLI overrides and run the configured pipeline."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bills', type=Path, default=BILLS_PATH, help='Bill CSV (defaults to the full-year Town file)')
    parser.add_argument('--weather', type=Path, help='Weather CSV (defaults to the prepared open-meteo-2024-25.csv)')
    parser.add_argument('--bill-policy', choices=['keep', 'exclude', 'prorate', 'clip_preserve_total', 'monthly_weighted'])
    parser.add_argument('--bill-window', choices=['target', 'weather', 'simulation'])
    args = parser.parse_args()

    # Partial JSON overrides the current Town configuration, never legacy defaults.
    config = (
        replace(CONFIG, **json.loads(args.config.read_text(encoding='utf-8')))
        if args.config else CONFIG
    )
    overrides = {}
    if args.bill_policy:
        overrides['bill_boundary_policy'] = args.bill_policy
    if args.bill_window:
        overrides['bill_window'] = args.bill_window
    config = replace(config, **overrides)
    run(ROOT, config, args.output or OUTPUT_DIRECTORY, bills_path=args.bills, weather_path=args.weather)

if __name__ == '__main__':
    main()
