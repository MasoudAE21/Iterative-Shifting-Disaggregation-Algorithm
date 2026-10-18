# Final pilot review

32 tests pass. Independent checks of the persisted Parquet files confirm full-interval conservation, nonnegativity, all 60 target dates per selected customer, null/zero separation, customer/aggregate export identities, string IDs and source fingerprints. Raw input hashes are unchanged.

The 10,000-customer universe pilot has 14,148 bills and 710,687 allocated bill-days. It contains 3,964 full, 6,028 partial and 8 uncovered customers. Target output has 495,854 numeric estimates and 104,146 nulls out of 600,000 rows. The independent 10,000-cohort-customer pilot has 19,320 bills and 986,415 bill-days; all 600,000 target rows have source bill support. Maximum bill reconciliation discrepancy in both pilots is approximately 1.82e-12 source units.

Default cohort design has rank 2/2 on 60 fit dates; paper-reference smoke design has rank 5/5 on 118 dates. No automatic feature reduction occurred. Last predictions are diagnostic, not replacements for reconciled allocations. Zero-residual no-op counts are substantial and explicitly retained in manifests; the boundary prediction assumption materially changes target shape in the registered unscaled sensitivity. These observations are not external accuracy evidence.

All real-data comparisons are consistency, plausibility or sensitivity. Known-truth synthetic scores do not establish customer accuracy in the supplied data. Defaults are engineering choices. Intended year, units, utility semantics, weather export processing and exposure assumptions remain unconfirmed. Full production was not run.

IDE entry point: D:/work/repo/run_pipeline.py with interpreter D:/work/repo/.venv/Scripts/python.exe. Primary outputs: D:/work/repo/outputs/pilot_10000 and D:/work/repo/outputs/cohort_pilot_10000. Upload ZIP: D:/work/repo/handoff/implementation_review_bundle.zip.