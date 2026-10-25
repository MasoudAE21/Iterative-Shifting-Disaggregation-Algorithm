# Synthetic experiments readability review

Completed the approved edit in isd/experiments.py: expanded compressed statements,
calls, scenario/method lists and metric dictionary; clarified local variables;
documented synthetic truth, shared random state, custom design and peak metrics.

Preserved public signature and seed, scenario/method order, random calls and their
order, numerical expressions, solver configuration, output columns and row order.
No unrelated modules were edited.

Validation: full module AST matched experiments_before.py after reversing local
names recorded in renames.json and removing the added docstring. git diff --check
passed. No experiments, solver runs, pipeline or tests were executed. Numerical
results were not independently revalidated in this readability-only step.

Learning checkpoint: daily synthetic truth is aggregated into bills, reconstructed
by three methods, then compared at customer and population levels. Peak value
error is measured on the true population peak day; timing error is signed.
Zero-only customers remain in absolute error metrics but are excluded from WAPE
division. Pipeline peak_mode does not control these experimental metrics.

The custom two-column intercept/weather design is passed directly to solve;
the configured paper feature preset does not build the design here. A shared
random generator means changing earlier scenarios can change later draws.
