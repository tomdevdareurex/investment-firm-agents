import numpy as np
import pandas as pd
import pytest

import bt_common as bc
import bt_long as bl
import bt_pit as bp


@pytest.fixture(scope="module")
def sample():
    return bl.long_sample()


def _daily_index():
    return pd.bdate_range("2000-01-03", "2001-12-31")


def test_monthly_to_daily_pit_lag_zero():
    idx = _daily_index()
    m = pd.Series(
        [1.0, 2.0, 3.0], pd.to_datetime(["2000-01-31", "2000-02-29", "2000-03-31"])
    )
    d = bp.monthly_to_daily_pit(m, idx)
    assert np.isnan(d.loc["2000-01-31"])  # Jan value not yet known in Jan
    assert d.loc["2000-02-01"] == 1.0  # known first trading day of Feb
    assert d.loc["2000-02-29"] == 1.0
    assert d.loc["2000-03-01"] == 2.0
    assert d.loc["2001-12-31"] == 3.0  # ffilled


def test_monthly_to_daily_pit_extra_lag():
    idx = _daily_index()
    m = pd.Series([1.0, 2.0], pd.to_datetime(["2000-01-31", "2000-02-29"]))
    d = bp.monthly_to_daily_pit(m, idx, months=1)  # one extra month
    assert np.isnan(d.loc["2000-02-29"])
    assert d.loc["2000-03-01"] == 1.0
    d7 = bp.monthly_to_daily_pit(m, idx, days=7)  # ~first Friday
    assert np.isnan(d7.loc["2000-02-07"])
    assert d7.loc["2000-02-08"] == 1.0


def test_daily_pit_shift():
    idx = _daily_index()
    s = pd.Series(np.arange(len(idx), dtype=float), idx)
    d = bp.daily_pit(s, idx, days=1)
    assert np.isnan(d.iloc[0]) and d.iloc[1] == 0.0 and d.iloc[-1] == len(idx) - 2
    # sparse source (weekly) is ffilled before shifting
    wk = s[::5]
    dw = bp.daily_pit(wk, idx, days=1)
    assert dw.iloc[2] == 0.0 and dw.iloc[6] == 5.0


def test_pit_align_dispatch_by_key():
    idx = _daily_index()
    m = pd.Series([1.0, 2.0], pd.to_datetime(["2000-01-31", "2000-02-29"]))
    cape = bp.pit_align(m, idx, "SHILLER_CAPE")
    assert np.isnan(cape.loc["2000-02-29"]) and cape.loc["2000-03-01"] == 1.0
    daily = pd.Series(np.arange(len(idx), dtype=float), idx)
    vix = bp.pit_align(daily, idx, "VIX")
    assert vix.iloc[1] == 0.0
    with pytest.raises(KeyError):
        bp.pit_align(daily, idx, "UNKNOWN")
    assert bp.pit_align(daily, idx, days=2).iloc[2] == 0.0


def test_lookahead_on_sma_peeking_helps(sample):
    px, cash = sample["px"], sample["cash"]
    px = px.loc["1990":]
    signal, _ = bc.sma_signal(px["close"], 200)
    res = bp.lookahead_test(px, signal, cash, shifts=(-21, 0, 5))
    assert list(res.sharpe_by_shift.index) == [-21, 0, 5]
    # peeking a month ahead must be much better, delaying worse
    assert res.sharpe_by_shift[-21] > res.sharpe_by_shift[0] + 0.3
    assert res.sharpe_by_shift[5] < res.sharpe_by_shift[-21]
    assert not res.suspicious
    assert res.to_frame().shape == (3, 1)


def test_lookahead_flags_leaking_signal(sample):
    px, cash = sample["px"], sample["cash"]
    px = px.loc["1990":]
    # next_close trades one bar after the signal, so r[t+2] is the leaked return
    fwd = px["close"].pct_change().shift(-2)
    leak = (fwd > 0).astype(float)
    res = bp.lookahead_test(px, leak, cash, shifts=(-21, 0), rebalance="daily")
    assert res.sharpe_by_shift[0] > 3  # absurdly good = leak
    assert res.suspicious  # peeking further cannot improve on it


def test_assert_no_future_dates():
    idx = _daily_index()
    m = pd.Series([1.0, 2.0], pd.to_datetime(["2000-01-31", "2000-02-29"]))
    good = bp.pit_align(m, idx, "SHILLER_CAPE")
    bp.assert_no_future_dates(good, m, "SHILLER_CAPE")
    bad = m.reindex(idx, method="bfill")
    with pytest.raises(AssertionError):
        bp.assert_no_future_dates(bad, m, "SHILLER_CAPE")
