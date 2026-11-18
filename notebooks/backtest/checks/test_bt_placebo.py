"""Synthetic checks for the opt-in, matched-sample placebo evaluation."""

import numpy as np
import pandas as pd
import pytest

import bt_common as bc
import bt_stats as bs
from bt_placebo import placebo_test


@pytest.fixture
def late_sample():
    idx = pd.bdate_range("2000-01-03", "2015-12-31")
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx))))
    px = pd.DataFrame(
        {"close": close, "tr_close": close, "tr_open": close * 1.001}, index=idx
    )
    signal = pd.Series(np.nan, index=idx)
    eligible = idx[idx >= "2011-02-15"]
    signal.loc[eligible] = (np.arange(len(eligible)) // 60) % 2
    signal.loc["2012-03-01":"2012-04-10"] = np.nan
    cash = pd.Series(0.00005, index=idx)
    cash.loc["2013-04-03":"2013-04-05"] = np.nan
    return px, signal, cash


@pytest.mark.parametrize("execution", ["next_close", "same_close", "next_open"])
@pytest.mark.parametrize("rebalance", ["monthly", "daily"])
def test_placebo_matches_executed_dates_and_exposure(
    late_sample, monkeypatch, execution, rebalance
):
    px, signal, cash = late_sample
    frames = []
    original = bc.backtest_signal

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        frames.append(result)
        return result

    monkeypatch.setattr(bc, "backtest_signal", capture)
    result = placebo_test(
        px, signal, cash, n_placebo=8, execution=execution, rebalance=rebalance
    )
    real = frames[0]
    assert len(frames) == 9
    assert all(fake.index.equals(real.index) for fake in frames[1:])
    assert result["time_in_market"] == pytest.approx(real["pos"].mean())
    assert result["n_observations"] == len(real)
    assert result["sample_start"] == real.index[0].isoformat()
    assert result["sample_end"] == real.index[-1].isoformat()
    assert result["real"] == pytest.approx(
        bc.perf_stats(real["r_strat"], real["r_cash"])["Sharpe"]
    )
    assert result["n_placebo"] + result["n_degenerate"] == 8


def test_irrelevant_price_prehistory_cannot_change_placebo(late_sample):
    px, signal, cash = late_sample
    short = px.loc["2010":]
    full_result = placebo_test(px, signal, cash, n_placebo=12)
    short_result = placebo_test(short, signal, cash, n_placebo=12)
    assert full_result.keys() == short_result.keys()
    for key in full_result:
        if isinstance(full_result[key], float):
            assert full_result[key] == pytest.approx(short_result[key], nan_ok=True)
        else:
            assert full_result[key] == short_result[key]


def test_corrected_mode_dispatches_without_changing_legacy_default(late_sample):
    px, signal, cash = late_sample
    expected = placebo_test(px, signal, cash, n_placebo=5)
    assert (
        bs.placebo_test(px, signal, cash, n_placebo=5, evidence_version="matched-v1")
        == expected
    )
    legacy = bs.placebo_test(px, signal, cash, n_placebo=5)
    assert "evidence_version" not in legacy
    assert legacy["time_in_market"] < expected["time_in_market"] / 2


def test_missing_signal_and_insufficient_executed_history_fail(late_sample):
    px, signal, cash = late_sample
    with pytest.raises(ValueError, match="signal"):
        placebo_test(px, signal * np.nan, cash, n_placebo=3)
    with pytest.raises(ValueError, match="observations"):
        placebo_test(px, signal, cash * np.nan, n_placebo=3)
    with pytest.raises(ValueError, match="n_placebo"):
        placebo_test(px, signal, cash, n_placebo=0)


def test_all_degenerate_placebos_report_unavailable_inference(late_sample, monkeypatch):
    px, signal, cash = late_sample
    calls = 0

    def fake_stats(ret, rf):
        nonlocal calls
        calls += 1
        return {"Sharpe": 0.5 if calls == 1 else np.nan}

    monkeypatch.setattr(bc, "perf_stats", fake_stats)
    result = placebo_test(px, signal, cash, n_placebo=3)
    assert result["n_placebo"] == 0
    assert result["n_degenerate"] == 3
    assert np.isnan(result["p_one_sided"])
    assert np.isnan(result["placebo_q95"])
