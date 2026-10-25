# Modeled population daily peak



Target: 2025-01-20 through 2025-03-20, inclusive; Asia/Tehran civil days.

Selected date: **2025-03-07**. Units: **source_units_unknown per day**, preserving original bill totals without conversion.

Input: 3 distinct customers, 4 bills. Selected output: 3 customers; accepted/fully reconciled bills: 4.

Fixed peak-selection population: 1 fully covered customers. Source coverage: {'full': 1, 'partial': 1, 'none': 1}. This is a modeled population peak, not a full-city peak.

Peak total: 5.04117177699567. Exported population sum: 5.04117177699567.



## Highest five daily totals



- 2025-03-07: 5.04117177699567

- 2025-02-14: 5.041068846713864

- 2025-02-25: 5.040192189197269

- 2025-03-18: 5.0398587533318695

- 2025-03-17: 5.038868696846755



Missing output values: 2; reasons: {'no_target_bill': 2}. Customer-level reasons are in peak_missing_reasons.csv. Available: 1; retained zeros: 0.

Fixed full-target valid-billing population; exact ties choose earliest date. All output customers use that same date.

Shortest round-trip float64 decimal (Python repr); no fixed decimal rounding. Compensated float64 totals select the peak before export.



## Verification and review

Full-bill reconciliation passed: 4; maximum absolute discrepancy: 0.0. Full/target identities passed: True. CSV identity, unique row, finite nonnegative value and round-trip reconciliation checks passed: True.

Review F1: narrowly classified availability fallback; operational/checkpoint/configuration errors propagate. F2: advancing bill cursor replaces retained customer DataFrames. F3: reject blank/whitespace and multiline physical CSV records before normalization. See handoff/peak_review_resolutions.md and verification artifacts.

Optional O1–O3 are deferred: the current target remains 1403, metadata remains provisional and RSS measurement is available locally.

No measured daily accuracy is claimed. Existing cohort ISD, exposure adaptation, uniform full-bill fallback and missing-value policies remain unchanged. Physical units, billing semantics, weather representativeness and customer daily accuracy remain unconfirmed. No hourly conversion, external data or city scaling was applied.



## Runtime and reproducibility

Wall seconds: 0.745978; peak process RSS bytes: 170,942,464.

Stage times: {'import_audit_seconds': 0.03899440006352961, 'population_seconds': 0.0026925000129267573, 'weather_seconds': 0.04883860005065799, 'model_seconds': 0.37440690002404153, 'export_seconds': 0.026327700004912913, 'peak_export_seconds': 0.028623800026252866}

Run from the IDE with run_pipeline.py; defaults select all available input customers. production=False retains the provisional semantic gates.

Configuration and hashes (SHA256):

```json

{
  "configuration": {
    "mode": "provisional_cohort_isd",
    "engine": "scaled",
    "alpha": 0.05,
    "n_lr_models": 2,
    "n_disagg_cycles": 2,
    "target_start": "2025-01-20",
    "target_end_exclusive": "2025-03-21",
    "timezone": "Asia/Tehran",
    "feature_preset": "winter_hdd65_v1",
    "endpoint_convention": "inclusive",
    "endpoint_confirmed": false,
    "calendar_origin_confirmed": false,
    "day_basis_confirmed": false,
    "target_year_confirmed": false,
    "target_jalali_year_candidate": 1403,
    "physical_zero_confirmed": false,
    "export_unmodified_confirmed": false,
    "consumption_unit": "source_units_unknown",
    "provider_variable_definition": "instant",
    "weather_adapter": "point_linear_integral_v1",
    "ordering_version": "customer_start_end_bill_id_v1",
    "coverage_policy": "balanced_cohort_uniform_elsewhere_v1",
    "zero_residual_policy": "keep_current",
    "residual_tolerance_policy": "64eps_length_max_scale_v1",
    "reconciliation_atol": 1e-08,
    "reconciliation_rtol": 1e-10,
    "regression_rcond": null,
    "exposure_scaled": true,
    "production": false,
    "max_customers": null,
    "sample_scope": "universe",
    "sample_seed": "isd_pilot_v1:",
    "row_group_size": 17,
    "ingestion_chunk_size": 100000,
    "memmap_threshold_mb": 256,
    "checkpoint": false,
    "resume": false
  },
  "inputs": {
    "bill_1403.csv": "86f2ee228254e643ec572744a172875c36ea5f04bb8cdce979856e12be9e93e0",
    "open-meteo-fixture.csv": "1aafbf59432ba67fdc80969d5dc34d87f27656e08810d66bb4d2d27102d61f0b"
  },
  "source": {
    "source_sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "files": {}
  },
  "dependencies": {
    "numpy": "2.3.5",
    "pandas": "3.0.1",
    "pyarrow": "25.0.1",
    "numba": "0.68.0",
    "llvmlite": "0.50.0",
    "jdatetime": "6.1.0",
    "jalali-core": "1.0.0",
    "tzdata": "2026.5",
    "psutil": "7.2.2"
  }
}

```
