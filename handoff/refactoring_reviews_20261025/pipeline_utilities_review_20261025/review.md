# Pipeline supporting utilities

Approved scope completed: PeakMemory, clean_json, write_json,
source_fingerprint, RowWriter, schema_for, and canonical.

Expanded compressed statements and schemas, clarified comprehension variables
and fingerprint local names, and documented utility responsibilities.
Corrected PeakMemory's docstring: this class samples RSS; it does not separately
record the Windows peak working set. Sampling behavior remains unchanged.

Preserved public signatures and attributes, JSON options, file selection and
hash construction, Parquet field order/types/compression, buffering behavior,
and stable bill ordering. No main pipeline functions were changed.

Validation: complete module AST comparison passed after stripping docstrings
and reversing the specified local renames. git diff --check passed.
Only static source verification was executed; no imports of pipeline code,
tests, solver runs, or output generation were performed.
The baseline is saved beside this note as pipeline_before.py.

Existing limitations retained: RSS sampling can miss transient peaks;
RowWriter relies on callers to close it; schema_for returns the target schema
for every kind other than bill_daily. These were not behavioral fixes.

Next review: population(), covering full-coverage candidates, sampling scope,
deterministic customer selection, retention of all selected bills, and coverage
diagnostics. Main model allocation and exports remain pending.
