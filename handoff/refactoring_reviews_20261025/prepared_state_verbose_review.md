# Prepared state inspection option

prepare_state now accepts keyword-only verbose=False, sample_path='outputs/prepared_state_sample.json', sample_size=5. Verbose mode writes prepared inputs and keeps the State return interface. No daily allocations are computed. The sample path is relative to the working directory and is replaced on each verbose call. Use distinct paths for before/after comparisons.

The example JSON was generated from tests/fixtures/cohort_equivalence_bills.csv (pseudonymized fixture), normalized and canonically sorted. It is illustrative, not a fresh production result. Sampling follows bill order, not unique-customer selection. Existing pipeline callers remain quiet; enable verbose at the prepare_state call when desired.

hash_sample is unchanged; its proposed readability edit has not been performed in this step.
