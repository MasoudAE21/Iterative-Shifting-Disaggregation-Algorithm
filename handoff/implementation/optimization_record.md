# Measured optimization record

Full audit: 210.775s before, 3.866s after under cProfile, with identical complete audit statistics and H. Sorted-array traversal replaces repeated per-customer pandas frames; original oracle is retained in isd/data_reference.py and exercised by fixture tests.

Real same-mode engine comparison: 100 customers, 198 bills, 9882 days. Reference profiled time 1.833064s; compiled warm time 0.018339s. Profiling overhead makes these unsuitable for a precise speedup claim. Reference profile identifies interval updates and compensated aggregation as bottlenecks. Allocations and aggregates match exactly. No fastmath, parallel bill sweeps or independent batch models.

The initially rejected implementation differed by up to 0.00038314 because summation/arithmetic order diverged. Both engines now use the same compensated sums and explicit z-then-blend order. Tolerance was not relaxed. The positive zero-residual guard is retained and no-op counts are in all manifests.

A normal cold IDE-entry run took 6.599s for 1000 customers, including full import/audit. Benchmarks with preloaded source tables label that reuse explicitly. Peak RSS is sampled every 20 ms and includes the source table; warm subset RSS also reflects allocator retention. These are laptop measurements, not a guarantee for the full population.

Export was the largest measured stage in the 10,000-customer pilots. It is streamed with fixed Parquet row groups and was not further optimized; solver storage/model order remain independent of output chunk size. Full production execution is deferred.