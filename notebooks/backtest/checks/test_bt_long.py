"""Checks for bt_long: long-history loaders reproduce the sma200 notebook figures.

Uses the on-disk cache (.cache/notebooks); network only if the cache is missing.
"""

import numpy as np
import pandas as pd
import pytest

import bt_common as bc
import bt_long as bl


@pytest.fixture(scope="module")
def shiller():
    return bl.load_shiller()


@pytest.fixture(scope="module")
def sample():
    return bl.long_sample("1934-01-01")


def test_shiller_period_index():
    idx = bl.shiller_period_index(pd.Series([1871.01, 1871.1, 2024.12]))
    assert list(idx.astype(str)) == ["1871-01", "1871-10", "2024-12"]


def test_shiller_columns_and_range(shiller):
    assert {"P", "D", "E", "CPI", "GS10", "CAPE"} <= set(shiller.columns)
    assert shiller.index[0] == pd.Period("1871-01", "M")
    assert shiller.index.is_monotonic_increasing and shiller.index.is_unique
    assert shiller["CAPE"].dropna().index[0] == pd.Period("1881-01", "M")
    assert shiller.loc["2000-01", "CAPE"] > 40  # dot-com peak


def test_fred_tb3ms_starts_1934():
    s = bl.fred_series("TB3MS")
    assert s.index[0] == pd.Timestamp("1934-01-01")
    assert s.between(0, 20).all()


def test_long_sp500_tr_splice_and_tracking(sample):
    px = sample["px"]
    assert px.index[0] >= pd.Timestamp("1934-01-01")
    assert px.attrs["splice_date"].year == 1988
    assert np.isfinite(px["tr_close"]).all() and (px["tr_close"] > 0).all()
    # Synthetic TR (price + Shiller dividends) vs official ^SP500TR, 1989-2023.
    gspc = bc.load_history("^GSPC")["Close"]
    sptr = bc.load_history("^SP500TR")["Close"]
    d = bl.load_shiller()["D"].reindex(gspc.index.to_period("M")).ffill().to_numpy()
    r_syn = ((gspc + d / 252) / gspc.shift(1) - 1).loc["1989":"2023"]
    r_off = sptr.pct_change(fill_method=None).reindex(r_syn.index)
    a_syn = (1 + r_syn).groupby(r_syn.index.year).prod() - 1
    a_off = (1 + r_off).groupby(r_off.index.year).prod() - 1
    diff = a_syn - a_off
    assert abs(diff.mean()) < 0.0015
    assert diff.std() < 0.0025
    assert diff.abs().max() < 0.006


def test_long_tbill_yield_splices_irx(sample):
    yld = sample["yld"]
    assert yld.index[0] == pd.Timestamp("1934-02-01")
    assert yld.index.is_unique and yld.index.is_monotonic_increasing
    irx0 = bc.load_history("^IRX").index[0]
    # monthly before ^IRX, daily afterwards
    assert (yld.index < irx0).sum() < 700
    assert (yld.index >= irx0).sum() > 5000


def test_long_cash_returns_match_sma200_notebook(sample):
    cash = sample["cash"]
    assert cash.index.equals(sample["px"].index)
    assert cash.iloc[1:].between(-0.0001, 0.004).all()
    # 1981 (yields ~14 %) must compound to roughly the yield
    y1981 = (1 + cash.loc["1981"]).prod() - 1
    assert 0.12 < y1981 < 0.16


def test_sma200_long_reproduces_reference(sample):
    """Reference (sma200 notebook, data to 2026-10-16, monthly, next_close, 5 bp):
    B&H CAGR 11.04 % Sharpe 0.51 MaxDD -55.25 %; SMA200 CAGR 10.60 % Sharpe 0.64
    MaxDD -32.96 %, 139 switches, 68.97 % in equities."""
    px, cash = sample["px"], sample["cash"]
    bt = bc.sma_backtest(
        px, cash, window=200, cost_bps=5, execution="next_close", rebalance="monthly"
    )
    st = bc.perf_stats(bt["r_strat"], bt["r_cash"])
    ss = bc.strategy_stats(bt)
    bh = bc.perf_stats(bt["r_bh"], bt["r_cash"])
    assert abs(st["Sharpe"] - 0.64) < 0.03
    assert abs(st["CAGR"] - 0.1060) < 0.004
    assert abs(st["Max DD"] - (-0.3296)) < 0.01
    assert abs(bh["Sharpe"] - 0.51) < 0.03
    assert abs(bh["Max DD"] - (-0.5525)) < 0.005
    assert 130 <= ss["Switches"] <= 150 and 0.65 < ss["Time in market"] < 0.72


def test_shiller_to_daily_is_lagged(sample):
    cape = sample["shiller"]["CAPE"]
    idx = sample["px"].index
    daily = bl.shiller_to_daily(cape, idx, lag_months=0)
    assert daily.index.equals(idx)
    # Jan-2000 CAPE becomes known on 2000-02-01 (first trading day on/after).
    jan = cape.loc[pd.Period("2000-01", "M")]
    first_feb = idx[idx >= "2000-02-01"][0]
    assert daily.loc[first_feb] == pytest.approx(jan)
    assert daily.loc[idx[idx < "2000-02-01"][-1]] != pytest.approx(jan)
    lagged = bl.shiller_to_daily(cape, idx, lag_months=1)
    first_mar = idx[idx >= "2000-03-01"][0]
    assert lagged.loc[first_mar] == pytest.approx(jan)
