# Peak review and individual mode

Completed peak.py readability edits and the requested peak-mode feature.
Config.peak_mode accepts population (default) or individual. The IDE entry point
exposes this setting and README documents both policies and output schemas.

Population mode retains its existing two-column CSV, fixed full-coverage
selection population, compensated sums and earliest-date tie policy.
Individual mode streams target rows, selects each customer's largest available
value, and writes peakDate in Gregorian YYYY-MM-DD format beside the value.
Partial customers use available days; all-missing customers retain blank values
and dates plus their missing reason. Zeros are numeric. Individual mode does not
require a full-coverage cohort. Its report and manifest do not claim a shared
peak date or simultaneous total; stale population daily totals are removed.

Individual export validates customer/date membership, duplicate days, complete
target row presence (including null rows), finite nonnegative estimates, and
CSV identity/value/date round trips. Per-customer day-presence bitmasks avoid
retaining all customer-day rows in memory. The earliest missing day's reason is
used when a customer has no available estimates.

Validation: 7 focused pytest cases passed (27 unrelated cases deselected),
covering default population output, ties, different customer dates, float64
precision, partial/no coverage, zeros, missing gap reasons, duplicate and absent
rows, invalid values and invalid mode. Individual summary generation was tested.
The first test run caught a renamed lambda parameter mismatch; it was corrected.
Static comparison confirms the three original population functions have identical
ASTs after reversing local renames and removing the new mode dispatch/docstring.
git diff --check passed. No full pipeline or solver execution was performed.

Existing limitations remain: population daily counts rely on upstream uniqueness;
population summary prose includes fixed historical statements. Config hashing
includes peak_mode through as_dict, so old checkpoints or changes of peak_mode
can require a fresh solver run under the existing checkpoint compatibility rule.

Files changed: isd/peak.py, isd/config.py, run_pipeline.py, README.md,
tests/test_peak_review.py. Baseline peak source is saved beside this note.
