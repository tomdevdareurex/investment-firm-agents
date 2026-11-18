"""Offline tests for stage2.py (synthetic data only)."""

import numpy as np
import pandas as pd
import pytest

import bt_pit
import stage2 as s2


@pytest.fixture(scope="module")
def inputs():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("1990-01-01", "2005-12-31")
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))), idx)
    px = pd.DataFrame({"close": close, "tr_close": close})
    months = pd.period_range("1989-01", "2005-12", freq="M")
    macro = pd.Series(
        rng.normal(0, 1, len(months)).cumsum(), index=months, name="macro"
    )
    fred = pd.Series(
        macro.to_numpy(), index=months.to_timestamp(how="start"), name="fred"
    )
    return {"px": px, "macro": macro, "fred": fred}


def honest(inp, window=12):
    m = inp["macro"]
    sig = (
        (m > m.rolling(window).mean())
        .astype(float)
        .where(m.rolling(window).mean().notna())
    )
    sig.index = sig.index.to_timestamp(how="start")
    return bt_pit.monthly_to_daily_pit(sig, inp["px"].index, months=0, days=7)


def honest_daily(inp):
    c = inp["px"]["close"]
    return (
        (c > c.rolling(200).mean()).astype(float).where(c.rolling(200).mean().notna())
    )


def leaky_full_median(inp):
    m = inp["macro"]
    sig = (m > m.median()).astype(float)
    sig.index = sig.index.to_timestamp(how="start")
    return bt_pit.monthly_to_daily_pit(sig, inp["px"].index, months=0, days=7)


def leaky_centred(inp):
    c = inp["px"]["close"]
    ma = c.rolling(41, center=True).mean()
    return (c > ma).astype(float).where(ma.notna())


def leaky_no_lag(inp):
    f = inp[
        "fred"
    ]  # month-start dated monthly average, used from the 1st of the same month
    sig = (f > f.rolling(12).mean()).astype(float).where(f.rolling(12).mean().notna())
    return (
        sig.reindex(sig.index.union(inp["px"].index)).ffill().reindex(inp["px"].index)
    )


def test_honest_signals_pass(inputs):
    assert s2.truncation_test(honest, inputs, n_cuts=25).passed
    assert s2.truncation_test(honest_daily, inputs, n_cuts=25).passed
    assert s2.truncation_test(honest, inputs, n_cuts=10, window=6).passed


@pytest.mark.parametrize("fn", [leaky_full_median, leaky_centred, leaky_no_lag])
def test_leaky_signals_fail(inputs, fn):
    res = s2.truncation_test(fn, inputs, n_cuts=40)
    assert not res.passed and res.n_mismatch > 0


def test_truncate_inputs_monthly_keeps_completed_months_only(inputs):
    cut = pd.Timestamp("2000-03-15")
    t = s2.truncate_inputs(inputs, cut)
    assert t["macro"].index[-1] == pd.Period("2000-02", "M")
    assert t["fred"].index[-1] == pd.Timestamp("2000-02-01")
    assert t["px"].index[-1] <= cut
    t2 = s2.truncate_inputs(inputs, pd.Timestamp("2000-03-31"))
    assert t2["macro"].index[-1] == pd.Period("2000-03", "M")


def test_late_protocol_periods(inputs):
    px = inputs["px"]
    cash = pd.Series(0.0001, index=px.index)
    sig = honest_daily(inputs)
    runs = s2.run_protocol(px, sig, cash, protocol="late")
    assert set(runs) == {"dev", "full"}  # synthetic data ends 2005: no val/holdout
    assert runs["dev"].index[-1] <= pd.Timestamp("2013-12-31")
    with pytest.raises(ValueError):
        s2.run_protocol(px, sig, cash, protocol="other")


@pytest.fixture
def sweep_data(monkeypatch):
    # Real execution paths, including forced initial entry and later trading costs.
    idx = pd.bdate_range("2000-01-03", periods=180)
    rng = np.random.default_rng(21)
    close = pd.Series(100 * np.exp(rng.normal(0.001, 0.01, len(idx)).cumsum()), idx)
    px = pd.DataFrame({"close": close, "tr_close": close})
    cash = pd.Series(0.0001, idx)
    early = pd.Series(1.0, idx)
    early.iloc[80:100] = 0.0
    late = early.copy()
    late.iloc[:30] = np.nan
    bench = pd.DataFrame(
        {"sma200": close.pct_change(), "bh": close.pct_change(), "tbill": cash}
    )
    signals = {"early": early, "late": late}
    calls = []
    monkeypatch.setattr(s2.br, "append_trials", lambda rows: calls.extend(rows))
    return px, cash, bench, signals, calls


def sweep(data, **kwargs):
    px, cash, bench, signals, _ = data
    return s2.dev_sweep(
        px,
        cash,
        bench,
        signals,
        {k: k for k in signals},
        trial_id="synthetic",
        strategy="test",
        notebook="none",
        protocol="late",
        rebalance="daily",
        **kwargs,
    )


def test_matched_sweep_identical_overlap_ties_and_keeps_internal_costs(sweep_data):
    px, cash, bench, signals, calls = sweep_data
    tab, winner = sweep(sweep_data, evidence_version="matched-v1")
    runs = {
        k: s2.run_protocol(px, sig, cash, "late", "daily")["dev"]
        for k, sig in signals.items()
    }
    boundary = max(df.index[0] for df in runs.values())
    common = runs["late"].index[runs["late"].index > boundary]
    expected = runs["early"].loc[common]
    score = s2.bs.excess_sharpe(expected.r_strat, expected.r_cash)
    assert tab.dev_sharpe.astype(float).tolist() == pytest.approx([score, score])
    assert tab.d_sma200.astype(float).nunique() == 1
    assert tab.d_bh.astype(float).nunique() == 1
    assert tab.dev_start.tolist() == [common[0].date()] * 2
    assert tab.dev_end.tolist() == [common[-1].date()] * 2
    assert tab.dev_n.tolist() == [len(common)] * 2
    assert winner == "early"
    assert expected.cost.sum() > 0
    assert score != s2.bs.excess_sharpe(expected.r_gross, expected.r_cash)
    assert len(calls) == 2
    for row in calls:
        assert "matched-v1" in row["note"]
        assert str(common[0].date()) in row["note"]
        assert str(common[-1].date()) in row["note"]
        assert str(len(common)) in row["note"]
    legacy, _ = sweep(sweep_data, register=False)
    explicit, _ = sweep(sweep_data, register=False, evidence_version="legacy")
    pd.testing.assert_frame_equal(legacy, explicit)
    assert legacy.dev_sharpe.iloc[0] != legacy.dev_sharpe.iloc[1]
    assert "dev_end" not in legacy and "dev_n" not in legacy


def test_matched_sweep_intersects_every_finite_return(sweep_data, monkeypatch):
    px, cash, bench, signals, _ = sweep_data
    paths = {
        k: s2.run_protocol(px, sig, cash, "late", "daily") for k, sig in signals.items()
    }
    bad = px.index[[45, 50, 55, 60, 65]]
    paths["early"]["dev"].loc[bad[0], "r_strat"] = np.inf
    paths["late"]["dev"].loc[bad[1], "r_cash"] = np.nan
    for date, col in zip(bad[2:], ["sma200", "bh", "tbill"]):
        bench.loc[date, col] = np.nan
    monkeypatch.setattr(
        s2,
        "run_protocol",
        lambda px, sig, *a: paths[next(k for k, v in signals.items() if v is sig)],
    )
    tab, _ = sweep(sweep_data, evidence_version="matched-v1", register=False)
    common = paths["late"]["dev"].index[1:].difference(bad)
    for name in signals:
        dev = paths[name]["dev"].loc[common]
        assert tab.loc[name, "dev_n"] == len(common)
        assert tab.loc[name, "dev_sharpe"] == pytest.approx(
            s2.bs.excess_sharpe(dev.r_strat, dev.r_cash)
        )
        assert tab.loc[name, "d_bh"] == pytest.approx(
            tab.loc[name, "dev_sharpe"]
            - s2.bs.excess_sharpe(bench.loc[common, "bh"], bench.loc[common, "tbill"])
        )


@pytest.mark.parametrize(
    "problem", ["missing", "empty", "short", "nonfinite", "no_signals"]
)
def test_matched_sweep_rejects_before_registration(sweep_data, monkeypatch, problem):
    px, cash, bench, signals, calls = sweep_data
    if problem == "missing":
        monkeypatch.setattr(s2, "run_protocol", lambda *a: {})
    elif problem == "empty":
        bench.loc[:, :] = np.nan
    elif problem == "short":
        bench.iloc[60:] = np.nan
    elif problem == "nonfinite":
        # First variant is valid: partial successful scoring must not write.
        signals["late"].loc[:] = 0.0  # zero excess volatility => undefined Sharpe
    else:
        signals.clear()
    with pytest.raises(ValueError):
        sweep(sweep_data, evidence_version="matched-v1")
    assert calls == []


def test_matched_sweep_minimum_sixty_rows(sweep_data):
    px, cash, bench, signals, _ = sweep_data
    first = s2.run_protocol(px, signals["late"], cash, "late", "daily")["dev"].index[0]
    valid = bench.index[bench.index > first][:60]
    bench.loc[~bench.index.isin(valid), :] = np.nan
    tab, _ = sweep(sweep_data, evidence_version="matched-v1", register=False)
    assert tab.dev_n.tolist() == [60, 60]


@pytest.mark.parametrize("version", [None, "", "MATCHED-V1", 1, "matched-v1\u200b"])
def test_stage2_invalid_version_fails_before_work(sweep_data, monkeypatch, version):
    monkeypatch.setattr(
        s2, "run_protocol", lambda *a: pytest.fail("must validate first")
    )
    with pytest.raises(ValueError, match="evidence_version"):
        sweep(sweep_data, evidence_version=version)
    with pytest.raises(ValueError, match="evidence_version"):
        s2.evaluate(None, None, None, None, evidence_version=version)


def test_evaluate_forwards_version_and_evidence_labels(monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(s2, "run_protocol", lambda *a: {})
    monkeypatch.setattr(s2.bp, "compare_to_benchmarks", lambda *a: "compare")
    monkeypatch.setattr(s2.bp, "period_table", lambda *a: "stats")

    def primary(*args, **kwargs):
        calls.append(kwargs)
        return s2.bs.PrimaryResult(
            n_trials=kwargs["n_trials"], evidence_version=kwargs["evidence_version"]
        )

    monkeypatch.setattr(s2.bs, "primary_metric", primary)
    _, _, _, res = s2.evaluate(
        None, None, None, None, n_trials=3, evidence_version="matched-v1"
    )
    assert calls[0]["evidence_version"] == "matched-v1"
    placebo = {"real": 1.0, "placebo_q95": 0.0, "p_one_sided": 0.01}

    def lines(result):
        return s2.evidence_lines(
            result,
            s2.TruncResult(3, 0, 0.0),
            SimpleNamespace(peek_gain=0.0),
            placebo,
            50.0,
        )

    assert any("matched-v1" in line and "dev+val" in line for line in lines(res))
    legacy = lines(s2.bs.PrimaryResult())
    assert "Deflated Sharpe nan with n_trials=1." in legacy
    assert not any("matched-v1" in line or "dev+val" in line for line in legacy)


@pytest.mark.parametrize("version", ["legacy", "matched-v1"])
def test_register_final_version_note_without_registry_writes(monkeypatch, version):
    notes = []
    registry = pd.DataFrame({"trial_id": ["synthetic", "other"]})
    monkeypatch.setattr(s2.br, "load_registry", lambda: registry.copy())
    monkeypatch.setattr(pd.DataFrame, "to_csv", lambda *a, **kw: None)
    monkeypatch.setattr(s2.br, "append_trials", lambda rows: None)
    monkeypatch.setattr(s2.br, "render_registry", lambda **kw: None)

    def rows(*args, note):
        notes.append(note)
        return []

    monkeypatch.setattr(s2.br, "rows_from_primary", rows)
    res = s2.bs.PrimaryResult(evidence_version=version)
    s2.register_final("synthetic", "test", "none", "fixed", res, note="original")
    if version == "legacy":
        assert notes == ["original"]
    else:
        assert notes[0].startswith("original")
        assert "evidence_version=matched-v1" in notes[0]
        assert "dev+val" in notes[0]
