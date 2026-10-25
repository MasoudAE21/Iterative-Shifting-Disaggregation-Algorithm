# Peak verifier update

Updated scripts/verify_peak_outputs.py to dispatch on manifest peak_mode,
defaulting to population for older manifests. Existing population verification
is retained. Individual verification independently selects maxima using ordered
(-value, date) pairs, validates customer-day membership/uniqueness/completeness,
and compares CSV values, dates, missing reasons and manifest counts. Individual
reports do not require peak_daily_totals.csv or a shared population peak date.

Fixed two full-source assumptions: reconciled bill count now uses the manifest's
export bill count, and CSV customer identities use selected normalized records
rather than the full input customer count. This supports sampled and quarantined
runs. Expanded existing compressed statements and the report dictionary.

Validation: four focused tests passed. Both main verifier branches were exercised
on tiny generated artifacts with missing customers and a source population larger
than the selection. Deliberately corrupted individual values and dates were
rejected. The test source fingerprint was stubbed; actual source integrity was
not asserted for existing outputs. git diff --check passed. No full pipeline,
solver execution, or verification of real saved outputs was performed.

The verifier retains its fixed outputs/ directory and current-source fingerprint
requirement; historical runs made with earlier source need their matching code.
Existing assert-based checks require normal Python execution (without -O).
Nothing was deleted. Baseline saved as verify_before.py beside this note.
