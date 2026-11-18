"""Tests for bt_stats_v2 (deflated Sharpe v2; frozen bt_stats untouched)."""

import math

import numpy as np
import pandas as pd
import pytest

import bt_stats as bs
import bt_stats_v2 as v2


def _series(mu, sd, n=6000, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("1990-01-01", periods=n)
    return pd.Series(rng.normal(mu, sd, n), index=idx)


def test_frozen_module_unchanged_surface():
    # v2 must only add; the frozen names are still those of bt_stats.
    assert v2.ANN == bs.ANN and v2.DSR_MIN == bs.DSR_MIN
    assert callable(bs.deflated_sharpe) and callable(bs.expected_max_sharpe)


def test_cross_trial_variance_matches_manual():
    s = [0.6, 0.3, 0.1, 0.9]
    exp = pd.Series(s).div(math.sqrt(bs.ANN)).var(ddof=1)
    assert v2.cross_trial_variance(s) == pytest.approx(exp)
    assert math.isnan(v2.cross_trial_variance([0.5]))


def test_cross_trial_sr0_grows_with_variance_and_trials():
    r = _series(0.0004, 0.01)
    a = v2.deflated_sharpe_cross_trial(r, 10, 1e-4)
    b = v2.deflated_sharpe_cross_trial(r, 100, 1e-4)
    c = v2.deflated_sharpe_cross_trial(r, 10, 4e-4)
    assert a["sr0_daily"] < b["sr0_daily"]
    assert a["sr0_daily"] < c["sr0_daily"]
    assert a["dsr"] > b["dsr"] > 0.0


def test_cross_trial_with_tiny_variance_recovers_frozen_dsr():
    r = _series(0.0004, 0.01)
    own = bs.deflated_sharpe(r, 34)
    # feeding the frozen own-variance into v2 reproduces the frozen number
    sr, T, skew, kurt = v2._moments(r)
    var_own = (1 - skew * sr + (kurt - 1) / 4 * sr**2) / (T - 1)
    mine = v2.deflated_sharpe_cross_trial(r, 34, var_own)
    assert mine["dsr"] == pytest.approx(own["dsr"], abs=1e-9)


def test_vs_benchmark_identical_series_fails():
    r = _series(0.0004, 0.01)
    out = v2.deflated_sharpe_vs_benchmark(r, r.copy(), 34)
    # zero active return -> sr nan/0 -> cannot pass
    assert not out["passes"]


def test_vs_benchmark_clear_outperformance_passes():
    bench = _series(0.0002, 0.01, seed=1)
    strat = bench + 0.0006  # +15% a year of pure alpha, zero tracking noise
    out = v2.deflated_sharpe_vs_benchmark(strat + _series(0, 0.002, seed=2), bench, 100)
    assert out["sr_annual"] > 1.0
    assert out["passes"]


def test_vs_benchmark_noise_vs_benchmark_fails_with_cross_variance():
    bench = _series(0.0003, 0.01, seed=3)
    strat = bench + _series(0.0, 0.003, seed=4)  # no alpha, just tracking noise
    out = v2.deflated_sharpe_vs_benchmark(strat, bench, 119, var_sr_daily=1.2e-4)
    assert out["dsr"] < v2.DSR_MIN


def test_invalid_variance_raises():
    with pytest.raises(ValueError):
        v2.deflated_sharpe_cross_trial(_series(0, 0.01), 10, float("nan"))


def test_score_table_shape_and_pass_logic():
    bench = _series(0.0003, 0.01, seed=5)
    rf = pd.Series(0.0, index=bench.index)
    runs = {"good": bench + 0.0008, "same": bench.copy()}
    tab = v2.score_table(runs, bench, rf, 34, 119, 1.2e-4)
    assert list(tab.index) == ["good", "same"]
    assert set(["dsr_v1", "dsr_vs_bench", "dsr_cross_full", "pass_v2"]) <= set(
        tab.columns
    )
    assert bool(tab.loc["good", "pass_v2"]) and not bool(tab.loc["same", "pass_v2"])
