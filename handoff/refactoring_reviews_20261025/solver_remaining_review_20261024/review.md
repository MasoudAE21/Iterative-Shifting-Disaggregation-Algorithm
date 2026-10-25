# Solver remaining review — 2026-10-24

Completed approved readability edits to initialize and correct_roundoff only. Static whole-module AST comparison passed after removing two docstrings and reversing local renames. No application imports, solver runs or tests. git diff --check passed.

Source evaluation completed for sum_compensated, aggregate_kernel, interval_update, reference_sweep, scaled_sweep, conservation_kernel, lstsq_diagnostics, state_lock and solve. Existing tests inspected by source, not rerun.

Core invariants: fixed prediction per outer fit; latest aggregate used for each sequential bill update; full-bill normalization; explicit zero-total and negligible-residual handling; compensated sums, roundoff correction and cycle conservation; aggregate recomputation after every cycle; no convergence-based early stopping.

Potential issues to investigate separately (not repaired): checkpoint input lock is not payload integrity validation; restored arrays/progress are not fully validated before use; initialization can overwrite allocation storage before checkpoint rejection; state lock includes storage settings and excludes engine intentionally, but has no algorithm version; memory copies and checkpoint payloads exceed allocation memmap alone; low-level State validation does not enforce integer array dtypes; zero-column designs are not explicitly rejected; all-zero fast path does not write a checkpoint; stop_after_cycles returns the same Result type without a completion field and may omit current outer diagnostics.

These are static findings or edge-case risks, not claims of failures in the present dataset. Existing normal-path resume/engine-equivalence tests provide historical coverage, not a fresh validation result.

Recommended subsequent edits, each requiring approval: expand regression diagnostics and lock construction; clarify reference interval/sweep variable names; mirror names in compiled kernels while retaining numerical order; reorganize solve into visible stages, considering checkpoint helpers only after behavior is understood. Behavioral hardening needs targeted tests separately. No broad solver rewrite approved.
