from dataclasses import replace
import numpy as np
import pytest
from isd.config import Config
from isd.solver import State, solve, interval_update


@pytest.mark.parametrize('strength', [.01, .05, 1.])
def test_engines_conservation_resume(strength, tmp_path):
    state = State(np.array([0, 0, 0]), np.array([4, 4, 4]), np.array([20., 80., 0.]), np.array([0, 4, 8, 12]), 4)
    cfg = Config(mode='paper_reference', feature_preset='paper_section3_v1', engine='reference',
                 individual_reference_strength=strength, checkpoint=False, n_lr_models=3, n_disagg_cycles=5)
    design = np.column_stack([np.ones(4), [0, 0, 0, 10]])
    weights = np.array([1., 2., 3., 4.])
    ref = solve(state, design, cfg, reference_weights=weights)
    fast = solve(state, design, replace(cfg, engine='scaled'), reference_weights=weights)
    np.testing.assert_allclose(fast.allocations, ref.allocations, atol=1e-10)
    np.testing.assert_allclose([sum(fast.allocations[:4]), sum(fast.allocations[4:8])], [20, 80])
    np.testing.assert_array_equal(fast.allocations[8:], 0)
    if strength == 1:
        np.testing.assert_allclose(fast.allocations[:4], [2, 4, 6, 8])
    ck = tmp_path / 'state.npz'
    solve(state, design, replace(cfg, checkpoint=True), checkpoint_path=ck, stop_after_cycles=7, reference_weights=weights)
    resumed = solve(state, design, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck, reference_weights=weights)
    np.testing.assert_array_equal(resumed.allocations, ref.allocations)
    with pytest.raises(ValueError, match='mismatch'):
        solve(state, design, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck, reference_weights=weights+1)


def test_zero_aggregate_residual_still_corrects_individual():
    cfg = Config(individual_reference_strength=.1)
    new, aggregate, noop = interval_update(np.array([9., 1.]), np.array([20., 20.]), np.zeros(2), 10, cfg, np.array([2., 8.]))
    np.testing.assert_allclose(new, [8.3, 1.7])
    np.testing.assert_allclose(aggregate, [19.3, 20.7])
    assert not noop


@pytest.mark.parametrize('value', [-.1, 1.1, float('nan'), float('inf'), True])
def test_invalid_strength(value):
    with pytest.raises(ValueError, match='individual_reference_strength'):
        Config(individual_reference_strength=value).validate()


def test_missing_reference_weights_rejected():
    state = State(np.array([0]), np.array([2]), np.array([10.]), np.array([0, 2]), 2)
    cfg = Config(mode='paper_reference', feature_preset='paper_section3_v1', individual_reference_strength=.1)
    with pytest.raises(ValueError, match='reference_weights'):
        solve(state, np.ones((2, 1)), cfg)
