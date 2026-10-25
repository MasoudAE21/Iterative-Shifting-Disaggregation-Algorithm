# Configuration review — 2026-10-18

Approved scope: readability only in isd/config.py.

Completed: class documentation, mode/engine and endpoint explanations, multiline validation, x renamed to count, expanded as_dict. Field order, defaults, validation order, messages and interfaces preserved.

Verification:
- Existing suite started before edit: 60 passed in 77.52s.
- After edit: 60 passed in 6.24s.
- Command: .venv/Scripts/python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp outputs/config_review_20261018/after_tmp
- Normalized AST identical after removing the added class docstring and normalizing the loop variable name.
- Dataclass field order and default dictionary unchanged.
- 36 validation cases matched, including all six JSON presets.
- git diff --check passed.

Original source retained as config_before.py in this directory. No full-data experiment rerun. Historical output manifests retain their original source fingerprints; this source edit changes the current fingerprint.

Deferred behavior question: max_customers=True remains accepted, as before. No validation policy was tightened.

Next: explain data.py normalization, provenance, interval representation and quarantine before proposing any edit.
