from dataclasses import replace
import math
import numpy as np
import pytest
from isd.config import Config
from isd.solver import State, solve, interval_update


@pytest.mark.parametrize('floor', [0.1, 0.2, 1.0])
def test_floor_conservation_engines_and_resume(floor, tmp_path):
    state = State(np.array([0, 0, 0]), np.array([4, 4, 4]), np.array([20., 80., 0.]), np.array([0, 4, 8, 12]), 4)
    cfg = Config(mode='paper_reference', feature_preset='paper_section3_v1', engine='reference', checkpoint=False,
                 redistribution_floor=floor, n_lr_models=3, n_disagg_cycles=10)
    design = np.column_stack([np.ones(4), [0, 0, 0, 10]])
    reference = solve(state, design, cfg)
    fast = solve(state, design, replace(cfg, engine='scaled'))
    np.testing.assert_allclose(fast.allocations, reference.allocations, atol=1e-12)
    for k, total in enumerate(state.totals):
        values = fast.allocations[4*k:4*k+4]
        assert math.fsum(values) == pytest.approx(total)
        assert np.all(values >= floor * total / 4 - 1e-12)
    np.testing.assert_array_equal(fast.allocations[8:], 0)
    if floor == 1:
        np.testing.assert_allclose(fast.allocations[:8], [5]*4+[20]*4)
    checkpoint = tmp_path / 'state.npz'
    solve(state, design, replace(cfg, checkpoint=True), checkpoint_path=checkpoint, stop_after_cycles=7)
    resumed = solve(state, design, replace(cfg, checkpoint=True, resume=True), checkpoint_path=checkpoint)
    np.testing.assert_array_equal(resumed.allocations, reference.allocations)
    with pytest.raises(ValueError, match='mismatch'):
        solve(state, design, replace(cfg, checkpoint=True, resume=True, redistribution_floor=0), checkpoint_path=checkpoint)


def test_proposal_reserves_uniform_share():
    cfg = Config(alpha=1, redistribution_floor=.2)
    values, _, _ = interval_update(np.array([5., 5.]), np.array([5., 5.]), np.array([10., 0.]), 10., cfg)
    np.testing.assert_allclose(values, [9., 1.])


@pytest.mark.parametrize('value', [-.1, 1.1, float('nan'), float('inf'), True])
def test_invalid_floor(value):
    with pytest.raises(ValueError, match='redistribution_floor'):
        Config(redistribution_floor=value).validate()
