# export_outputs readability review

Completed the approved readability edit in isd/pipeline.py. Expanded compressed
statements, reconciliation schema and output dictionaries; clarified local
names for allocations, writers, coverage, target slices and baseline differences;
added a return/side-effect docstring and stage comments. No helpers extracted.

Preserved public and nested function arguments, return order, numerical
expressions and accumulation order, output filenames, schema fields/types/order,
method and status labels, null handling, internal_target_gap reasons, and errors.
Other functions were not changed.

Validation: complete module AST matched pipeline_before.py after reversing local
renames and removing the added docstring. git diff --check passed. No pipeline,
solver, tests or output generation were run; runtime results remain unverified
in this step. renames.json records the main mappings; day_ordinal and domain_index
also reverse to the original comprehension name i.

Existing limitations retained:
- Customer export relies on upstream canonical ordering.
- Any nonfinite domain weather weight disables the weighted baseline for all bills.
- Writers are closed on successful completion; exceptions can leave partial outputs.
- partial_target_coverage also labels accepted fallback bills with no target coverage.

Learning checkpoint: bill totals reconcile over complete intervals; target rows
are slices of those allocations, with unavailable customer days kept null. Daily
customer sums are checked against the combined aggregate. Baseline differences
measure shape changes, not accuracy against independent daily observations.

Next: review run(), the remaining orchestration, provenance and completion logic.
