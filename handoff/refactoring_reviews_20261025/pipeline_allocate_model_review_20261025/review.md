# allocate_model readability review

Completed the approved edit: expanded statements, calls and diagnostic mappings;
clarified local names for target dates, fit mask, customer coverage, singular
values and bill lookup; documented all seven return values and stage intent.

Preserved public parameters, return order, cohort selection, exposure formulas,
fit-day rules, design and solver arguments, rank calculations, checkpoint paths,
exception handling, and diagnostic keys. Other functions were not edited.

Validation: full module AST comparison passed after reversing local renames and
removing the added docstring. git diff --check passed. No pipeline imports,
tests, solver runs or output generation were performed. Runtime behavior was
not independently revalidated. Baseline and rename mapping are saved here;
the bill-ID comprehension uses bill_id, mapping back to the original b.

Existing limitation retained: allocated_model_interval_days counts the prepared
interval length even when an AvailabilityError prevents a model result.
Fallback remains limited to cohort availability failures outside resume mode;
uniform allocation itself occurs during export.

Next review: export_outputs(), including bill reconciliation, target rows,
unavailable reasons, aggregate identities, and baseline comparisons.
