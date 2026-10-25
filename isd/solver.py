"""Section 3, Eqs. 9, 12, 18-23. One immutable prediction per outer fit.
Reference uses readable NumPy interval updates; scaled uses sequential Numba loops.
No customer batching, parallel sweeps, normal equations, or prediction mutation.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib, json, math, time
import numpy as np
from numba import njit
from .errors import AvailabilityError
from .config import Config
EPS=np.finfo(np.float64).eps

@dataclass
class State:
    """Bill constraints and storage layout, treated as fixed during solving.

    starts indexes the shared daily timeline; offsets bounds each bill's slice
    in the separate flattened allocation array. Allocations are not stored here.
    """

    starts: np.ndarray
    lengths: np.ndarray
    totals: np.ndarray
    offsets: np.ndarray
    n_days: int
    identity_token: str = ""

    def validate(self):
        if not (
            len(self.starts) == len(self.lengths) == len(self.totals)
            == len(self.offsets) - 1
        ):
            raise ValueError('State shape')
        if (
            np.any(self.starts < 0)
            or np.any(self.lengths <= 0)
            or np.any(self.starts + self.lengths > self.n_days)
        ):
            raise ValueError('Interval outside domain')
        if not np.isfinite(self.totals).all() or np.any(self.totals < 0):
            raise ValueError('Invalid total')
        if not np.array_equal(np.diff(self.offsets), self.lengths) or self.offsets[0] != 0:
            raise ValueError('Offsets')
        return self

@dataclass
class Result:
    """Solver allocations, aggregate profile and execution diagnostics.

    y sums the per-bill allocations onto the shared daily timeline. prediction
    is the last regression profile and need not reconcile to bill totals.
    """

    allocations: np.ndarray
    y: np.ndarray
    prediction: np.ndarray
    iterations: list
    cycles: list
    zero_residual_noops: int
    all_zero_fast_path: bool
    wall_seconds: float

@njit(cache=True, fastmath=False)
def sum_compensated(x):
    """Sum values in order while compensating for floating-point rounding."""
    total = 0.0
    correction = 0.0
    for value in x:
        adjusted_value = value - correction
        next_total = total + adjusted_value
        correction = next_total - total - adjusted_value
        total = next_total
    return total

@njit(cache=True, fastmath=False)
def aggregate_kernel(a, starts, lengths, offsets, n):
    """Return daily sums and contribution counts from flattened bill allocations."""
    daily_total = np.zeros(n)
    daily_correction = np.zeros(n)
    daily_count = np.zeros(n, np.int64)
    for bill_index in range(len(starts)):
        for day_offset in range(lengths[bill_index]):
            day_index = starts[bill_index] + day_offset
            value = a[offsets[bill_index] + day_offset]
            adjusted_value = value - daily_correction[day_index]
            next_total = daily_total[day_index] + adjusted_value
            daily_correction[day_index] = next_total - daily_total[day_index] - adjusted_value
            daily_total[day_index] = next_total
            daily_count[day_index] += 1
    return (daily_total, daily_count)

def correct_roundoff(a, total, cfg):
    """Correct a small bill-sum discrepancy in place; return the same array."""
    delta = total - sum_compensated.py_func(a)
    if abs(delta) > cfg.reconciliation_atol + cfg.reconciliation_rtol * abs(total):
        raise ArithmeticError('Correction exceeds reconciliation threshold')
    largest_index = int(np.argmax(a))
    a[largest_index] += delta
    if not np.isfinite(a).all() or np.any(a < 0):
        raise ArithmeticError('Invalid corrected allocation')
    return a

def interval_update(old, y, p, total, cfg):
    """Hand-checkable Eq. 20-23 update, returning new, restored y, no-op flag."""
    other_contributions = y - old
    subtraction_tolerance = 64 * EPS * np.maximum(1, np.maximum(np.abs(y), np.abs(old)))
    if np.any(other_contributions < -subtraction_tolerance):
        raise ArithmeticError('Aggregate minus bill is materially negative')
    other_contributions = np.maximum(other_contributions, 0)
    if total == 0:
        new_allocation = np.zeros_like(old)
        noop = False
    else:
        residual = np.maximum(p - other_contributions, 0)
        if not np.isfinite(residual).all():
            raise ArithmeticError('Nonfinite residual')
        scale = max(1, float(np.max(np.abs(p))), float(np.max(np.abs(other_contributions))))
        residual_sum = sum_compensated.py_func(residual)
        residual_threshold = 64 * EPS * len(residual) * scale
        noop = residual_sum <= residual_threshold
        if noop:
            new_allocation = old.copy()
        else:
            weights = residual / np.max(residual)
            proposed_allocation = total * (weights / sum_compensated.py_func(weights))
            new_allocation = correct_roundoff(
                (1 - cfg.alpha) * old + cfg.alpha * proposed_allocation,
                total,
                cfg,
            )
    return (new_allocation, other_contributions + new_allocation, noop)

def reference_sweep(a, y, p, state, cfg):
    """Update bills sequentially in place; later bills see the latest aggregate."""
    noops = 0
    for bill_index in range(len(state.starts)):
        day_start = int(state.starts[bill_index])
        length = int(state.lengths[bill_index])
        offset = int(state.offsets[bill_index])
        (new_allocation, restored_aggregate, noop) = interval_update(
            a[offset:offset + length].copy(),
            y[day_start:day_start + length],
            p[day_start:day_start + length],
            state.totals[bill_index],
            cfg,
        )
        a[offset:offset + length] = new_allocation
        y[day_start:day_start + length] = restored_aggregate
        noops += noop
    return int(noops)

@njit(cache=True, fastmath=False)
def scaled_sweep(a, y, p, starts, lengths, totals, offsets, alpha, atol, rtol):
    """Compiled sequential sweep matching the reference arithmetic order."""
    noops = 0
    for bill_index in range(len(starts)):
        length = lengths[bill_index]
        day_start = starts[bill_index]
        offset = offsets[bill_index]
        total = totals[bill_index]
        other_contributions = np.empty(length)
        residual = np.empty(length)
        scale = 1.0
        max_residual = 0.0
        for day_offset in range(length):
            old_allocation = a[offset + day_offset]
            aggregate_value = y[day_start + day_offset]
            other_value = aggregate_value - old_allocation
            subtraction_tolerance = 64 * EPS * max(1.0, abs(aggregate_value), abs(old_allocation))
            if other_value < -subtraction_tolerance:
                raise ArithmeticError('Aggregate minus bill is materially negative')
            other_contributions[day_offset] = max(other_value, 0.0)
            scale = max(scale, abs(p[day_start + day_offset]), abs(other_contributions[day_offset]))
            residual[day_offset] = max(p[day_start + day_offset] - other_contributions[day_offset], 0.0)
            max_residual = max(max_residual, residual[day_offset])
            if not np.isfinite(residual[day_offset]):
                raise ArithmeticError('Nonfinite residual')
        if total == 0:
            for day_offset in range(length):
                a[offset + day_offset] = 0.0
                y[day_start + day_offset] = other_contributions[day_offset]
            continue
        if sum_compensated(residual) <= 64 * EPS * length * scale:
            noops += 1
            for day_offset in range(length):
                y[day_start + day_offset] = other_contributions[day_offset] + a[offset + day_offset]
            continue
        for day_offset in range(length):
            residual[day_offset] /= max_residual
        weight_sum = sum_compensated(residual)
        for day_offset in range(length):
            proposed_allocation = total * (residual[day_offset] / weight_sum)
            a[offset + day_offset] = (1 - alpha) * a[offset + day_offset] + alpha * proposed_allocation
        delta = total - sum_compensated(a[offset:offset + length])
        if abs(delta) > atol + rtol * abs(total):
            raise ArithmeticError('Correction exceeds threshold')
        largest_index = 0
        for day_offset in range(1, length):
            if a[offset + day_offset] > a[offset + largest_index]:
                largest_index = day_offset
        a[offset + largest_index] += delta
        for day_offset in range(length):
            if not np.isfinite(a[offset + day_offset]) or a[offset + day_offset] < 0:
                raise ArithmeticError('Invalid allocation')
            y[day_start + day_offset] = other_contributions[day_offset] + a[offset + day_offset]
    return noops

@njit(cache=True, fastmath=False)
def conservation_kernel(a, totals, offsets, atol, rtol):
    """Check bill sums and allocation validity; return the largest discrepancy."""
    max_discrepancy = 0.0
    for bill_index in range(len(totals)):
        discrepancy = abs(
            sum_compensated(a[offsets[bill_index]:offsets[bill_index + 1]]) - totals[bill_index],
        )
        max_discrepancy = max(max_discrepancy, discrepancy)
        if discrepancy > atol + rtol * abs(totals[bill_index]):
            raise ArithmeticError('Bill conservation failure')
    for value in a:
        if not np.isfinite(value) or value < 0:
            raise ArithmeticError('Allocation invariant failure')
    return max_discrepancy

def initialize(state, cfg, storage=None):
    """Allocate each bill uniformly, optionally creating file-backed storage."""
    size = int(state.offsets[-1])
    if storage and size * 8 > cfg.memmap_threshold_mb * 1024**2:
        allocations = np.memmap(storage, dtype=np.float64, mode='w+', shape=(size,))
    else:
        allocations = np.empty(size, dtype=np.float64)
    for bill_index, total in enumerate(state.totals):
        offset = int(state.offsets[bill_index])
        length = int(state.lengths[bill_index])
        allocations[offset:offset + length] = total / length
        correct_roundoff(allocations[offset:offset + length], total, cfg)
    return allocations

def lstsq_diagnostics(X, y, mask, cfg):
    """Fit masked aggregate observations and predict over the full domain."""
    fit_design = X[mask]
    fit_response = y[mask]
    n_fit, n_features = fit_design.shape
    if n_fit == 0:
        raise AvailabilityError('fit_unavailable: No fit rows')
    rcond = cfg.regression_rcond if cfg.regression_rcond is not None else max(n_fit, n_features) * EPS
    beta, _, rank, singular_values = np.linalg.lstsq(fit_design, fit_response, rcond=rcond)
    predicted = X @ beta
    if not np.isfinite(beta).all() or not np.isfinite(predicted).all():
        raise ArithmeticError('Nonfinite OLS')
    condition_number = float(singular_values[0] / singular_values[-1]) if rank == n_features else float('inf')
    diagnostics = {
        'rank': int(rank),
        'columns': n_features,
        'n_fit': n_fit,
        'rcond': rcond,
        'singular_values': singular_values.tolist(),
        'condition_number': condition_number,
        'condition_number_infinite': not math.isfinite(condition_number),
        'residual_norm': float(np.linalg.norm(fit_response - fit_design @ beta)),
        'column_ranges': [
            [
                float(np.min(fit_design[:, column_index])),
                float(np.max(fit_design[:, column_index])),
            ]
            for column_index in range(n_features)
        ],
        'zero_columns': np.flatnonzero(np.all(fit_design == 0, axis=0)).tolist(),
        'beta': beta.tolist(),
    }
    if cfg.mode == 'provisional_cohort_isd' and (
        rank != n_features
        or n_fit < max(30, 5 * n_features)
        or condition_number > 1e8
    ):
        raise AvailabilityError('fit_unavailable: rank/count/condition gate')
    return (beta, predicted, diagnostics)

def state_lock(state, X, mask, cfg):
    """Fingerprint inputs and settings for checkpoint compatibility, not payload integrity."""
    digest = hashlib.sha256()
    digest.update(state.identity_token.encode())
    for array in [state.starts, state.lengths, state.totals, state.offsets, X, mask]:
        digest.update(np.ascontiguousarray(array).tobytes())
    settings = cfg.as_dict()
    settings.pop('resume')
    settings.pop('checkpoint')
    settings.pop('engine')
    digest.update(json.dumps(settings, sort_keys=True).encode())
    return digest.hexdigest()

def solve(state, X, cfg, fit_mask=None, checkpoint_path=None, storage=None, stop_after_cycles=None, exposure=None):
    """Fit fixed aggregate predictions and shift full bill intervals sequentially."""
    started_at = time.perf_counter()
    cfg.validate()
    state.validate()
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[0] != state.n_days or (not np.isfinite(X).all()):
        raise ValueError('Invalid design')
    fit_rows = np.ones(state.n_days, bool) if fit_mask is None else np.asarray(fit_mask, dtype=bool)
    if fit_rows.shape != (state.n_days,):
        raise ValueError('Fit mask shape')
    if cfg.mode == 'paper_reference' and (not fit_rows.all()):
        raise ValueError('Reference fits all domain days')
    X = X.copy()
    X.setflags(write=False)
    fit_rows = fit_rows.copy()
    fit_rows.setflags(write=False)
    input_lock = state_lock(state, X, fit_rows, cfg)
    aggregate_function = aggregate_kernel.py_func if cfg.engine == 'reference' else aggregate_kernel
    # Establish allocations before optionally restoring completed-cycle state.
    allocations = initialize(state, cfg, storage)
    (daily_total, daily_count) = aggregate_function(
        allocations,
        state.starts,
        state.lengths,
        state.offsets,
        state.n_days,
    )
    iteration_diagnostics = []
    cycle_diagnostics = []
    total_noops = 0
    resume_data = None
    if cfg.resume:
        if not checkpoint_path or not Path(checkpoint_path).exists():
            raise ValueError('No resume checkpoint')
        loaded = np.load(checkpoint_path, allow_pickle=False)
        resume_data = {name: loaded[name].copy() for name in loaded.files}
        loaded.close()
        if str(resume_data['lock']) != input_lock:
            raise ValueError('Checkpoint input/design/config mismatch')
        allocations[:] = resume_data['a']
        daily_total = resume_data['y'].copy()
        iteration_diagnostics = json.loads(str(resume_data['iterations']))
        cycle_diagnostics = json.loads(str(resume_data['cycles']))
        total_noops = int(resume_data['noops'])
    if np.all(state.totals == 0):
        return Result(
            allocations,
            daily_total,
            np.zeros_like(daily_total),
            [],
            [],
            0,
            True,
            time.perf_counter() - started_at,
        )
    executed_cycles = 0
    first_outer = int(resume_data['outer']) if resume_data is not None else 0
    # Each outer fit supplies one prediction shared by all its shifting cycles.
    for outer_index in range(first_outer, cfg.n_lr_models):
        if resume_data is not None and outer_index == first_outer:
            beta = resume_data['beta']
            prediction = resume_data['prediction'].copy()
            fit_info = json.loads(str(resume_data['fit_info']))
            first_cycle = int(resume_data['next_cycle'])
            outer_start_total = resume_data['old_y']
            outer_start_allocations = resume_data['old_a']
            outer_noops = int(resume_data['outer_noops'])
        else:
            outer_start_total = daily_total.copy()
            outer_start_allocations = allocations.copy()
            outer_noops = 0
            first_cycle = 0
            beta, prediction, fit_info = lstsq_diagnostics(X, daily_total, fit_rows, cfg)
        prediction.setflags(write=False)
        prediction_hash = hashlib.sha256(prediction.tobytes()).hexdigest()
        for cycle_index in range(first_cycle, cfg.n_disagg_cycles):
            if cfg.engine == 'reference':
                cycle_noops = reference_sweep(allocations, daily_total, prediction, state, cfg)
            else:
                cycle_noops = scaled_sweep(
                    allocations,
                    daily_total,
                    prediction,
                    state.starts,
                    state.lengths,
                    state.totals,
                    state.offsets,
                    cfg.alpha,
                    cfg.reconciliation_atol,
                    cfg.reconciliation_rtol,
                )
            total_noops += cycle_noops
            outer_noops += cycle_noops
            # Check conservation, then rebuild the aggregate in canonical order.
            max_bill_error = conservation_kernel(
                allocations,
                state.totals,
                state.offsets,
                cfg.reconciliation_atol,
                cfg.reconciliation_rtol,
            )
            (recomputed_total, daily_count) = aggregate_function(
                allocations,
                state.starts,
                state.lengths,
                state.offsets,
                state.n_days,
            )
            aggregate_discrepancy = np.abs(recomputed_total - daily_total)
            gamma = daily_count * EPS / (1 - daily_count * EPS)
            drift_bound = gamma * np.abs(recomputed_total) + daily_count * cfg.reconciliation_atol
            if np.any(aggregate_discrepancy > drift_bound):
                raise ArithmeticError('Aggregate drift exceeds summation bound')
            if hashlib.sha256(prediction.tobytes()).hexdigest() != prediction_hash:
                raise ArithmeticError('Prediction mutated')
            daily_total = recomputed_total
            cycle_diagnostics.append(
                {
                    'outer': outer_index,
                    'cycle': cycle_index,
                    'zero_residual_noops': int(cycle_noops),
                    'max_bill_abs_error': float(max_bill_error),
                    'max_aggregate_discrepancy': float(aggregate_discrepancy.max()),
                    'max_aggregate_bound': float(drift_bound.max()),
                },
            )
            executed_cycles += 1
            # Save only completed cycles, replacing the previous checkpoint atomically.
            if cfg.checkpoint and checkpoint_path:
                temporary_checkpoint = Path(str(checkpoint_path) + '.tmp')
                with temporary_checkpoint.open('wb') as checkpoint_file:
                    np.savez(
                        checkpoint_file,
                        lock=input_lock,
                        a=allocations,
                        y=daily_total,
                        prediction=prediction,
                        beta=beta,
                        outer=outer_index,
                        next_cycle=cycle_index + 1,
                        old_y=outer_start_total,
                        old_a=outer_start_allocations,
                        outer_noops=outer_noops,
                        noops=total_noops,
                        iterations=json.dumps(iteration_diagnostics),
                        cycles=json.dumps(cycle_diagnostics),
                        fit_info=json.dumps(fit_info),
                        fit_mask=fit_rows,
                        design=X,
                        g=np.ones(state.n_days) if exposure is None else exposure,
                        source_order_identity=state.identity_token,
                        config_json=json.dumps(cfg.as_dict()),
                    )
                temporary_checkpoint.replace(checkpoint_path)
            if stop_after_cycles and executed_cycles >= stop_after_cycles:
                return Result(
                    allocations,
                    daily_total,
                    prediction,
                    iteration_diagnostics,
                    cycle_diagnostics,
                    total_noops,
                    False,
                    time.perf_counter() - started_at,
                )
        # Compare the completed outer iteration with its saved starting state.
        aggregate_change = daily_total - outer_start_total
        allocation_change = allocations - outer_start_allocations
        fit_info.update(
            {
                'outer': outer_index,
                'max_y_change_fit': float(np.max(np.abs(aggregate_change[fit_rows]))),
                'relative_y_change_fit': float(
                    np.linalg.norm(aggregate_change[fit_rows])
                    / max(np.linalg.norm(outer_start_total[fit_rows]), EPS)
                ),
                'max_allocation_change': float(np.max(np.abs(allocation_change))),
                'relative_allocation_change': float(
                    np.linalg.norm(allocation_change)
                    / max(np.linalg.norm(outer_start_allocations), EPS)
                ),
                'negative_predicted_days': int(np.sum(prediction < 0)),
                'zero_residual_noops': outer_noops,
                'final_fit_residual_norm': float(
                    np.linalg.norm(daily_total[fit_rows] - prediction[fit_rows])
                ),
            },
        )
        iteration_diagnostics.append(fit_info)
        resume_data = None
    return Result(
        allocations,
        daily_total,
        prediction,
        iteration_diagnostics,
        cycle_diagnostics,
        total_noops,
        False,
        time.perf_counter() - started_at,
    )
