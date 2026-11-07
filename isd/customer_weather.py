"""Customer ridge smoothing of generated daily allocations, conserving each bill."""
import numpy as np
from numba import njit


def prepare_customer_model(state, groups, design, penalty):
    groups = np.asarray(groups)
    design = np.asarray(design, dtype=float)
    if groups.shape != state.starts.shape or groups.dtype.kind not in 'iu' or np.any(groups < 0):
        raise ValueError('Integer customer group per bill required')
    if design.ndim != 2 or design.shape[0] != state.n_days or design.shape[1] < 1 or not np.isfinite(design).all():
        raise ValueError('Finite customer design required')
    if not np.all(design[:, 0] == 1):
        raise ValueError('Customer design must start with intercept')
    # Canonical ledger order keeps all bills for a customer contiguous.
    bounds = np.r_[0, np.flatnonzero(groups[1:] != groups[:-1])+1, len(groups)].astype(np.int64)
    if len(np.unique(groups)) != len(bounds)-1:
        raise ValueError('Customer bills must be contiguous')
    means, scales, inverses, available = [], [], [], []
    cache = {}
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        days = np.concatenate([np.arange(s, s+l) for s, l in zip(state.starts[lo:hi], state.lengths[lo:hi])])
        if len(np.unique(days)) != len(days):
            raise ValueError('Overlapping customer bill support')
        key = days.tobytes()
        if key not in cache:
            rows = design[days]
            mean = rows.mean(axis=0); mean[0] = 0
            scale = rows.std(axis=0); scale[0] = 1
            scale[scale <= 64*np.finfo(float).eps*np.maximum(1, np.abs(mean))] = 1
            Z = (rows-mean)/scale
            ridge = np.eye(Z.shape[1])*penalty; ridge[0, 0] = 0
            try:
                inverse = np.linalg.solve(Z.T @ Z + ridge, np.eye(Z.shape[1]))
                valid = len(days) >= 2 and np.isfinite(inverse).all()
            except np.linalg.LinAlgError:
                inverse = np.zeros_like(ridge); valid = False
            cache[key] = (mean, scale, inverse, valid)
        mean, scale, inverse, valid = cache[key]
        means.append(mean); scales.append(scale); inverses.append(inverse); available.append(valid)
    return (bounds, design.copy(), np.array(means), np.array(scales), np.array(inverses), np.array(available))


@njit(cache=True, fastmath=False)
def customer_weather_sweep(a, starts, lengths, offsets, totals, fallback, bounds, design,
                           means, scales, inverses, available, reserve, strength, atol, rtol):
    """Fit all customer models to a frozen pre-correction sweep, then reconcile bills."""
    fallbacks = 0
    p = design.shape[1]
    for owner in range(len(bounds)-1):
        rhs = np.zeros(p)
        for k in range(bounds[owner], bounds[owner+1]):
            for j in range(lengths[k]):
                d = starts[k]+j
                for col in range(p):
                    z = (design[d, col]-means[owner, col])/scales[owner, col]
                    rhs[col] += z*a[offsets[k]+j]
        coefficients = np.zeros(p)
        for row in range(p):
            for col in range(p):
                coefficients[row] += inverses[owner, row, col]*rhs[col]
        for k in range(bounds[owner], bounds[owner+1]):
            if totals[k] == 0:
                continue
            prediction = np.zeros(lengths[k])
            for j in range(lengths[k]):
                d = starts[k]+j
                for col in range(p):
                    prediction[j] += coefficients[col]*(design[d, col]-means[owner, col])/scales[owner, col]
                prediction[j] = max(prediction[j], 0.)
            maximum = np.max(prediction)
            use_fallback = not available[owner] or not np.isfinite(prediction).all() or maximum <= 0
            if use_fallback:
                fallbacks += 1
            else:
                prediction /= maximum
            weight_sum = prediction.sum()
            for j in range(lengths[k]):
                q = fallback[offsets[k]+j] if use_fallback else totals[k]*((1-reserve)*prediction[j]/weight_sum+reserve/lengths[k])
                a[offsets[k]+j] = (1-strength)*a[offsets[k]+j]+strength*q
            values = a[offsets[k]:offsets[k+1]]
            delta = totals[k]-values.sum()
            if abs(delta) > atol+rtol*abs(totals[k]):
                raise ArithmeticError('Customer correction exceeds reconciliation tolerance')
            values[np.argmax(values)] += delta
    return fallbacks
