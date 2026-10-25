# Audit review — 2026-10-18

Approved: readability changes to audit_normalized and a new policy making internal billing gaps intersecting the target invalidate the customer history.

Implemented: descriptive names, expanded statements/ledger; optional keyword cfg (default Config) supplies target dates; read_bills passes its actual cfg. Existing rejected records remain; otherwise accepted history is quarantined. Internal gap-only quarantine uses internal_target_gap in normalized records and target exports. Ledger adds internal_target_gap_customers. Existing conflicts retain precedence. Edge-only missing coverage remains partial; outside-target gaps remain allowed. README updated.

Verification: 22 data/weather cases passed initially; one setup error was caused by a missing temporary parent directory. After creating it, the remaining ingestion test and three existing export/pipeline checks passed. New gap-specific null-export test passed. git diff --check passed. No full suite or real-data pipeline run.

Existing output and sample CSV are historical and have not been regenerated under the new rule. Preloaded audit tables must be prepared using the same target configuration as their run.
