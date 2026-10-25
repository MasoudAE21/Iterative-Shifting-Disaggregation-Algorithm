# Weather features review — 2026-10-24

Approved edit limited to weather_features(): descriptive local names, expanded calculations and return dictionary, docstring specifying daily mean input units.

Verification: whole-module AST matches the saved pre-edit source after removing the added docstring and reversing six local renames. Formula constants, arithmetic order, output keys and interface unchanged. No application imports, tests or pipeline execution. Original source retained as weather_before.py.

Next: explain build_design(), including fit-mask scaling and exposure multiplication, before proposing edits.
