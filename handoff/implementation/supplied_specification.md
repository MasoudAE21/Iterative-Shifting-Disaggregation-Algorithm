Final Iterative Shifting Disaggregation specification

Audit reconciled specification for laptop Codex with target year provisional

Version 2.0 | 7 October 2026 | Recipient: laptop Codex | Supersedes version 1.0

1 Purpose and authority

Implement a small, auditable reference ISD engine first, then an equivalent scalable engine. Preserve Quinn et al., Sensors 2025, 25, 895, DOI 10.3390/s25030895, Section 3, Equations 9-23 and Algorithm 1. The requested deliverable is daily consumption estimates by customer, with retained bill-level allocations and exact bill reconciliation. The supplied data_audit_bundle.zip was inspected, including the audit report, JSON schema, audit script and samples. Counts below are reported by the local audit and were checked for internal consistency; the complete raw customer/weather CSVs and laptop repository were not available here. The audit is evidence of structure and coverage, not validation of consumption semantics or daily accuracy.

The provisional target is 2025-01-20 through 2025-03-20 inclusive, represented internally as [2025-01-20, 2025-03-21). This is 60 days. The audit used these hard-coded dates, so its agreement does not confirm the user intended year. Set target_year_confirmed=false and target_jalali_year_candidate=1403. Validate that the intended year is 1403 and that the calendar conversion maps 1403-11-01 to 2025-01-20 and 1403-12-30 to 2025-03-20 before production. Estimate on complete bill intervals before extracting target days.

Terminology in this document:

PAPER CORE: equations and loop semantics supported by Section 3 and Algorithm 1.

IMPLEMENTATION POLICY: explicit handling of cases the paper leaves undefined; required for reproducibility, not claimed as an original ISD result.

ADAPTATION: a change to fitting, feature selection, coverage handling, stopping, or modeling scope. Must have a separate mode/configuration and validation record.

Daily allocations are model estimates. The paper evaluates aggregate profiles; aggregate accuracy does not establish customer-level accuracy. Reconciliation establishes accounting correctness, not daily accuracy. Do not infer hourly profiles, hourly maxima, or confidence intervals from these daily estimates.

1A Audit findings and resolved implementation choices

Source of measured findings is audit_bundle/handoff/data_schema.json, audit_version=1, with matching data_audit.md. The packaged audit script computes union coverage under inclusive endpoints and an end-exclusive sensitivity case. It hard-codes the provisional Gregorian target; it does not confirm target intent. Its bill sample is deliberately selected and pseudonymized, and its weather sample deliberately omits intermediate hours. Do not run either sample as the full production dataset or interpret weather sample gaps as actual missingness.

Full-file coverage under provisional inclusive endpoints is:

Observed support is 82.6836% of potential customer-days. The balanced cohort is 39.6677% of subscriptions. Neither statistic establishes city population completeness or representative customer accuracy. No internal gaps means no holes BETWEEN bills within a customer's observed span; it does not eliminate target boundary undercoverage. The 237 uncovered customers alone guarantee that there are zero target dates with complete coverage of the full 362,660-customer universe. An all-customer complete-case regression is therefore infeasible on this target.

End-exclusive sensitivity yields 9,939 full, 352,477 partial and 244 uncovered customers, with 17,736,019 covered and 4,023,581 uncovered days. There are 58 same-date records that become zero-length under this convention. The audit's alternative union coverage effectively gives those records no support; it is not a validated alternative solver input. Do not discard them without a source decision. If endpoint semantics change, rebuild validity, cohorts, allocation domain and outputs from raw records.

Resolved parsing: full bills are comma-separated UTF-8-BOM CSV, one header, CRLF, strict ISO YYYY-MM-DD dates and 11-digit string IDs. These override screenshot-based MM/DD/YYYY parsing guesses. Weather is UTF-8 CSV with two metadata rows, one blank row and header on line 4. Headers carry Celsius and km/h units. Enforce exact columns/shape, explicit format and finite values; never guess Excel encoding or serial dates for these current files.

Full bill date envelope is January 2 through April 29 inclusive, canonical D=[2025-01-02,2025-04-30), 118 local days. Audited UTC brackets January 1 20:00 through April 29 21:00 cover all full-interval local midnight boundaries. No current weather extension or weather-gap imputation is needed under the point-value adapter. A new source hash/date extent requires recomputation.

The 10,000-row pilot contains 7,181 customers, is exactly the ordered prefix of the full file, and includes every full-file bill for those customers. It is usable for smoke tests, not a representative scientific sample. Its zero-bill rate is 1.63% versus 4.22% in the full file; UnitCount=1 is 60.90% versus 76.22%, and Capacity=6 is 76.17% versus 79.40% (row-weighted comparisons). Customer identifier order meaning remains unknown.

No raw correction is supported by the audit. Do not remove zero bills, cap high consumption, divide by UnitCount, create missing bills or infer capacity limits. All cohort counts are structural candidates until semantic exclusions are explicitly established. Current exploratory output uses source-recorded totals and labels zero values as recorded zeros, not verified physical inactivity.

2 State and exact mathematical update

Let k identify an accepted bill, c(k) its customer, I_k its complete set of daily indices, L_k = |I_k|, and B_k its observed nonnegative Consumption. Let a_k[d] be the retained allocation for bill k, supported only on I_k. Define customer load q_c[d] = sum of a_k[d] over bills belonging to c. Define the observed-support aggregate y[d] = sum_k a_k[d]. For accepted non-overlapping customer bills, there is at most one bill contribution per customer-day.

PAPER CORE initialization (Eq. 9): a_k[d] = B_k/L_k for d in I_k. Equations 10-11 introduce other source series; Eq. 12 sums their daily contributions. The retained a_k arrays are necessary state even though the paper's declared output is the single aggregate y. Returning them is an output extension, not a replacement algorithm.

For each outer iteration r, fit one ordinary least-squares aggregate model (Eq. 18): beta_r = argmin_beta ||y - X beta||_2^2. Compute p_r = X beta_r (Eq. 19). X includes an intercept and is constant across the run. In reference mode all domain days are fit rows. Keep p_r immutable through every inner shifting cycle of this outer iteration.

For one bill update, using the latest aggregate and the current allocation:

old = a_k[I_k].copy()

other = y[I_k] - old                         # Eq. 20

e = maximum(p_r[I_k] - other, 0.0)           # Eq. 21 + clipping in prose

s = sum(e)

z = B_k * e / s                             # Eq. 22, when s > 0

new = (1 - alpha) * old + alpha * z          # Eq. 23

a_k[I_k] = new

y[I_k] = other + new                        # restore interval, Algorithm 1

Eq. 22 writes the numerator as the current interval sum. It equals B_k by the reconciliation invariant. Use immutable B_k in the implementation to avoid cumulative drift. Eq. 23 blends the CURRENT allocation with z, not the original uniform initialization on every visit. With 0 <= alpha <= 1, nonnegative old and z imply nonnegative new, and sum(new) = B_k. No values outside I_k change. The aggregate over a bill interval generally DOES NOT sum to that bill total because it includes other customers. Reconcile a_k, never y restricted to I_k.

Example oracle: B=6, old=[3,3], other=[2,4], fixed p=[7,5], alpha=0.05. Then e=[5,1], z=[5,1], new=[3.1,2.9], and restored y=[5.1,6.9]. Both allocation values remain nonnegative and sum to 6.

The fitted p may be negative and need not reconcile to any bill. Do not silently constrain OLS coefficients, clip p globally, or replace the update with B_k times normalized weather weights. Only the residual e is clipped by the paper.

3 Loop specification and reference pseudocode

PAPER CORE uses nested outer regression iterations, inner complete shifting cycles, and sequential visits to all bills. The paper suggests nLRModels=10, nDisaggCycles=10 and alpha=0.05 for three or more input series (Section 3.3, p. 14). These are initial reference settings, not validated settings for the audited 513,921 bills and 362,660 subscriptions. A series is a customer/source, not a bill row. The paper gives no exact alternative counts for fewer than three sources.

def isd_reference(bills, X, config):

    validate_nonnegative_bills_and_intervals(bills)

    order = canonical_bill_order(bills)

    alloc = initialize_uniform_full_intervals(bills)  # Eq. 9

    y = aggregate_in_order(alloc)                    # Eq. 12

    for r in range(config.n_lr_models):

        beta, diagnostics = svd_lstsq(X, y)          # Eq. 18

        predicted = X @ beta                        # Eq. 19

        predicted.setflags(write=False)

        for j in range(config.n_disagg_cycles):

            for k in order:

                old = alloc[k].copy()

                idx = bills[k].daily_slice

                other = checked_subtraction(y[idx], old)

                if bills[k].consumption == 0:

                    new = zeros_like(old)

                else:

                    e = maximum(predicted[idx] - other, 0)

                    if residual_is_numerically_zero(e, predicted[idx], other):

                        new = old.copy()             # explicit no-op policy

                        log_zero_residual(r, j, k)

                    else:

                        z = bills[k].consumption * stable_normalize(e)

                        new = (1-config.alpha)*old + config.alpha*z

                        new = correct_roundoff_only(new, bills[k].consumption)

                alloc[k] = new

                y[idx] = other + new

            verify_cycle_invariants(alloc, y)

        record_outer_diagnostics(r, beta, y, alloc)

    return retained_allocations_and_final_aggregate(alloc, y)

There are exactly R regression fits and R*C full bill sweeps. Later bills see the aggregate changes made by earlier bills in the same sweep. Predict once per outer iteration; do not refit between bills/cycles. Do not return the last prediction as the final reconciled aggregate. A final diagnostic fit, if requested, must be separately labeled and must not add another shifting iteration.

Resolve source inconsistencies explicitly. Appendix A1 changes y_tilde inside the shifting loop, conflicting with Eq. 19 and Algorithm 1. Follow Section 3/Algorithm 1: mutate allocations and y; retain p unchanged. Appendix A's equal series-length assumption is unnecessary: iterate every accepted bill once regardless of the number of bills per customer. Section 5's independent-per-series regressions and parallelization discussion does not describe the aggregate regression/sequential update in Section 3. Do not implement independent customer regressions or simultaneous stale-aggregate updates as reference ISD.

IMPLEMENTATION POLICY deterministic visit order: ascending (SubscriptionNumber as normalized string, start_day, end_day_exclusive, bill_id), using stable Unicode/code-point ordering, not locale-sensitive collation. For current unique records, bill_id = SHA256(source_file_sha256 + ":" + decimal CSV physical row number), with row 2 the first bill; store all 64 hex characters. This policy is stable across chunk sizes for the same source hash. bill_id must be stable across chunk sizes. The numerical output can depend on visit order; freeze and record it. An alternate ordering is a sensitivity experiment, not an unnoticed optimization.

4 Dates and full interval scope

IMPLEMENTATION POLICY use provisional inclusive FromDate and ToDate for this audited source, retaining endpoint_confirmed=false. Convert once to [FromDate, ToDate+1 day); day_count=(ToDate-FromDate).days+1. This is supported by all 151,261 adjacent pairs and 58 one-day records, but does not prove utility meter-reading conventions. Strictly parse raw dates as %Y-%m-%d and preserve raw text. The source format is operationally Gregorian; calendar_origin_confirmed=false until the supplier confirms it. Do not reinterpret the file as Jalali because its filename contains 1403.

SubscriptionNumber is an 11-digit identifier string in the real source. Check this format there; permit CUSTOMER_001-style sample IDs only in an explicit sample/test adapter. Preserve leading zeros. Do not numeric-coerce identifiers. Keep inclusive and end-exclusive adapters separate; a convention change requires a new manifest/run and complete recomputation, not a one-day label shift.

Normalize Gregorian/Jalali dates once during ingestion using a pinned, tested conversion implementation. Gregorian dates are the computational axis; retain Jalali display dates and original calendar metadata. Do not treat Gregorian 2025 dates as Jalali because a filename contains 1403. Calendar dates are not UTC midnight instants. Store billing days as date32/day ordinals; weather instants are timezone-aware UTC timestamps converted to the chosen billing-day timezone.

For reproducibility, use D=[2025-01-02,2025-04-30) for this audited release. Preserve all 513,921 full bills in full-interval allocation outputs, including bills that do not intersect the target. In an adapted ISD run, only bills of its frozen cohort enter its shared aggregate. Construct D as the full envelope of the bills selected for a modeling run, including bills needed to cover the chosen fit window. All selected bills are allocated completely on D. Obtain weather throughout D and the required boundary interpolation hours. The audited weather DOES cover this full D, including all necessary boundary brackets. The earlier missing-weather risk is resolved for this source hash. Future bills that begin before January or end after April require a fresh weather audit. Do not truncate such bills or renormalize their entire consumption inside the target. Fetch missing weather, isolate those bills into an explicit unavailable/fallback path, or stop that run.

After allocation, extract dates in the target only. Retain full-interval a_k and full-interval reconciliation reports. A bill crossing a target boundary contributes only its estimated target portion. Customers with no valid coverage on a target day have a missing estimate, not a fabricated zero. Output all requested customer-days with a status, even when the value is null. This makes the limitations of estimating every customer explicit.

5 Weather definitions and units

The actual CSV audit identifies latitude 34.411247, longitude 50.490566, elevation 1435 m, GMT with utc_offset_seconds=0, temperature_2m and apparent_temperature in Celsius, and wind_speed_10m in km/h. Use CSV metadata rather than the earlier incorrectly transcribed latitude 34.41247. It does not establish all customer locations or that this one grid location represents them. Preserve download metadata, provider/model, coordinate, elevation, timestamp convention and units. Open-Meteo documentation confirms selectable temperature/wind units and timezone controls [W1].

IMPLEMENTATION POLICY daily aggregation: set weather_adapter=point_linear_integral_v1 and use local civil days in Asia/Tehran for the provisional run; day_basis_confirmed=false and provider_variable_definition=instant and export_unmodified_confirmed=false. No utility gas-day cutoff or export-specific processing was established by the audit. Open-Meteo Historical Weather API documentation, Hourly Parameter Definition, identifies temperature_2m, apparent_temperature and wind_speed_10m as instantaneous values [W1]. This supports the point-value adapter for an unmodified provider export. It does not identify the exact endpoint/model/retrieval run or prove the CSV was not transformed after download. Read source GMT instants as UTC, then convert; never merely relabel them. Tehran's half-hour offset means UTC-hourly points do not coincide with local midnight. Define the reference weather adapter by piecewise-linear interpolation of the hourly instantaneous temperature and wind series to local day boundaries, then integrate with the trapezoid rule over [local midnight, next midnight) and divide by day duration. Require bounding samples and no timestamp gap exceeding one hour. Do not extrapolate or silently average 23/25 observations. If metadata identifies interval-average rather than instantaneous values, require the period orientation (preceding/following hour) and use interval overlap weights instead. Do not guess this orientation. Record the changed adapter and rerun allocations. Weather aggregation is a specified adapter, not prescribed by the paper.

Set t_F = 1.8*t_C + 32 and w_mph = w_kmh/1.609344. Eq. 15: HDD_b = max(b-t_F,0); Eq. 17: CDD_b = max(t_F-b,0), for b=65 or 55 degrees F. Eq. 16:

HDDW_b = HDD_b * (152 + w_mph)/160   if w_mph <= 8

HDDW_b = HDD_b * (72  + w_mph)/80    if w_mph > 8

The paper states Fahrenheit temperatures but does not specify wind units beside Eq. 16. The New Mexico Gas Company Revised 2024 Integrated Resource Plan, filed 7 May 2025, Appendix C, printed page C-5 (PDF page 69), reproduces the identical Marquette Energy Analytics formula and explicitly specifies mph and degrees F [W2]. This establishes the convention for this formula; it does not independently recover the paper's proprietary weather preprocessing. Use mph, with this provenance recorded. The multiplier is 0.95 at zero wind, 1 at 8 mph, and 1.1 at 16 mph. Threshold 8 mph equals 12.874752 km/h.

Feature transformation occurs AFTER daily temperature/wind aggregation in this specification, consistent with Eqs. 13-17 taking daily inputs. Mean(hourly HDD) and HDD(mean temperature) can differ; an hourly-transform adapter is a separately labeled sensitivity adaptation. Apparent temperature is not HDDW and does not enter the reference design.

Reference feature preset: X columns [intercept, HDD65, HDD55, HDDW65, CDD65], as the explicit Section 3.2 example. Preserve this full design and report its rank. It is NOT an exact reproduction of the paper's case-study feature list: Section 4.1 calls its variables eight but lists trend, four weather variables and four Fourier variables, totaling nine predictors; Section 5/Table 3 describes intercept plus eight predictors and omits HDDW. Do not claim to reproduce an unambiguous experimental design.

ADAPTATION frozen default preset for the provisional cohort run is [intercept, HDD65], named winter_hdd65_v1. Daily feature values/rank are not in this audit and must be computed locally. HDDW65 is retained for the reference preset and separately registered sensitivity runs, not automatically enabled for the default run. Consider HDDW65 in a future validated preset only if independently supported by rank and external validation. Freeze the selected columns before the first regression. Add HDD55 only with enough observations spanning both sides of 55 F and a full-rank design. CDD65 is often all-zero in winter, and HDD65-HDD55 is exactly 10 when all temperatures are below 55 F. Fourier seasonality and trend are unsupported by a two-month window unless longer history provides evidence. If studied, define trend as elapsed days from a fixed origin and harmonics as sin/cos(2*pi*h*elapsed_days/365.2425), h=1,2; this phase/period choice is an adaptation. Do not select features by increasing correlation with ISD's own fitted output.

6 Data contracts and Python interfaces

Use Arrow/Parquet tables for persisted results and float64 NumPy arrays for mathematical state. These are proposed interfaces; the local agent may adapt repository naming while preserving semantics.

audit_bills(raw, parse_config) -> AuditResult

normalize_bills(raw, decisions) -> BillsTable

prepare_daily_weather(hourly, full_domain, weather_config) -> DailyWeather

build_design(daily_weather, feature_config, fit_mask) -> DesignMatrix

isd_reference(bills, design, config) -> ISDResult

isd_scaled(bills, design, config, storage) -> ISDResult

export_target(result, customer_universe, target_start, target_end_exclusive)

BillsTable required fields: bill_id:string; SubscriptionNumber:string; source_file:string; source_row:int64; raw_FromDate/raw_ToDate:string; source_calendar:string; endpoint_convention:string; start_day:date32; end_day_exclusive:date32; day_count:int32; Consumption:float64; consumption_unit:string (default source_units_unknown); ConsumptionType:string; UnitCount:nullable float64; Capacity:nullable float64; model_group_id:string; record_status:string; exclusion_reason:nullable string. Preserve source metadata unchanged. The audit establishes code 40 is constant and UnitCount/Capacity are integers with no within-customer changes, but their meanings remain unconfirmed. Do not divide consumption by UnitCount or enforce Capacity as a daily limit without audited semantics. Missing Consumption is invalid, distinct from zero. Consumption units must be established, not assumed to be standard cubic metres.

DailyWeather required fields: date_gregorian:date32; weather_location_id:string; temperature_mean_C:float64; wind_mean_kmh:float64; temperature_mean_F:float64; wind_mean_mph:float64; coverage_seconds:float64; weather_status:string; adapter_version:string. Optional apparent_temperature_mean_C is retained separately. DesignMatrix includes dates, X:float64[N_D,p], ordered feature_names, immutable fit_mask:bool[N_D], scaling metadata and weather provenance.

ISDConfig: mode in {paper_reference, provisional_cohort_isd}; n_lr_models=10; n_disagg_cycles=10; alpha=0.05; feature_preset; ordering_version; zero_residual_policy='keep_current'; reconciliation_atol; reconciliation_rtol; residual_tolerance_policy; regression_rcond; coverage_policy; checkpoint_policy. Validate integer loop counts >=1 and alpha in [0,1]. alpha=0 is permitted as an identity diagnostic.

FullBillDaily output: run_id, model_group_id, bill_id, SubscriptionNumber, date_gregorian, estimated_consumption:float64, method, status. TargetCustomerDaily output: run_id, SubscriptionNumber, Gregorian date, Jalali date string, estimated_consumption:nullable float64, bill_id:nullable string, model_group_id:nullable string, method, status. Use separate fields: coverage_class in {full, partial, none}; method in {paper_reference_isd, cohort_exposure_isd, uniform_full_interval, none}; estimate_status in {estimated, recorded_zero, unavailable}; reason in {none, partial_target_coverage, no_target_bill, fit_unavailable, rejected_conflict, weather_unavailable}. Include target_year_confirmed=false and provisional_semantics=true as run-level metadata. A covered zero bill uses recorded_zero, with its method and unknown physical-zero interpretation retained. Conflicts must be resolved before summing customer-day allocations. Do not turn missing days into zeros during aggregation.

AggregateDaily output: run/group/date, allocation_sum, predicted_profile_last_outer, n_customers_covered, n_bills_covered, n_zero_customers, coverage_fraction, fit_eligible, weather_status, extrapolation_flag. Name observed-support totals explicitly; they are not city totals on incomplete-coverage days. BillReconciliation: bill total, full daily sum, signed/absolute discrepancy, target daily sum, outside_target_sum, method and passed. Record full_sum = target_sum + outside_target_sum. Empty target overlap has target_sum=0 even though the customer estimate is null on unsupported target days. RunManifest: input hashes, configs, audit decisions, customer universe, code/dependency versions, date domain, feature ordering, rank diagnostics, iteration metrics, timings and warnings. ISDResult retains allocation storage, final y, last p, manifest and diagnostics; never returns only y.

7 Zero cases and numerical correctness

IMPLEMENTATION POLICY the 21,705 recorded zero consumption bills have an exactly zero allocation and remain zero in provisional source-total runs. Keep them in structural coverage accounting: a recorded zero is supported by a record. The audit does not establish physical zero usage. Set physical_zero_confirmed=false; if the supplier later identifies zero as a missing-read sentinel, quarantine affected records/customers and rebuild eligibility instead of fabricating usage. They need no normalization. Reject negative consumption as a correction/credit requiring audit rather than modeling it as physical demand. Reject nonfinite numbers, reversed dates and zero-length canonical intervals.

If a positive bill's clipped residual has zero or numerically negligible sum, Eq. 22 is undefined. Keep its CURRENT allocation unchanged, restore the aggregate, and increment an auditable no-op counter. Do not replace the denominator by epsilon, which breaks reconciliation; do not reset to uniform after previous shifts. All-zero aggregate groups return exactly zero without a regression; record this fast path.

Float64 defaults: reconciliation_atol=1e-8 consumption units and reconciliation_rtol=1e-10, per bill threshold atol+rtol*abs(B). Confirm these against the audited unit scale. For residual sum use tol_s = 64*machine_epsilon*L_k*max(1, max(abs(p[I_k])), max(abs(other))). A sum s <= tol_s is a numerical zero. This guard is unit/scale dependent and must be recorded. Use stable summation and normalize e via its maximum first to prevent overflow. Detect nonfinite intermediates and stop rather than exporting corrupt values.

Tiny negative other values from subtraction may be clipped only when abs(value) <= 64*epsilon*max(1,abs(y[d]),abs(old[d])). Larger negatives indicate aggregate/state inconsistency and fail. For new, correct only roundoff-scale reconciliation differences: add the difference B-sum(new) to the largest allocated day (earliest date on ties); check that the correction remains nonnegative and within the declared reconciliation threshold. Larger corrections fail. No cent/integer rounding in the mathematical state. Any display rounding is separate and must not become the persisted computation.

Recompute the aggregate from retained allocations with compensated summation in canonical order at each complete cycle boundary. First compare it with incrementally updated y using the bound below, fail if exceeded, then replace y with the recomputed aggregate to limit drift. Both reference and scaled engines must use this exact boundary policy. Initialization uses the same compensated aggregation and roundoff-only bill corrections. Aggregate equality tolerance per day should be summation-aware: gamma_M*sum(abs(contributions)) + M*bill_atol, gamma_M=M*epsilon/(1-M*epsilon), with M the contributing bill count; use compensated summation for audit. Report actual discrepancy as well as the bound so an overly loose bound cannot hide bugs.

OLS uses QR/SVD, never explicit inversion of X.T@X. Reference mode uses an SVD minimum-norm solution even when deficient, with rcond=max(N_fit,p)*epsilon explicitly passed. Record singular values, effective rank, condition number (infinite if deficient), residual norms, column ranges and zero columns on every fit. Coefficient identification can fail while predictions remain defined; report this instead of claiming full rank. Production centers/scales the non-intercept columns of Phi using means and population standard deviations from fit rows F, reuses that transform on every date, THEN multiplies every column including the intercept by g. Never center X_adapt after exposure scaling. Keep the zero-spread/rank checks and retain conversion metadata. This order ensures predictions outside F equal g times the full-cohort weather prediction. Reference mode remains the unscaled paper design. This is a numerically equivalent reparameterization for full-rank OLS, not permission to hide rank loss. Require rank=p, N_fit>=max(30,5*p), finite coefficients/predictions, and scaled condition number <=1e8 for production release. These thresholds are proposed engineering gates, not paper guarantees. Freeze any feature reduction before rerunning; never change X mid-run. No automatic ridge or nonnegative regression.

8 Missing data and conflicting bills

The paper is inconsistent about missing data: Section 2.1 and later Section 3.1 replace missing/unaccounted daily values with zero to align source arrays, whereas early Section 3.1 proposes estimating missing low-frequency bills by a regression on similar intervals/covariates. It provides neither that imputation model nor a complete reconciliation/uncertainty rule. These are different procedures; do not pretend they are interchangeable or that zero represents measured inactivity.

Reference convention: absent support contributes numerical zero to y for array alignment, has a separate missing coverage mask, and creates no observed bill constraint. Do not manufacture a zero bill. This preserves the stated zero-alignment branch of the paper, with its potential coverage bias exposed. An imputation experiment would be an ADAPTATION, with imputed intervals separately tagged and reconciled to imputed totals, never presented as observed consumption.

Production policy: retain missing customer-day values as null, exclude incomplete-population days from aggregate regression under Section 9, and avoid default bill imputation. A verified service closure is a separately documented known-zero state, not a missing bill. Do not forward-fill daily consumption or metadata whose time validity is unknown.

Within a customer, remove exact duplicate physical bills once only when the source duplicate audit confirms they are duplicated records. Preserve a ledger of removed rows. Same dates with different totals, partial overlaps, estimated bills followed by actual adjustments, meter exchanges and rebills cannot be resolved from the seven listed columns alone. Quarantine the affected customer's modeling run until authoritative version/status/meter metadata resolves which observations are additive and which replace earlier bills. Do not add overlapping totals, split them in proportion to time, average totals or select the latest row without evidence. Overlap BETWEEN different customers is expected and essential to ISD.

If legitimate independent meters share a subscription, introduce an audited meter/source key and sum distinct physical sources only after that decision. Do not invent separate meters from conflicting rows. Track record counts and volumes through every exclusion, deduplication and resolution.

9 Mandatory policy for incomplete coverage

The audited full population cannot supply complete target-date fit rows: 237 customers have no bill covering any target date. Dropping them alone is insufficient because 218,564 others have partial coverage. Treating absent support as zero creates a response with changing membership and can fit extraction coverage rather than weather. Constant covered counts also do not guarantee constant customer mix.

Default policy is a composite provisional release with three explicit paths. This supersedes version 1's unspecified attempt to find all-population complete dates. No missing bill totals or uncovered daily values are imputed.

Path A uses the frozen balanced cohort S of subscriptions whose accepted inclusive bill union covers every date in F=[2025-01-20,2025-03-21). Expected structural candidate size is 143,859. Recompute membership from raw source after all explicit quality decisions; do not force this number if a decision changes validity. Preserve every bill of each selected customer on full D, including bills outside F. Missing support outside F contributes numerical zero to the aggregate only; it is not a zero-demand observation.

If S is empty, do not divide by n_S: mark fit_unavailable and use only the accepted-bill fallback/unavailable paths. Fit-eligible dates are exactly F AND complete_weather AND full_S_membership AND no conflict. For the current structural cohort this is 60 days. If any cohort customer is disqualified, remove the entire customer from S before fitting, recompute membership and retain the exclusion reason. Do not change S, F or fit rows during an iterative run. Use rank and N_fit gates from Section 7; if they fail, return a uniform fallback for this entire candidate cohort with fit_unavailable, never an unlabeled substitute regression.

Full intervals extend outside F, where even balanced-cohort customers do not all have observed support. Applying a fixed full-cohort predicted total on these dates can exaggerate residuals for the few covered bills and shift bill volume away from target days. Default Path A therefore uses the following explicit boundary ADAPTATION. Define n_S=|S|, n_cov[d]=number of distinct cohort customers with a valid covering bill on d, including recorded-zero bills, and exposure g[d]=n_cov[d]/n_S. Let Phi[d] be the fixed weather design including intercept; set X_adapt[d,:]=g[d]*Phi[d,:]. Fit y_S on F only using X_adapt[F], then predict p=X_adapt@beta across D once per outer iteration. On F, g=1, so fitting is to the constant-population cohort. Elsewhere p scales to observed cohort exposure. The first column is g rather than a constant on D: this is NOT the paper reference design. g is frozen from record support, not adjusted using fitted allocations.

S = customers_continuously_covered_on_target(accepted_bills, F)

cohort_bills = all_bills_for_customers(accepted_bills, S)

g = distinct_cohort_coverage_count(cohort_bills, D) / len(S)

Phi = fixed_features(daily_weather, ['intercept', 'HDD65'])

X_adapt = g[:, None] * Phi

M = target_mask & weather_complete & complete_cohort_coverage

# Inside every outer iteration, with latest cohort y:

beta = lstsq(X_adapt[M], y[M])

p = X_adapt @ beta                 # fixed during all inner cycles

# Use EXACT Eqs. 20-23 sequential updates on every full cohort bill.

Scientific assumption for exposure scaling: the customers observed outside F have approximately the same average weather-dependent daily load as the complete cohort. The audit does not establish this. UnitCount/Capacity heterogeneity and identifier ordering may violate it. It is a declared approximation for cohort boundary predictions, not measured truth or a citywide estimator. Save g, n_cov, fit rows, prediction and exposure-scaled_design=true. Run a registered comparison against masked-fit unscaled predictions to quantify boundary sensitivity; neither comparison proves accuracy without truth. Fitting on non-target days with incomplete S membership is disabled.

Path B covers all subscriptions outside S with some target bill support. Allocate every accepted bill of these customers uniformly over its complete interval, a_k[d]=B_k/L_k, with roundoff-only reconciliation. On covered target days export numeric values and method=uniform_full_interval, reason=partial_target_coverage. On uncovered target days export null, method=none, reason=no_target_bill. For the current audit this is 218,564 customers, with 9,360,075 numeric target-day values and 3,753,765 null values. This deliberately labeled fallback avoids claiming weather-derived individual profiles unsupported by current coverage. It must never be reported as ISD. A future coverage-adjusted all-customer regression or cohort-shape transfer is a separate research adaptation, disabled in this release.

Path C covers the 237 subscriptions with no target support. Export 60 null target estimates per customer, 14,220 nulls in total. Still retain/reconcile all their accepted observed bills outside the target using uniform full-interval allocation. No service-start/closure dates are inferred from their observed span. A null means absence of an estimable bill constraint, not physical non-consumption.

If Path A fits successfully and source validity remains unchanged, target export has 17,991,615 supported numeric values (including recorded zeros) and 3,767,985 nulls. Path A model failure changes methods to uniform but not structural support counts. Structural cohort counts are not final quality eligibility; report any count changes with record/customer ledgers.

Produce separate aggregates: cohort_isd_sum on F (fixed population), observed_partial_uniform_sum, and combined_observed_support_sum. Sum only supported numeric allocations, and include missing-customer counts. The combined sum mixes methods and changing coverage; it is not citywide demand and must not feed an ISD regression. predicted_profile refers only to the cohort model. Do not scale the cohort to city totals or use cohort p while subtracting all-customer contributions. Full-domain cohort sums outside F also have changing membership and must be labeled observed-support totals.

Additional source bills that close gaps trigger a new audit/cohort/run; never fill gaps by extending neighboring bill allocations. If the intended target year differs, no cohort/coverage count here applies: require the corresponding bills/weather, then rebuild the whole pipeline. Pending semantic decisions may be recorded as assumptions for a provisional exploratory run. Verified production claims require resolution and daily accuracy evidence.

10 Modeling groups and storage at scale

Default scientific structure is one shared aggregate model per justified population group, not one regression per customer. Separate fitting groups require evidence of different load mechanisms or weather exposure: verified residential/commercial/industrial classes, materially different geography/climate, or independently validated heating responses. Codes must first be decoded. UnitCount/Capacity alone do not justify separate regressions. Every group must pass coverage, rank, temporal variation and external-validation requirements; very small groups or synchronized intervals can be weakly identifiable. Group selection using consumption outcomes must be evaluated without leakage. Log grouping rules and compare with a pooled model on the same data.

Storage partitions by customer hash, file chunk, month or a fixed number of records are not modeling groups. Batching must preserve one global y and the canonical visit order. Persist ragged float64 allocation arrays with offsets and bill day slices; retain dates by slice rather than repeating them in memory. Memory cost is proportional to H=sum L_k, not customers times target days; account separately for K bills and N_D days. From the audited duration histogram, all-bill H=25,771,767, so float64 allocation values alone need 206,174,136 bytes (196.623 MiB). The subset H for the balanced cohort is NOT reported and must be calculated locally. The previous 400,000-by-45 example is retired. All-file R=C=10 implies 2,577,176,700 bill-day visits if every bill were shifted; default policy shifts only cohort bills. Store uniform fallback bills compactly as total/length/slice rather than dense arrays until streamed export.

Shifting work is O(R*C*H); aggregate regressions use N_fit daily rows, not K separate models. Profile the audit's actual H and bill lengths before choosing storage or compilation. NumPy plus compiled sequential bill loops can preserve semantics. Parallelize ingestion/weather construction/export or proven independent modeling groups. Overlapping updates within one group cannot naively run in parallel. No distributed independent batch models or Jacobi-style stale y updates in the reference-equivalent engine. If checkpointing, save allocations, y, current beta/p, outer/cycle/next-bill position, ordering and hashes; resume without an extra regression or repeated bill update.

11 Verification and acceptance criteria

Build tests that can fail for scientific implementation errors, not only shape checks. Add these audit-specific gates first: source hashes/counts match; inclusive full/partial/none membership matches the audit; all 60 fit days have g=1; zero-only records count toward structural exposure; g is fixed across iterations; outside-target predictions equal g times unscaled prediction; changing coverage never enters fit rows; partial values equal B/L on full intervals; exactly 3,767,985 nulls remain under unchanged validity; the discontinuous weather sample is not accepted as complete weather. Include a synthetic heterogeneous cohort showing that count scaling can remain biased, and report boundary-policy sensitivity rather than asserting it fixes all coverage bias:

Single-update numerical oracle in Section 2; hand-check clipping using p=[1,5] and other=[2,4], B=6, old=[3,3], alpha=0.05, yielding e=[0,1], z=[0,6], new=[2.85,3.15]. Test B=0 and s=0 separately, including s=0 after a previous nonuniform update.

Two overlapping bills and a fixed prediction: verify that the second bill uses the first bill's updated aggregate. Instrument regression-call count, prediction immutability and all R*C*K visit positions. A vectorized stale-aggregate implementation must fail this test.

One-day, 45-day and boundary-crossing intervals; both endpoint conventions; adjacent bills; March leap-year/calendar boundary conversion; Gregorian/Jalali round trips; strict ISO source strings and explicit noncanonical-date rejection; other date encodings are separate adapters. Compare full allocation followed by target filtering with the full result; deliberately show that clipping first changes reconciliation.

Missing support versus measured zero, duplicate/rebill/conflict quarantine, missing consumption, negative credits, identifier precision loss and long bills exceeding weather availability. A changing-population synthetic case must show why raw zero-aligned regression is biased and verify eligibility rejects the biased days.

Weather unit conversion, 8-mph continuity, 0/8/16-mph multipliers, Celsius/Fahrenheit equivalence, half-hour local-day boundaries, duplicate timestamps, missing hour/boundary samples and a temperature day crossing the heating threshold. Check that apparent temperature is not substituted.

Rank fixtures: all-zero CDD, exact HDD65/HDD55 collinearity below 55 F, nearly collinear features, constant-weather intercept-only design, insufficient fit rows and all-zero group. Assert diagnostics and the production rejection/reduced-design pathway.

Known-truth synthetic daily loads for many customers, with heterogeneous baseload/heating slopes, irregular and staggered bills, noise, occupancy changes and known zeros. Aggregate truth to bills, run ISD, score aggregate AND individual estimates separately. Also use a common noiseless weather shape, synchronized bills, weak-weather loads and multiple distinct customer profiles with identical bills. These tests expose information limits; exact customer recovery is not a universal expected result.

Reference/scaled equality, varying storage chunk sizes, shuffled ingestion followed by canonical sorting and checkpoint/resume equivalence. A changed visit-order experiment can legitimately change results and must be reported.

Baselines: full-interval uniform allocation is mandatory; fixed weather-proportional allocation is a comparison only, with explicit baseload/HDD weights and per-bill normalization; aggregate OLS prediction is a non-reconciled diagnostic baseline. Compare advanced GLS/TSR only if their interval/overlap implementation is independently validated. Score all methods on identical days/customers. Include both low-weather and high-weather synthetic conditions; ISD need not beat uniform in every condition.

Accuracy measures with actual daily ground truth: aggregate MAE/RMSE/WAPE, signed bias and peak-day error; per-customer MAE and WAPE where total true consumption is positive, plus error distributions by class and size. WAPE=sum abs(error)/sum true consumption; undefined when its denominator is zero, so use MAE for zero-only populations. Do not average undefined customer percentages or use MAPE on zero days. Report peak-day timing separately. Bill sum error is a correctness metric. Regression R-squared/correlation against y generated by the same algorithm is not external accuracy evidence.

Use smart-meter daily data, accurately matched aggregate meter data or known synthetic truth for validation. Aggregate upstream measurements may include industry, losses, line pack or populations absent from customer bills; align scope before comparing. Withhold daily truth from model selection and use blocked time/customer holdouts. This is retrospective disaggregation using complete bills, potentially extending beyond March 20; do not label it an operational forecast. Splits must reflect the intended retrospective or real-time information set.

For engine equivalence, compare the scaled engine with the scalar oracle under the SAME mode, feature columns, fit mask, exposure vector and numerical boundary policies. Adapted cohort results are not expected to equal the paper reference with a different design or fit domain. In paper_reference mode enforce fit_mask=all D and exposure=1; in provisional_cohort_isd mode enforce the Section 9 cohort, fit mask and exposure rules. Synthetic fixtures exercise both modes.

Production correctness gates: 100% accepted bills reconcile within Section 7 tolerances; no nonfinite or materially negative allocations; customer/aggregate/full-target export identities hold; every requested customer-day has an explicit status; all excluded records and consumption totals reconcile through the audit ledger; fit eligibility/rank/unit/calendar gates pass; prediction immutability and sequential semantics are verified; reference/scaled allocations agree within the same per-value atol+rtol scale on a representative fixture, with aggregate summation bounds checked separately. Runtime/memory budgets are set after the local audit and benchmark, not inferred from the paper's 10,000-series statement.

Scientific release gate: use preregistered evaluation on representative daily ground truth. A proposed gate is no aggregate WAPE degradation against uniform on the primary evaluation set, with customer-level MAE/WAPE and peak errors reported independently. Agree business-specific customer and peak-error limits before release; no customer daily-error threshold is justified by this audit, which supplies no daily consumption truth. If no daily ground truth exists, ship only explicitly provisional model estimates after correctness gates, with sensitivity results; do not claim validated customer daily accuracy. Examine parameter sensitivity (e.g., alpha 0.01/0.05/0.10, loop counts 5/10/20), grouping, feature presets, coverage and visit order. Sensitivity ranges are not calibrated uncertainty intervals.

12 Remaining assumptions and laptop execution contract

Evidence settles file format, measured scale, structural coverage, available weather timestamp support and current absence of structural conflicts. It does not settle the following assumptions. Each is mandatory manifest metadata; the local agent must not report them as confirmed.

Run manifest also records that reference thresholds and alpha/loop counts are engineering defaults, not tuned validated results. ConsumptionType=40 is a measured constant but its label is unknown. No time-varying attributes were observed; future attribute changes need source time-validity rules. Missing readings/service interruptions/extract restrictions are not inferable from the partial boundary coverage.

Use the full CSV as the source of truth. Do not combine the 10,000-row prefix with the full file: that duplicates observations. For a better local correctness/performance pilot, select 10,000 subscriptions by sorting SHA256('isd_pilot_v1:' + SubscriptionNumber) lexicographically and retain ALL their bills; report its full/partial/none and zero-bill distributions. This is a deterministic approximately random customer sample, not proof of population representativeness. Select Path A cohort pilot customers separately using the same hash ordering within S. The ordered-prefix pilot remains a regression fixture only. Do not export real IDs or maps outside the laptop.

Hash-lock the three input CSVs to data_schema.json before applying reported expectations. Full file SHA256 is a40d065cf7bf0168c34443912318ad5f51e07b8af99a77c351191cbbe828f29d; prefix is a2da3a4deb7771a2e5bf8e3801e0e1afe5af739a78cbfb70769edbc12ff654b1; weather is 6c56d838b470e1255332b1ec0e39c48280bbfe27e0c7b0d8df65582cc1894533. If any hash changes, rerun the packaged audit locally and treat old counts as historical. Do not force records to match these expectations.

Implementation order: verify hashes and reproduce the audit locally; implement strict parsers and calendar tests; build/test paper_reference engine; build balanced membership, weather adapter and production adaptation; allocate all noncohort bills uniformly; retain full-bill allocations and reconciliation; benchmark/reference-check the scaled engine; stream the 60-day customer output; run scientific validation/sensitivity; document remaining assumptions. No repository existed in the audit, so create only the required local modules/tests/configs; do not assume an existing Git project, framework or application architecture.

Laptop audit reports Windows 11, Python 3.12.14, 12 logical processors and about 16.78 GB installed RAM. Free memory was about 3.25 GiB at audit time (FreePhysicalMemory in KiB); remeasure before running. Use the recorded bundled interpreter, not the WindowsApps PATH alias. Install/test IANA tzdata for ZoneInfo on Windows. Use compiled sequential bill loops for scaled shifting, no object-per-day state, no dense customer-by-118-day matrix. Stream Parquet output in fixed row groups, default 100,000 rows, ordered by subscription and date; change row-group size without changing mathematical visit order. Default working-memory goal is below 1 GiB for solver arrays/buffers, with peak process memory measured including ingestion; if available RAM is insufficient, use allocation memmaps. This is a budget to test, not a measured benchmark. Do not retain the standard-library audit's full string-row list while allocating solver state.

Compute and report cohort bill count, H_cohort, per-day support, raw-unit total volumes, feature ranges/rank, runtime and peak RAM; these were not provided by the audit. At every outer iteration record fit residual norm, max/relative changes of y on F and allocations, negative predicted-day count, zero-residual no-op count, and reconciliation/aggregate discrepancy. Use R=10, C=10 and alpha=0.05, with no adaptive stopping in the first final-spec run. Checkpoint at completed cycles, saving allocations, y, fixed beta/p, next outer/cycle indices, g, fit mask, input/config hashes and order. Resume must not refit inside a partially completed outer loop.

The default complete target output is intentionally a mixture of cohort ISD, observed-bill uniform fallbacks and missing values. State that distinction prominently in delivery notes and per-row metadata. The specification is final for implementation of a provisional run; year confirmation, utility semantics, exposure assumptions and customer daily accuracy remain unresolved. Implementing it does not resolve those facts.

13 Sources and traceability

[P1] Quinn CO, Brown RH, Corliss GF, Povinelli RJ. An Iterative Shifting Disaggregation Algorithm for Multi-Source, Irregularly Sampled, and Overlapped Time Series. Sensors 2025;25:895. DOI https://doi.org/10.3390/s25030895. Attached PDF read directly; Eq. 16 visually checked on PDF page 10. Main authority: Section 3, Eq. 9-23 and Algorithm 1 on p. 6; missing-data conflict pp. 3, 8; defaults p. 14; experimental feature ambiguity pp. 16, 22; Appendix A contradiction pp. 25-27; scalability statements p. 23 are not an equivalence proof.

[W1] Open-Meteo Historical Weather API documentation. https://open-meteo.com/en/docs/historical-weather-api. Accessed 7 October 2026. Confirms unit/timezone options and lists these three weather variables as instantaneous values. Exact local export provenance remains unconfirmed; full timestamp completeness is supported by the local audit rather than the documentation.

[W2] New Mexico Gas Company. Revised 2024 Integrated Resource Plan, filed 7 May 2025, Case 24-00203-UT. Appendix C, Marquette Energy Analytics methodology, C-5, PDF page 69. https://www.nmgco.com/userfiles/files/50725%20Case%20No.%2024-00203-UT%20-%202025-05-07%20-%20NMGC%20-%20Revised%202024%20Integrated%20Resource%20Plan.pdf. Accessed 7 October 2026. Identical piecewise HDDW formula explicitly uses wind in mph and base temperature in degrees F.

[D1] data_audit_bundle.zip supplied 7 October 2026: handoff/data_audit.md, handoff/data_schema.json, handoff/questions.md, handoff/sample_notes.json, pseudonymized bill sample, deliberately discontinuous weather sample, and scripts/audit_data.py. Counts and source hashes are reported by this local audit, not independently recomputed from full raw CSVs here. Histograms and customer/day counts were cross-checked for internal arithmetic consistency. The final specification supersedes screenshot parsing/scale assumptions from version 1.0; it does not reinterpret the audit as scientific validation.

Table 1

Measured full file finding | Value | Implementation consequence

Bills and distinct subscriptions | 513,921 and 362,660 | Replace the earlier approximate scale; a subscription is not a confirmed physical meter

Bills per subscription | 1: 211,656; 2: 150,750; 3: 251; 4: 3 | Retain customer histories and bill identity

Bill duration under inclusive endpoints | 1 to 117 days; mean 50.1473 | Support arbitrary positive lengths; no 40 or 45 day cap

Sum of all bill lengths H | 25,771,767 bill-days | Derived from duration histogram; allocation values use 206,174,136 bytes

Consumption | Integer values 0 to 85,820; 21,705 zero bills; no negatives | Exact source totals can be int64; solver state remains float64

Structural defects | No missing fields, parse failures, exact duplicates, conflicts, overlaps or internal gaps | Do not apply any correction to current source; keep defensive checks

Adjacent distinct bill pairs | 151,261 pairs, all next start minus prior end = 1 day | Strong evidence for provisional inclusive endpoints

Attributes | All ConsumptionType=40; UnitCount 1 to 112; Capacity 4 to 160; no within-customer changes | Preserve codes; no type label, scaling or grouping inferred

Weather metadata | 34.411247 N, 50.490566 E, 1435 m, GMT and offset 0 | Correct earlier latitude transcription; parse timestamps as UTC

Weather support | 2,880 hourly rows, Jan 1 through Apr 30 2025; no duplicate/missing hours or invalid numeric values | Timestamp support covers full audited bill intervals

Table 2

Coverage class | Customers | Covered target days | Uncovered target days | Default output policy

Full target coverage | 143,859 | 8,631,540 | 0 | Candidate balanced cohort for adapted ISD

Partial target coverage | 218,564 | 9,360,075 | 3,753,765 | Uniform fallback on observed bill support; null elsewhere

No target coverage | 237 | 0 | 14,220 | All 60 target estimates null

Total | 362,660 | 17,991,615 | 3,767,985 | Exactly 21,759,600 requested customer-day rows

Table 3

Assumption or unresolved fact | Provisional executable policy | What establishes it

Intended target year | Candidate 1403; Gregorian dates fixed only for exploratory run; confirmed=false | User confirmation of intended Bahman/Esfand year

Utility endpoint semantics | Inclusive FromDate and ToDate; confirmed=false | Supplier definition of billing/meter-reading interval

Calendar origin and billing day | Operational Gregorian ISO dates; Asia/Tehran civil midnight; confirmed=false | Supplier confirms calendar, timezone and gas-day cutoff

Consumption physical meaning/unit | Preserve recorded totals in source_units_unknown; no m3 label | Supplier confirms units, scaling and corrected/estimated totals

Meaning of zero totals | Retain recorded zeros; physical meaning unconfirmed | Supplier distinguishes zero use from missing/estimated reads

Code 40 and UnitCount/Capacity | Metadata only; no independent modeling groups or limits | Authoritative codebook and units

Population/meter completeness | Universe is the 362,660 observed subscriptions, not a confirmed city census | Extract specification and subscription/meter identity rules

Weather point suitability | One proxy point; representativeness unconfirmed | Customer geography or load/weather validation

Weather export provenance/semantics | UTC established by metadata; provider defines these variables as instantaneous; assume no export transformation | Export endpoint/model/retrieval metadata and confirmation that values were not reaggregated

Exposure scaling outside F | Equal average weather response among covered cohort members | Boundary validation against daily truth or additional bills

Cohort representativeness | Cohort-only conclusions; no city scaling | Compare included/excluded geography, load distributions and response

Features and daily accuracy | Frozen HDD65 preset; rank computed locally; no accuracy claim | Computed features, withheld daily truth and agreed acceptance limits