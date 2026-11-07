# Algorithm comparison review — 2026-11-05

Scope: current working tree, including existing local edits and experiment configurations. No algorithm or configuration changes made. Reviewed solver, pipeline, weather features, bill-window preprocessing, configuration, and relevant tests.

Conclusion: the basic ISD update is implemented consistently with the repository's transcription of Section 3. The current Town workflow is an adaptation, not an exact paper reproduction. No missing core loop step was identified. The largest differences arise before and after that loop.

## Evidence and limitation

Reference: Quinn et al., *An Iterative Shifting Disaggregation Algorithm for Multi-Source, Irregularly Sampled, and Overlapped Time Series*, Sensors 2025, 25, 895, https://doi.org/10.3390/s25030895 ; indexed full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC11819941/ . The indexed paper overview and Algorithm 1 description were retrieved. Direct full-text requests were blocked by rate limits/browser checks; an alternate XML host could not resolve. Equation-level and appendix details below therefore use the existing `handoff/implementation/supplied_specification.md`, especially lines 45–139 and 161–175. Those details were not independently reverified against the original PDF during this review.

The documented paper core is uniform initialization, aggregate OLS, a fixed prediction per outer iteration, and sequential removal/residual redistribution/restoration of each interval. The local specification records an Appendix A1 prediction-mutation conflict and chooses Section 3/Algorithm 1. That choice is internally coherent.

## Core implementation mapping

| Operation | Current implementation | Assessment |
| --- | --- | --- |
| Uniform bill initialization | `isd/solver.py:248` | Total divided by interval length, with small reconciliation correction. |
| Aggregate daily allocations | `isd/solver.py:77` | Sequential compensated accumulation. |
| Aggregate OLS and prediction | `isd/solver.py:262` | SVD least squares; prediction formed from the design matrix. |
| Nested regression/cycle/bill loops | `isd/solver.py:391`, `:411`, `:143` | Correct nesting; compiled engine also sequential. |
| Remove current bill | `isd/solver.py:106` | Uses current allocation and current aggregate. |
| Clip residual to nonnegative | `isd/solver.py:115` | Clips residual, not the complete prediction. |
| Normalize and blend | `isd/solver.py:125` | Uses immutable bill total; current allocation is blended, not initial uniform allocation. |
| Restore aggregate | `isd/solver.py:138` | Later bills see earlier updates. |
| Freeze prediction | `isd/solver.py:408` | Read-only array plus cycle-level hash check. |

Roundoff correction, compensated summation, aggregate rebuilding, zero-total fast paths, and near-zero residual no-ops are explicit numerical policies. They are sensible extensions but prevent a claim of literal arithmetic equivalence to unspecified pseudocode edge cases. OLS centering/scaling alone preserves the fitted column space when rank is unchanged; it is not inherently a different regression model.

## Findings and differences

### 1. High priority: Town wind input does not follow the reference feature convention

`isd/town_features.py:39` reads daily maximum wind in km/h and passes it directly to the piecewise multiplier with threshold 8. `isd/weather.py:249` instead evaluates the analogous reference feature with mean wind in mph. The supplied specification records the mph convention and its external provenance; the paper itself reportedly does not state wind units next to the equation.

At 16 km/h, the Town multiplier is 1.1; converting that same speed to mph gives approximately 1.0243. This is not a global rescaling: the breakpoint also changes. Feature standardization cannot generally remove the discrepancy. Maximum versus mean wind is a separate difference. Treat the Town feature as a custom model, or use appropriate mean-wind input and unit conversion for the reference convention.

### 2. High priority: paper-reference labeling does not exclude the extra correction

`isd/config.py:144` requires the Section 3 feature preset in paper-reference mode, but permits nonzero `individual_reference_strength`. `isd/solver.py:132` and `:212` then apply another update after the ISD blend:

`allocation = allocation + strength * (reference_allocation - allocation)`

The pipeline builds that reference from per-bill normalized `1 + HDD65` (`isd/pipeline.py:265`). At strength 1, it replaces the ISD result with the reference allocation on every visit. Nevertheless, `isd/pipeline.py:348` labels the output `paper_reference_isd`. The tests explicitly exercise this permitted combination.

Recommended correction: prohibit nonzero strength in strict reference mode, or give the augmented algorithm a separate mode and method label. The current entry-point default is zero; `configs/experiment_reference_05_10x10.json` uses strength 0.05 and cohort mode. Here “reference” in the filename means the added individual reference, not paper-reference mode. The added adjustment is applied every visit, so its effect depends on cycle counts as well as strength.

### 3. Current preprocessing changes the constraints supplied to ISD

`run_pipeline.py:29` selects `monthly_weighted`. `isd/bill_window.py:83` estimates retained consumption using retained/original calendar-weight sums and clips crossing intervals. Reconciliation then checks effective totals, not original full-bill totals. December's current weight is 0.8. These choices can materially change both initialization and the final estimates even with an unchanged solver.

For a strict full-bill comparison, preserve original totals and full intervals with sufficient weather coverage. The current `max_bill_days=150` applies only to boundary-crossing bills because `bill_duration_scope='boundary'`; it is not a universal duration cap.

### 4. Current population and fit domain are restricted

Default mode is `provisional_cohort_isd` (`isd/config.py:13`). `isd/pipeline.py:211` models only customers fully covering the target. Partial customers receive uniform allocations on accepted support; uncovered days remain missing. A failed rank/count/condition gate also causes cohort-wide uniform fallback. Thus the final exported population series can combine ISD and uniform estimates.

The adaptation fits target dates and optionally scales predictions by coverage exposure. With the present target and simulation both December 2023–April 2025 and modeled customers fully covered, exposure is normally one within that domain; it should not be described as necessarily changing this particular run. Reference mode selects all accepted customers and all domain fit days, but source quarantine still applies.

### 5. Current weather design is custom

`isd/town_features.py:46` enables intercept, HDD65, a trailing three-day HDD65 mean, HDD65 times the wind multiplier, and HDD65 plus the multiplier. Inputs are apparent temperature and maximum wind. The reference preset in `isd/weather.py:276` instead contains intercept, HDD65, HDD55, HDDW65 and CDD65.

Changing only `mode` cannot reproduce the reference with current daily inputs: configuration requires the reference preset, and the weather feature builder rejects that preset for the apparent-temperature/maximum-wind adapter. Appropriate reference weather inputs are needed. The three-day moving average retains raw values for its first two days, another explicit custom boundary convention.

### 6. Missing-data behavior is an explicit local policy

`isd/data.py:145` quarantines a customer's accepted history when an internal gap intersects the target. It does not impute missing bills. Partial boundary coverage follows the uniform/missing-output policy. Weather gaps are not silently filled. These policies narrow the input the algorithm actually handles; they should not be mistaken for a general missing-data reconstruction implementation.

### 7. Run settings and documentation need clearer separation

The IDE defaults use 10 regression fits × 10 cycles, alpha 0.05. `configs/town.json` overrides those counts to 5 × 5. Both are valid configurations but need not produce equal results. `engine='reference'` selects the scalar implementation; `mode='paper_reference'` selects the formulation. They are different settings.

The historical algorithm specification describes full intervals, a simpler cohort feature set, and no target-truncated normalization. Current Town preprocessing and features have moved beyond that description. The top of README also states older month weights/formulas. A single current configuration-specific mathematical description is missing.

## What remains missing for a convincing reproduction

- A strict reference configuration that rejects optional allocation modifications and preserves full source intervals/totals.
- An independently checked paper-derived end-to-end numerical fixture, beyond local scalar/compiled agreement and a hand-calculated interval update.
- Tests of the actual enabled Town wind features and their units. Existing custom-feature tests mostly monkeypatch the feature builder, so they do not detect the current unit discrepancy.
- An independently reproduced Appendix/Section 3 comparison resolving the documented inconsistency against the original PDF.
- Case-study reproduction and independent customer daily accuracy evidence. Existing synthetic experiments and TBS aggregate comparisons serve different purposes; conservation and engine equivalence do not establish daily customer accuracy.

## Verification

Executed:

`.venv/Scripts/python.exe -m pytest tests/test_solver.py tests/test_individual_reference.py tests/test_town_features.py tests/test_daily_weather.py tests/test_bill_window.py -q`

Result: **56 passed in 5.29 seconds**. This covers hand updates, sequential semantics, conservation, zero residuals, rank behavior, scalar/compiled agreement, resume, optional reference adjustment, and related feature/window policies. No full dataset rerun or scientific accuracy validation was performed.

Suggested order: fix or explicitly rename the wind convention; enforce accurate reference-mode labeling; establish a strict full-interval reference configuration; add an independent paper fixture; then compare each adaptation separately on aligned data.
