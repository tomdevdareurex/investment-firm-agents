import numpy as np
import pandas as pd
import pytest

import bt_common as bc
import bt_long as bl
import bt_periods as bp


@pytest.fixture(scope="module")
def sample():
    return bl.long_sample()


@pytest.fixture(scope="module")
def bench(sample):
    return bp.benchmark_returns(sample["px"], sample["cash"])


def test_period_bounds_clip_to_index():
    idx = pd.bdate_range("1950-01-01", "2015-12-31")
    lo, hi = bp.period_bounds("dev", idx)
    assert lo == idx[0] and hi == pd.Timestamp("1989-12-31")
    lo, hi = bp.period_bounds("holdout", idx)
    assert lo == pd.Timestamp("2010-01-01") and hi == idx[-1]
    assert bp.period_bounds("full", idx) == (idx[0], idx[-1])


def test_periods_are_disjoint_and_cover(sample):
    idx = sample["px"].index
    parts = [bp.slice_period(sample["px"], p).index for p in ("dev", "val", "holdout")]
    assert sum(len(p) for p in parts) == len(idx)
    assert parts[0][-1] < parts[1][0] < parts[1][-1] < parts[2][0]


def test_constant_mix_between_components():
    idx = pd.bdate_range("2000-01-03", periods=600)
    rng = np.random.default_rng(0)
    r_eq = pd.Series(rng.normal(0.0004, 0.01, len(idx)), idx)
    r_cash = pd.Series(0.0001, idx)
    mix = bp.constant_mix_returns(r_eq, r_cash, 0.6)
    assert len(mix) == len(idx) and mix.notna().all()
    assert mix.std() == pytest.approx(0.6 * r_eq.std(), rel=0.05)
    mix1 = bp.constant_mix_returns(r_eq, r_cash, 1.0)
    assert np.allclose(mix1.values, r_eq.values)


def test_benchmark_returns_match_reference(bench):
    full = bc.perf_stats(bench["sma200"], bench["tbill"])
    bh = bc.perf_stats(bench["bh"], bench["tbill"])
    assert abs(full["Sharpe"] - 0.64) < 0.03
    assert abs(bh["Sharpe"] - 0.51) < 0.03
    assert bench.index[0] > pd.Timestamp("1935-01-01")  # warm-up dropped
    assert set(bench.columns) == {"bh", "sma200", "mix60", "tbill"}


def test_benchmark_table_shape(bench):
    tab = bp.benchmark_table(bench)
    assert tab.index.nlevels == 2
    assert set(tab.index.get_level_values(0)) == {"dev", "val", "holdout", "full"}
    assert tab.loc[("full", "tbill"), "Sharpe"] == pytest.approx(
        0.0, abs=1e-9
    ) or np.isnan(tab.loc[("full", "tbill"), "Sharpe"])
    # 60/40 drawdown must be shallower than B&H in every period
    for p in ("dev", "val", "holdout", "full"):
        assert tab.loc[(p, "mix60"), "Max DD"] > tab.loc[(p, "bh"), "Max DD"]


def test_run_periods_and_compare(sample, bench):
    px, cash = sample["px"], sample["cash"]
    signal, sma = bc.sma_signal(px["close"], 200)
    runs = bp.run_periods(px, signal, cash, extra={"sma": sma})
    assert set(runs) == {"dev", "val", "holdout", "full"}
    assert runs["full"].attrs["period"] == "full"
    cmp = bp.compare_to_benchmarks(runs, bench)
    # identical rule -> zero diff vs the sma200 benchmark in every period
    assert (cmp["d_sma200"].abs() < 1e-9).all()
    tab = bp.period_table(runs)
    assert "Switches" in tab.columns and tab.loc["full", "Switches"] >= 130
