# Population readability review

Completed the approved population() edit in isd/pipeline.py: descriptive local
names for target boundaries, coverage, and customer selection; expanded
diagnostics; and documentation of its three outputs and record retention.

Sampling still uses the same eligible pool, seed, customer limit, and hash_sample
call. All selected customers' records remain in canonical order. Coverage
classification, diagnostic keys, formulas, and public arguments are unchanged.
Internal target gaps are rejected upstream by auditing, not by this function.

Validation: the complete module AST matched the saved pipeline_before.py after
reversing this function's local renames and removing its added docstring.
git diff --check passed. No pipeline, solver, or tests were executed; runtime
outputs were not independently revalidated.

Next: review allocate_model(), including population membership, exposure,
fit-day masking, solver invocation, and availability fallback.
