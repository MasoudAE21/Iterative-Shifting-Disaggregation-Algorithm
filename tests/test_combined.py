from dataclasses import replace
import numpy as np
import pytest
from isd.config import Config
from isd.solver import State, solve, interval_update, seasonal_reference


def fixture():
    n = 60
    state = State(np.array([0, 30, 0]), np.array([30, 30, 60]),
                  np.array([90., 120., 0.]), np.array([0, 30, 60, 120]), n)
    X = np.column_stack([np.ones(n), np.sin(np.arange(n)/7)])
    weights = 1 + np.maximum(0, 10 + 15*np.sin(np.arange(n)/9))
    cfg = Config(engine='reference', checkpoint=False, initialization='seasonal_reference',
                 redistribution_floor=.1, individual_reference_strength=.03,
                 n_lr_models=2, n_disagg_cycles=3)
    return state, X, weights, cfg


def test_combined_engines_floor_conservation_and_resume(tmp_path):
    st, X, w, c = fixture()
    result = solve(st, X, c, reference_weights=w)
    fast = solve(st, X, replace(c, engine='scaled'), reference_weights=w)
    np.testing.assert_allclose(result.allocations, fast.allocations, atol=1e-12)
    for k, total in enumerate(st.totals):
        a = result.allocations[st.offsets[k]:st.offsets[k+1]]
        assert a.sum() == pytest.approx(total)
        assert np.min(a) >= .1*total/st.lengths[k] - 1e-12
    ck = tmp_path/'checkpoint.npz'
    solve(st, X, replace(c, checkpoint=True), checkpoint_path=ck, stop_after_cycles=2, reference_weights=w)
    resumed = solve(st, X, replace(c, checkpoint=True, resume=True), checkpoint_path=ck, reference_weights=w)
    np.testing.assert_array_equal(result.allocations, resumed.allocations)
    with pytest.raises(ValueError, match='mismatch'):
        solve(st, X, replace(c, checkpoint=True, resume=True), checkpoint_path=ck, reference_weights=w+1)


def test_zero_residual_still_corrects():
    _, _, _, c = fixture()
    old = np.array([1., 9.])
    q = np.array([6., 4.])
    new, y, noop = interval_update(old, old, np.zeros(2), 10, c, q)
    np.testing.assert_allclose(new, .97*old + .03*q)
    np.testing.assert_array_equal(new, y)
    assert not noop


@pytest.mark.parametrize('value', [-.1, 1.1, float('nan'), float('inf'), True])
def test_invalid_fractions(value):
    with pytest.raises(ValueError):
        Config(redistribution_floor=value).validate()


def test_invalid_reference_and_disabled_equivalence():
    st, X, w, c = fixture()
    with pytest.raises(ValueError, match='Positive finite'):
        seasonal_reference(st, np.zeros(st.n_days), c)
    disabled = replace(c, initialization='uniform', redistribution_floor=0., individual_reference_strength=0.)
    a = solve(st, X, disabled).allocations
    b = solve(st, X, disabled, reference_weights=w).allocations
    np.testing.assert_array_equal(a, b)
