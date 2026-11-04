from dataclasses import replace
import numpy as np
import pytest
from isd.config import Config
from isd.solver import State, initialize, solve


def example():
    state = State(np.array([0, 2, 0]), np.array([2, 2, 4]), np.array([8., 12., 0.]), np.array([0, 2, 4, 8]), 4)
    cfg = Config(mode='paper_reference', feature_preset='paper_section3_v1', engine='reference',
                 initialization='seasonal_hdd65', checkpoint=False, n_lr_models=2, n_disagg_cycles=3)
    return state, cfg, np.array([1., 3., 2., 4.])


def test_bill_normalization_and_zero():
    state, cfg, weights = example()
    np.testing.assert_allclose(initialize(state, cfg, initial_weights=weights), [2, 6, 4, 8, 0, 0, 0, 0])
    np.testing.assert_allclose(initialize(state, replace(cfg, initialization='uniform')), [4, 4, 6, 6, 0, 0, 0, 0])


def test_engines_resume_and_changed_weather(tmp_path):
    state, cfg, weights = example()
    design = np.column_stack([np.ones(4), [0, 2, 1, 0]])
    ref = solve(state, design, cfg, initial_weights=weights)
    fast = solve(state, design, replace(cfg, engine='scaled'), initial_weights=weights)
    np.testing.assert_allclose(ref.allocations, fast.allocations, atol=1e-12)
    ck = tmp_path / 'state.npz'
    solve(state, design, replace(cfg, checkpoint=True), checkpoint_path=ck, initial_weights=weights, stop_after_cycles=2)
    resumed = solve(state, design, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck, initial_weights=weights)
    np.testing.assert_array_equal(ref.allocations, resumed.allocations)
    with pytest.raises(ValueError, match='mismatch'):
        solve(state, design, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck, initial_weights=weights+1)


@pytest.mark.parametrize('weights', [None, [1, 2], [1, 2, 0, 3], [1, 2, -1, 3], [1, 2, float('nan'), 3]])
def test_invalid_weights(weights):
    state, cfg, _ = example()
    with pytest.raises(ValueError, match='initial_weights'):
        initialize(state, cfg, initial_weights=weights)
