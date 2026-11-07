from dataclasses import replace
import numpy as np
import pytest
from isd.solver import State, solve, seasonal_reference
from isd.config import Config
from isd.customer_weather import prepare_customer_model, customer_weather_sweep


def example():
    n = 60
    state = State(np.array([0, 30, 0]), np.array([30, 30, 60]),
                  np.array([90., 120., 0.]), np.array([0, 30, 60, 120]), n)
    groups = np.array([0, 0, 1])
    X = np.column_stack([np.ones(n), np.sin(np.arange(n)/7)])
    weather = np.column_stack([np.ones(n), np.maximum(0, np.sin(np.arange(n)/9)),
                               np.zeros(n), np.arange(n), np.arange(n)])
    w = 1 + weather[:, 1]
    cfg = Config(checkpoint=False, engine='reference', initialization='seasonal_reference',
                 redistribution_floor=.1, individual_reference_strength=.03, customer_model='weather_ridge',
                 n_lr_models=2, n_disagg_cycles=3)
    return state, X, groups, weather, w, cfg


def test_weather_engines_checkpoint_and_floor(tmp_path):
    st, X, g, W, w, cfg = example()
    kw = dict(reference_weights=w, customer_groups=g, customer_design=W)
    ref = solve(st, X, cfg, **kw)
    fast = solve(st, X, replace(cfg, engine='scaled'), **kw)
    np.testing.assert_allclose(ref.allocations, fast.allocations, atol=1e-11)
    for k, total in enumerate(st.totals):
        a = fast.allocations[st.offsets[k]:st.offsets[k+1]]
        assert a.sum() == pytest.approx(total)
        assert a.min() >= .1*total/st.lengths[k]-1e-12
    ck = tmp_path/'weather.npz'
    solve(st, X, replace(cfg, checkpoint=True), checkpoint_path=ck, stop_after_cycles=2, **kw)
    resumed = solve(st, X, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck, **kw)
    np.testing.assert_array_equal(ref.allocations, resumed.allocations)
    with pytest.raises(ValueError, match='mismatch'):
        solve(st, X, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck,
              **dict(kw, customer_design=W+np.array([0, 1, 0, 0, 0])))
    with pytest.raises(ValueError, match='mismatch'):
        solve(st, X, replace(cfg, checkpoint=True, resume=True), checkpoint_path=ck,
              **dict(kw, customer_groups=np.array([0, 1, 2])))


def test_unavailable_customer_and_zero_prediction_fallback():
    st, X, g, W, w, cfg = example()
    fallback = seasonal_reference(st, w, cfg)
    plan = list(prepare_customer_model(st, g, W, 1))
    # Explicit unavailable fit, then a zero prediction despite positive bills.
    for unavailable in [True, False]:
        a = fallback.copy()
        plan[-1][:] = not unavailable
        if not unavailable:
            plan[-2][:] = 0
        count = customer_weather_sweep(a, st.starts, st.lengths, st.offsets, st.totals,
                                       fallback, *plan, .1, .03, 1e-8, 1e-10)
        assert count == 2
        np.testing.assert_allclose(a, fallback, atol=1e-12)


def test_invalid_customer_inputs():
    st, X, g, W, w, cfg = example()
    for bad in [np.array([0, 1, 0]), np.array([-1, 0, 0]), np.array([0., 0., 1.])]:
        with pytest.raises(ValueError):
            prepare_customer_model(st, bad, W, 1)
    with pytest.raises(ValueError):
        prepare_customer_model(st, g, W*float('nan'), 1)
    for penalty in [0, -1, float('nan')]:
        with pytest.raises(ValueError):
            replace(cfg, customer_ridge_penalty=penalty).validate()


def test_ridge_matches_augmented_least_squares_oracle():
    n = 20
    st = State(np.array([0]), np.array([n]), np.array([50.]), np.array([0, n]), n)
    W = np.column_stack([np.ones(n), np.arange(n), np.sin(np.arange(n))])
    old = np.r_[np.zeros(10), np.full(10, 5.)]
    cfg = Config(redistribution_floor=.1)
    q = seasonal_reference(st, np.ones(n), cfg)
    plan = prepare_customer_model(st, np.array([0]), W, 1.)
    Z = (W-plan[2][0])/plan[3][0]
    penalty = np.diag([0., 1., 1.])
    beta = np.linalg.lstsq(np.vstack([Z, penalty]), np.r_[old, np.zeros(3)], rcond=None)[0]
    pred = np.maximum(Z@beta, 0)
    expected = .97*old + .03*50*(.9*pred/pred.sum()+.1/n)
    actual = old.copy()
    customer_weather_sweep(actual, st.starts, st.lengths, st.offsets, st.totals, q,
                           *plan, .1, .03, 1e-8, 1e-10)
    np.testing.assert_allclose(actual, expected, atol=1e-12)
