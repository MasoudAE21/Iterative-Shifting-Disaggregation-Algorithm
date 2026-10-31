"""Rebuild the current input audit, report, and selected-bill coverage plot."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    for script in ('analyze_town_data.py', 'report_town_analysis.py', 'plot_bill_interval_coverage.py'):
        subprocess.run([sys.executable, str(ROOT / 'scripts' / script)], cwd=ROOT, check=True)
    print(f'Analysis saved to {ROOT / "outputs/town_analysis"}')

if __name__ == '__main__':
    main()
