# Cleanup completed

Removed five legacy regional/review/benchmark scripts, five legacy experimental JSON configs, and the hello-world `tests/test.py` placeholder. Kept the functional regression suite, fixtures, solver modules and current Town scripts.

Current configs:
- `configs/peak.json`: full Town run.
- `configs/smoke.json`: small run; overrides the current daily-weather settings from `run_pipeline.py`.

Removed generated analysis and algorithm outputs. Three old test directories could not be deleted because Windows denied access:
- `outputs/tests-window-1fe36824bddb4c8fbd738a9730b5533b`
- `outputs/tests-window-dbb9719f9aed4cfeb86a43291e8a76fd`
- `outputs/town-filter-tests`

They are unrelated to current execution. New test commands use unique temporary directories. Raw/prepared data, source documents, the working environment, and historical handoff evidence were retained. See `VALIDATION_GUIDE.md` for manual execution.
