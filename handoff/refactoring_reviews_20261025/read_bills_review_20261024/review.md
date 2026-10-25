# read_bills review — 2026-10-24

Approved scope: naming and layout only in read_bills(). Expanded CSV checks, reader arguments and normalization call; descriptive names for source hash, chunks and physical row counter; one provenance comment.

Verification: whole-module AST equals the saved pre-edit source after reversing the five approved local renames. No application imports, tests or pipeline execution. Existing gap policy and cfg forwarding preserved. Original source retained in data_before.py.

Next: explain coverage_classes() before proposing edits.
