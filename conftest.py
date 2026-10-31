"""Use isolated repository-local pytest scratch space on Windows and elsewhere."""
from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    # Respect an explicit --basetemp. A fresh path avoids both inaccessible
    # Windows user-temp directories and reuse/deletion of previous test runs.
    if config.option.basetemp is None:
        parent = Path(__file__).resolve().parent / '.pytest_tmp'
        parent.mkdir(exist_ok=True)
        config.option.basetemp = str(parent / f'run-{uuid4().hex}')
