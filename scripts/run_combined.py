"""Reproducible experiment runner; always uses the confirmed full-year bill source."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_pipeline import CONFIG
from isd.pipeline import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT/'configs/seasonal_reference_combined.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--long', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    cfg = replace(CONFIG, **json.loads(args.config.read_text(encoding='utf-8-sig')))
    if args.long:
        cfg = replace(cfg, n_lr_models=50, n_disagg_cycles=25)
    if args.smoke:
        cfg = replace(cfg, max_customers=100, n_lr_models=2, n_disagg_cycles=2)
    run(ROOT, cfg, args.output, bills_path=ROOT/'data/prepared/bill_Customers_Town_Q_full_year.csv')


if __name__ == '__main__':
    main()
