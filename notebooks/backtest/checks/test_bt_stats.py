import numpy as np
import pandas as pd
import pytest

import bt_common as bc
import bt_long as bl
import bt_periods as bp
import bt_stats as bs


@pytest.fixture(scope="module")
def sample():
    return bl.long_sample()


@pytest.fixture(scope="module")
def bench(sample):
    return bp.benchmark_returns(sample["px"], sample["cash"])


@pytest.fixture(scope="module")
def sma_runs(sample):
    sig, _ = bc.sma_signal(sample["px"]["close"], 200)
    return bp.run_periods(sample["px"], sig, sample["cash"])


def test_excess_sharpe_known_value():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0004, 0.01, 5000))
    expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert bs.excess_sharpe(r) == pytest.approx(expected)
    # subtracting the risk-free rate lowers the Sharpe
    rf = pd.Series(0.0001, index=r.index)
    assert bs.excess_sharpe(r, rf) < bs.excess_sharpe(r)


def test_bootstrap_identical_series_p_about_half():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0003, 0.01, 2000))
    res = bs.sharpe_diff_bootstrap(r, r, n_boot=300, block=63, rng=rng)
    assert res.diff == pytest.approx(0.0)
    assert 0.3 <= res.p_value <= 1.0
    assert res.ci_low <= 0 <= res.ci_high
    assert not res.significant


def test_bootstrap_detects_clearly_better_series():
    rng = np.random.default_rng(2)
    base = rng.normal(0.0, 0.01, 3000)
    a = pd.Series(base + 0.0015)
    b = pd.Series(base)
    res = bs.sharpe_diff_bootstrap(a, b, n_boot=300, block=63, rng=rng)
    assert res.diff > 0
    assert res.p_value <= 0.05
    assert res.significant
    row = res.row()
    assert set(row) >= {"sharpe_a", "sharpe_b", "diff", "p_one_sided"}


def test_placebo_returns_calibrated_dict(sample):
    px = sample["px"].loc["1990":]
    cash = sample["cash"].reindex(px.index).ffill()
    sig, _ = bc.sma_signal(px["close"], 200)
    res = bs.placebo_test(px, sig, cash, n_placebo=20, rng=np.random.default_rng(3))
    for k in ("real", "placebo_mean", "placebo_q95", "quantile", "p_one_sided"):
        assert k in res
    assert 0.0 <= res["quantile"] <= 1.0
    assert 0.0 <= res["p_one_sided"] <= 1.0
    assert res["n_placebo"] == 20
    assert 0.3 < res["time_in_market"] < 1.0


def test_deflated_sharpe_single_trial_and_monotone():
    rng = np.random.default_rng(4)
    r = pd.Series(rng.normal(0.0005, 0.01, 2500))
    one = bs.deflated_sharpe(r, n_trials=1)
    many = bs.deflated_sharpe(r, n_trials=50)
    assert one["sr0_daily"] == pytest.approx(0.0)
    assert many["sr0_daily"] > 0
    assert one["dsr"] > many["dsr"]
    assert 0.0 <= many["dsr"] <= 1.0
    assert one["T"] == 2500
    assert bs.expected_max_sharpe(1, 1.0) == 0.0
    assert bs.expected_max_sharpe(100, 1.0) > bs.expected_max_sharpe(10, 1.0)


def test_cost_sensitivity_monotone(sample):
    px = sample["px"].loc["1990":]
    cash = sample["cash"].reindex(px.index).ffill()
    sig, _ = bc.sma_signal(px["close"], 200)
    tab = bs.cost_sensitivity(px, sig, cash, bps_list=(0, 10, 50))
    assert list(tab.index) == [0, 10, 50]
    assert tab["Sharpe"].is_monotonic_decreasing
    assert tab["CAGR"].is_monotonic_decreasing
    assert tab["turnover_pa"].nunique() == 1
    be = bs.breakeven_cost_bps(px, sig, cash, bench_sharpe=tab["Sharpe"].iloc[-1])
    assert 10 <= be <= 50
    assert bs.breakeven_cost_bps(px, sig, cash, bench_sharpe=99.0) == 0.0


def test_primary_metric_sma200_vs_itself(sma_runs, bench):
    res = bs.primary_metric(
        sma_runs, bench, n_trials=1, n_boot=200, rng=np.random.default_rng(5)
    )
    for p in ("dev", "val", "holdout", "full"):
        assert p in res.sharpe
    # the SMA200 strategy is the sma200 benchmark: diff ~ 0, not significant
    for p in ("dev", "val"):
        assert abs(res.d_sma200[p]) < 0.05
        assert res.p_vs_sma200[p] > bs.P_MAX
    assert not res.passes
    tab = res.to_frame()
    assert list(tab.columns) == ["Sharpe", "d_sma200", "d_bh", "p_vs_sma200"]
    row = res.row()
    assert "sharpe_dev" in row and "passes" in row
    assert bs.passes_criteria(res) is res.passes


def test_primary_metric_passes_for_peeking_strategy(sample, bench):
    px = sample["px"]
    r = px["close"].pct_change()
    peek = (r.shift(-2) > 0).astype(float)
    runs = bp.run_periods(px, peek, sample["cash"], rebalance="daily")
    res = bs.primary_metric(
        runs, bench, n_trials=1, n_boot=200, rng=np.random.default_rng(6)
    )
    assert all(res.d_sma200[p] > 0 for p in ("dev", "val", "holdout"))
    assert all(res.p_vs_sma200[p] <= bs.P_MAX for p in ("dev", "val"))
    assert res.dsr >= bs.DSR_MIN
    assert res.passes and res.holdout_confirms


def test_criteria_frozen_constants():
    assert bs.CRITERIA["p_max"] == 0.10
    assert bs.CRITERIA["dsr_min"] == 0.95
    assert bs.CRITERIA["n_boot"] == 10_000
    assert bs.CRITERIA["beat_benchmarks_in"] == ("dev", "val")


@pytest.fixture
def synthetic_primary():
    idx = pd.bdate_range("2000-01-03", periods=900)
    noise = np.random.default_rng(71).normal(0, 0.01, len(idx))
    full = pd.DataFrame({"r_strat": noise + 0.0015, "r_cash": 0.0001}, index=idx)
    runs = {
        "dev": full.iloc[:300].copy(),
        "val": full.iloc[300:600].copy(),
        "holdout": full.iloc[600:].copy(),
        "full": full.copy(),
    }
    bench = pd.DataFrame({"sma200": noise, "bh": noise, "tbill": 0.0001}, index=idx)
    return runs, bench


def synthetic_metric(runs, bench, **kwargs):
    return bs.primary_metric(runs, bench, n_trials=4, n_boot=40, block=21, **kwargs)


def test_matched_primary_dsr_is_pre_holdout_only(synthetic_primary):
    runs, bench = synthetic_primary
    before = synthetic_metric(runs, bench, evidence_version="matched-v1")
    train = pd.concat([runs["dev"], runs["val"]])
    assert before.dsr == bs.deflated_sharpe(train.r_strat, 4, train.r_cash)["dsr"]
    assert (
        before.dsr_full
        == bs.deflated_sharpe(runs["full"].r_strat, 4, runs["full"].r_cash)["dsr"]
    )
    legacy = synthetic_metric(runs, bench)
    explicit = synthetic_metric(runs, bench, evidence_version="legacy")
    assert legacy.row() == explicit.row()
    assert legacy.dsr == before.dsr_full
    assert "evidence_version" not in legacy.row() and "dsr_full" not in legacy.row()
    assert before.row()["evidence_version"] == "matched-v1"
    assert before.row()["dsr_sample"] == "dev+val"
    assert before.row()["dsr_full"] == before.dsr_full
    runs["holdout"]["r_strat"] -= 0.03
    runs["full"].loc[runs["holdout"].index, "r_strat"] -= 0.03
    after = synthetic_metric(runs, bench, evidence_version="matched-v1")
    hard = lambda res: {
        k: v for k, v in res.checks.items() if not k.startswith("holdout")
    }
    assert hard(before) == hard(after)
    assert before.dsr == after.dsr
    assert before.passes == after.passes
    assert before.dsr_full != after.dsr_full
    assert legacy.dsr != synthetic_metric(runs, bench).dsr


@pytest.mark.parametrize("period", ["dev", "val"])
@pytest.mark.parametrize("problem", ["missing", "empty", "null", "nonfinite"])
def test_matched_primary_missing_period_fails_closed(
    synthetic_primary, period, problem
):
    runs, bench = synthetic_primary
    if problem == "missing":
        del runs[period]
    elif problem == "empty":
        runs[period] = runs[period].iloc[:0]
    elif problem == "null":
        runs[period] = None
    else:
        runs[period].iloc[0, 0] = np.inf
    res = synthetic_metric(runs, bench, evidence_version="matched-v1")
    assert np.isnan(res.dsr)
    assert not res.passes
    assert not res.checks[f"{period}_beats_sma200"]
    assert not res.checks[f"{period}_beats_bh"]
    assert not res.checks[f"{period}_p_le_{bs.P_MAX}"]


@pytest.mark.parametrize(
    "problem",
    ["reverse", "duplicate", "overlap", "swapped", "holdout_overlap", "holdout_before"],
)
def test_matched_primary_rejects_invalid_chronology(synthetic_primary, problem):
    runs, bench = synthetic_primary
    if problem == "reverse":
        runs["dev"] = runs["dev"].iloc[::-1]
    elif problem == "duplicate":
        runs["dev"] = pd.concat([runs["dev"].iloc[:1], runs["dev"]])
    elif problem == "overlap":
        runs["val"] = runs["full"].iloc[250:600]
    elif problem == "swapped":
        runs["dev"], runs["val"] = runs["val"], runs["dev"]
    elif problem == "holdout_overlap":
        runs["holdout"] = runs["full"].iloc[599:]
    else:
        runs["holdout"] = (
            runs["full"].iloc[:10].set_axis(pd.bdate_range("1999-01-01", periods=10))
        )
    with pytest.raises(ValueError, match="chronological|overlap"):
        synthetic_metric(runs, bench, evidence_version="matched-v1")


def test_matched_primary_does_not_require_full(synthetic_primary):
    runs, bench = synthetic_primary
    expected = synthetic_metric(runs, bench, evidence_version="matched-v1")
    del runs["full"]
    res = synthetic_metric(runs, bench, evidence_version="matched-v1")
    assert res.dsr == expected.dsr
    assert res.checks == expected.checks
    assert np.isnan(res.dsr_full)


@pytest.mark.parametrize("version", [None, "", 1, "matched-v2", "matched-v1\u200b"])
def test_stats_invalid_evidence_version(version):
    with pytest.raises(ValueError, match="evidence_version"):
        bs.primary_metric(None, None, evidence_version=version)
    with pytest.raises(ValueError, match="evidence_version"):
        bs.placebo_test(None, None, None, evidence_version=version)


def test_matched_placebo_dispatch_forwards_keywords(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []
    expected = {"corrected": True}

    def helper(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setitem(sys.modules, "bt_placebo", SimpleNamespace(placebo_test=helper))
    px, signal, cash = object(), object(), object()
    rng = np.random.default_rng(9)
    result = bs.placebo_test(
        px,
        signal,
        cash,
        17,
        9.0,
        "next_open",
        "daily",
        rng,
        "CAGR",
        evidence_version="matched-v1",
    )
    assert result is expected
    assert calls == [
        {
            "px": px,
            "signal": signal,
            "cash": cash,
            "n_placebo": 17,
            "cost_bps": 9.0,
            "execution": "next_open",
            "rebalance": "daily",
            "rng": rng,
            "stat": "CAGR",
        }
    ]


def test_placebo_legacy_default_unchanged(monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "bt_placebo",
        SimpleNamespace(
            placebo_test=lambda **kw: pytest.fail("legacy must not dispatch")
        ),
    )
    idx = pd.bdate_range("2000-01-01", periods=100)
    close = pd.Series(
        100 * np.exp(np.random.default_rng(2).normal(0, 0.01, 100).cumsum()), idx
    )
    px = pd.DataFrame({"close": close, "tr_close": close})
    cash = pd.Series(0.0001, idx)
    signal = pd.Series(np.tile([0.0, 1.0], 50), idx)
    default = bs.placebo_test(px, signal, cash, n_placebo=3)
    explicit = bs.placebo_test(px, signal, cash, n_placebo=3, evidence_version="legacy")
    assert default == explicit
