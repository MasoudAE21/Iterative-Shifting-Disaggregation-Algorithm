# Decisions conflicts and consequences

| Issue | Evidence and decision | Consequence |
| --- | --- | --- |
| Appendix A1 changes y_tilde | Contradicts Eq.19 and Algorithm 1; freeze prediction for each outer fit and update a/y | Following Appendix mutation would implement a different method |
| Paper missing values | Section 3.1 describes both unspecified bill imputation and daily zero alignment | Reference uses numerical zero alignment with coverage masks, no invented bills; provisional exports retain nulls |
| Paper experiments feature list | Section 4.1 counts eight but lists nine predictors; Table 3 differs | Reference preserves explicit Section 3.2 five-column example, not a claimed case-study reproduction |
| All-customer fit | Source contains 237 customers without any target support and many partial customers | Full-population complete-case regression infeasible; frozen balanced cohort with labeled uniform fallback |
| Boundary predictions | Complete cohort still has changing coverage outside target | Exposure scaling is an adaptation and requires a separate unscaled-prediction sensitivity |
| Wind units | Paper omits wind units near Eq.16; NMGC matching formula specifies mph | Convert km/h to mph; do not use raw km/h in the formula |
| Endpoint and dates | Adjacent +1-day intervals and source ISO text support provisional inclusion/Gregorian parsing | Confirmation flags remain false; no end-exclusive solver or filename-based Jalali parsing |
| Candidate year | Conversion library verifies 1403-11-01/1403-12-30 map to the supplied 2025 target | Intended year remains unconfirmed; production gate stays closed |
| Zero bill meaning | Source records zero totals without codebook | Preserve exactly zero and label recorded_zero, not verified physical inactivity |
| Units and attributes | ConsumptionType=40, UnitCount and Capacity meanings unavailable | Preserve metadata and source totals; no unit scaling, per-unit normalization, limits or separate models |
| Exact duplicates if future data change | Identical seven fields alone may lack physical bill authority | Default quarantine; audit API exposes deduplication only with explicit confirmation, retaining removed-row ledger |
| Within-customer overlap | Source has none; defensive fixtures do | Quarantine entire customer, never add conflicting totals; cross-customer overlap remains normal |
| Output memory | All-bill ragged state would have 25,771,767 values; fallback requires no shifting | Dense state only for modeled bills, memmap threshold and streamed output; no customer-by-day model matrix |
| Floating sums | Both engines use identical compensated float64 sums and z-then-blend arithmetic order | An initial real-data difference of 0.00038314 failed; align numerical order and rerun under unchanged tolerance, recomputing aggregates every cycle; no fastmath |
| Source changed | Pipeline recomputes audit and records hash mismatch | Historical audit counts are not forced; no silent data corrections |
| Local daily truth | No independent measurements in inputs | Real results report consistency/plausibility/sensitivity only; synthetic scores are labeled separately |

Unresolved: intended year, utility interval/day semantics, consumption units and zero interpretation, code labels, exact weather export provenance, geographic suitability, exposure response comparability and customer daily accuracy. Prototype correctness does not confirm these facts. Main requested pipeline is implemented as a provisional exploratory release; no full production execution.

The registered unscaled-boundary sensitivity uses method=cohort_masked_unscaled_isd, distinct from default cohort_exposure_isd. Normalized bills retain the final shared_population/fallback group assignment and source-row provenance. Numerical pipeline code was rerun after these output-metadata refinements.
