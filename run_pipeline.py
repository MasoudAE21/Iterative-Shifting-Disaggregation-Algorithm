"""IDE entry point. Edit CONFIG and OUTPUT_DIRECTORY, then click Run.
Optional CLI: python run_pipeline.py --config configs/pilot.json --output outputs/my_run
"""
import argparse
import json
from pathlib import Path
from isd.config import Config
from isd.pipeline import run
ROOT = Path(__file__).resolve().parent
# Full available input, provisional daily estimates; semantic production gates remain closed.
CONFIG = Config(
    max_customers=None,
    alpha=0.05,
    n_lr_models=10,
    n_disagg_cycles=10,
    peak_mode='population',
)
# Set peak_mode='individual' to export each customer's own peak value and date.
OUTPUT_DIRECTORY = ROOT / 'outputs'

def main():
    """Resolve optional CLI overrides and run the configured pipeline."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    # JSON replaces the IDE configuration; omitted fields use Config defaults.
    config = (
        Config(**json.loads(args.config.read_text(encoding='utf-8')))
        if args.config else CONFIG
    )
    run(ROOT, config, args.output or OUTPUT_DIRECTORY)

if __name__ == '__main__':
    main()
