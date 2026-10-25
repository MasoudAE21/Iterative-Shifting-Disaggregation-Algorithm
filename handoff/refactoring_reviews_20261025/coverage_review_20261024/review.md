# Coverage review — 2026-10-24

Approved readability edit limited to coverage_classes: descriptive scan-state and interval names, expanded statements and finish branches, coverage-only clipping comment. Signature, interval union, classification conditions and returned values preserved.

Static verification: whole-module AST matches the saved original after reversing five local renames and mechanically expanding the original nested conditional classification into branches. No application imports, tests or pipeline execution. Original source saved as data_before.py.

Next: explain hash_sample and prepare_state before proposing edits.
