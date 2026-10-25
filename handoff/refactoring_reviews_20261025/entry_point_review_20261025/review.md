# Entry-point readability review

Completed the approved run_pipeline.py edit: separate imports, expanded IDE
configuration and argument parsing, main() documentation, and an explicit
comment about JSON configuration precedence.

Preserved defaults, public names, CLI options, configuration construction,
output-directory precedence, and pipeline invocation. JSON supplies a fresh
Config; omitted fields use Config defaults rather than the IDE CONFIG values.

Validation: full module AST matched the saved baseline after normalizing split
imports and the added function docstring. git diff --check passed. No pipeline,
solver, experiments or tests were run. Runtime behavior was not independently
revalidated in this readability-only step.

The historical data_reference.py remains unchanged; it is used for comparison
tests and does not implement the newer internal-target-gap rejection policy.
