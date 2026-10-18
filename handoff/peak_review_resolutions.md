# Independent review resolutions

Review authority: `data/ISD_Independent_Review.docx` (8 October 2026). The requested `docs` path was absent; the supplied review was found in `data`. No AGENTS.md was present in the repository or ancestor directories inspected. The existing supplied/implemented specifications and recorded decisions govern the unchanged numerical algorithm. The user explicitly authorized the full available-input exploratory run; no semantic confirmation flags were changed.

## F1 Operational errors must not become uniform allocations — resolved

`isd/errors.py` defines AvailabilityError. Only explicit weather availability, zero-spread and regression rank/count/condition failures use this classification. `allocate_model` catches only that classification for provisional fresh runs. Configuration, design shape, checkpoint absence, mismatch, corruption and unexpected exceptions propagate. Resume requests also fail on unavailable fitting/weather rather than changing the requested calculation. Config validates registered features and finite nonnegative reconciliation tolerances before output creation. A new validated run invalidates old success markers and customer exports while retaining its checkpoint, preventing a failed retry from presenting stale completed customer outputs.

Verification: pipeline tests exercise missing, incompatible and unreadable checkpoints with deliberately planted stale completion artifacts, and assert that no success manifest/customer export survives. Typo/nonfinite/negative config tests fail before creating output directories. Genuine zero-spread/weather fallback remains explicitly labeled. Existing rank/count/condition tests pass. Both engines resume exactly at a middle cycle, an outer boundary and the final cycle, with forced allocation memmaps; allocations and saved prediction equal uninterrupted runs. The existing real-fixture same-mode engine equality check passes at the unchanged tolerance (atol 1e-8, rtol 1e-10).

## F2 Retained customer DataFrames defeat bounded export memory — resolved

`export_outputs` now advances once through canonical accepted bill tuples while merging with sorted requested customer IDs. Only the current customer's target arrays and fixed writer buffers are expanded. ISD population, bill order, update equations and allocation values are unchanged. Existing compact source tables, customer-ID maps and reconciliation scalars still scale with input size; this is not a constant-memory ingestion claim.

Verification: all values, IDs, dates, methods, statuses, coverage and reconciliation fields in the new 1,000-customer/1,432-bill pilot exactly equal the prior pilot (run UUID excluded), including 71,682 full bill-days and 60,000 target rows. Leading/interior/trailing quarantined customers emit all target dates with null values and rejection reasons. Existing row-group/chunk invariance checks pass. Fresh-process export-only RSS benchmarks with fixed 10,000-row groups measured 22,851,584 incremental bytes at 10,000 generated customers and 33,153,024 at 100,000; complete exports reconciled all bills. No tracemalloc was used. The modest increase includes O(input) cursor/ID/reconciliation storage, rather than hundreds of thousands of retained subframes. See peak_export_equivalence.json and peak_memory_benchmarks.json.

About 6.05 GB RAM was available before full execution; a 4 GB whole-process budget was used for assessment. The first full run peaked at 1,531,179,008 bytes and completed in 215.85 seconds; the final run's measured stages/RSS/runtime are in outputs/run_manifest.json. Full exports cover the actually present source file, not an assumed eventual scale. Available disk and output sizes are independently recorded in peak_final_verification.json. Fresh-process benchmarks, a moderate real pilot and the full run provide staged operational evidence. Failed checkpoint attempts clean completion/customer artifacts; unexpected failures can leave intermediate diagnostics or full-bill partial files, which have no success manifest and are not final peak deliverables.

## F3 Physical CSV line identity — resolved

`read_bills` performs a strict physical-line preflight before pandas ingestion. Blank and whitespace-only lines are explicitly rejected. Single-line CSV shape and strict quoting are checked; multiline records remain unsupported and fail explicitly. Normal single-line files keep the original SHA256(source hash + ':' + physical row) identity.

Verification: blank/space/tab lines fail at chunk sizes 1, 2 and 100,000. BOM, CRLF, quoted commas and ordinary source-row/bill-ID identity are tested for all three sizes. Multiline quoting fails. Full source audit reran without removing, correcting, truncating or imputing any source bill.

## Required peak output and scientific scope — completed provisionally

The IDE default now selects all available customers (configs/peak.json mirrors it); pilot/reference configurations remain available. Complete bills are allocated before target filtering. Peak selection uses the fixed valid full-target coverage population, with compensated float64 daily totals. Exact ties select the earliest date. All distinct input customers are exported on that one date; available fallback estimates and zeros are retained, missing estimates are blank with a separate reason file. CSV float text uses Python's shortest round-trip representation, without fixed-decimal rounding. CSV integrity and population sum are checked on write and independently on readback.

The agreed target remains 2025-01-20 through 2025-03-20 inclusive, candidate Jalali 1403, in Asia/Tehran civil days. Units remain source_units_unknown. This is a modeled balanced-population peak, not a full-city peak or a measured daily maximum. No external data, additional bills, hourly profiles, peaking factors or hourly conversion were introduced.

Review-requested known-truth tests exercise the actual default cohort fit window and changing boundary exposure, plus a partial customer excluded from the model. They report adverse results without requiring ISD superiority: weather-response customer MAE 1.1060138284775445 versus uniform 1.014296553911436; unmodeled daily variation MAE 2.2312121892458867 versus uniform 2.178610596063733. These are synthetic errors in constructed units, not measured local accuracy. Metrics are retained in peak_tests.xml.

The final suite has 60 passing tests. Early attempts hit sandbox temporary-directory permissions; workspace --basetemp resolved that environment issue. A new synthetic test's NumPy integer/date constructor mismatch was corrected before the passing run. No solver tolerance was relaxed. Run tests with `python -m pytest tests -q --basetemp outputs/unique_test_temp -o junit_family=xunit1` (use an unused temp directory).

## Optional review items and remaining limitations

O1 calendar generalization is deferred because the requested 1403 mapping is unchanged and tested. O2 confirmed-unit/alternate-weather metadata generalization is deferred because semantics remain provisional and the original weather point is retained. O3 best-effort telemetry is deferred because RSS measurement succeeds in this environment. None is required to change the present daily estimates.

Target-year intent, utility endpoints/gas-day definitions, physical units/zero interpretation, exact weather provenance and geographic representativeness remain unconfirmed. Complete-coverage customers are not proven representative. Full-bill conservation proves accounting, not customer daily accuracy. Independent customer measurements are unavailable; no validated accuracy or full-city claim is made.

## Reproduction and handoff

Run `run_pipeline.py` from the IDE, or `python run_pipeline.py --config configs/peak.json --output outputs`. Then `python scripts/verify_peak_outputs.py` independently checks serialized full-bill allocations, zeros, CSV identity, same-day extraction and a math.fsum peak. `python scripts/package_peak_review.py` produces the allowlisted ZIP and verifies every inventory SHA256. The ZIP contains source, tests/pseudonymized fixtures, resolution log, summary, aggregate totals, configuration, manifests, verification and a small pseudonymized output sample. Raw bulk data, customer-level full output, real IDs, credentials and environments are excluded. The legacy execute_review script still requires its original local data/handoff inputs; those are intentionally not included in this compact bundle.

## Final executed results

Final fresh run: 218.387142 seconds; peak RSS 1,507,880,960 bytes (below the 4 GB assessment budget). 513,921 bills and 25,771,767 full bill-days were exported and independently reconciled. Target output has 21,759,600 rows: 17,991,615 numeric and 3,767,985 null. CSV has 362,660 distinct string IDs, 315,351 available values, 12,927 valid zeros and 47,309 blanks (no_target_bill). Peak date 2025-02-10; fixed population 143,859; total 2183460.535366701 source units/day. Independent math.fsum readback matches exactly. Final source hashes match the manifest; no numerical solver changes were introduced. See peak_final_verification.json for output hashes and measured disk availability.
