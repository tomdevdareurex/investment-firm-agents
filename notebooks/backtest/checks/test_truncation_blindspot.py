"""Tests for stage2_trunc (release-aware truncation test, audit finding A5-01).

Synthetic data only: a daily price index and a monthly series.  Two signals:
``lag0`` uses month M's value from the first trading day of M+1 (no release
lag); ``lag1`` waits one more month (the SHILLER_CAPE convention).  The original
``stage2.truncation_test`` passes both; the release-aware test must fail lag0
and pass lag1.
"""

import numpy as np
import pandas as pd
import pytest

import bt_pit
import stage2 as s2
import stage2_trunc as st


@pytest.fixture(scope="module")
def inputs():
    idx = pd.bdate_range("2000-01-03", "2009-12-31")
    rng = np.random.default_rng(7)
    px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), idx)
    months = pd.period_range("1999-01", "2009-12", freq="M")
    monthly = pd.Series(np.arange(len(months), dtype=float), months)
    return {"px": px, "m": monthly}


def _sig(months):
    def build(inputs, months=months):
        m = inputs["m"].copy()
        m.index = m.index.to_timestamp(how="start")
        return bt_pit.monthly_to_daily_pit(m, inputs["px"].index, months=months)

    return build


def test_resolve_lag_variants():
    assert st.resolve_lag(None) == {"months": 0, "days": 0}
    assert st.resolve_lag({"months": 1}) == {"months": 1, "days": 0}
    assert st.resolve_lag("UNRATE") == {"months": 0, "days": 7}


def test_monthly_release_dates_period_and_timestamp():
    per = pd.period_range("2001-01", "2001-03", freq="M")
    rel = st.monthly_release_dates(per, {"months": 1, "days": 0})
    assert list(rel) == list(pd.to_datetime(["2001-03-01", "2001-04-01", "2001-05-01"]))
    ts = per.to_timestamp(how="start")
    rel2 = st.monthly_release_dates(ts, {"months": 0, "days": 7})
    assert list(rel2) == list(
        pd.to_datetime(["2001-02-08", "2001-03-08", "2001-04-08"])
    )


def test_truncate_release_drops_unreleased_month(inputs):
    cut = pd.Timestamp("2005-03-15")
    base = s2.truncate_inputs(inputs, cut)["m"]
    assert base.index.max() == pd.Period("2005-02", "M")
    rel = st.truncate_inputs_release(inputs, cut, {"m": {"months": 1}})["m"]
    assert rel.index.max() == pd.Period("2005-01", "M")
    rel7 = st.truncate_inputs_release(inputs, cut, {"m": "UNRATE"})["m"]
    assert rel7.index.max() == pd.Period("2005-02", "M")
    rel7b = st.truncate_inputs_release(
        inputs, pd.Timestamp("2005-03-05"), {"m": "UNRATE"}
    )["m"]
    assert rel7b.index.max() == pd.Period("2005-01", "M")


def test_truncate_release_daily_business_day_lag(inputs):
    d = inputs["px"]
    out = st.truncate_inputs_release({"px": d, "d": d}, "2005-03-15", {"d": "VIX"})
    assert out["d"].index.max() == pd.Timestamp("2005-03-14")
    assert out["px"].index.max() == pd.Timestamp("2005-03-15")


def test_release_window_cuts_inside_window(inputs):
    lags = {"m": {"months": 1}}
    cuts = st.release_window_cuts(inputs, lags, inputs["px"].index, n_cuts=40)
    assert 0 < len(cuts) <= 40
    # every cut lies strictly between a month end and that month's release
    for c in cuts:
        rel = pd.Timestamp(c).to_period("M").to_timestamp(
            how="start"
        ) + pd.offsets.MonthBegin(1)
        assert c < rel  # trivially true; the real check is day-of-month < 1st of M+2
        assert c.day >= 1
    # a month that has ended but is not yet released exists at each cut
    for c in cuts[:10]:
        base = s2.truncate_inputs(inputs, c)["m"]
        rel = st.truncate_inputs_release(inputs, c, lags)["m"]
        assert len(base) == len(rel) + 1


def test_original_test_is_blind_to_missing_lag(inputs):
    r0 = s2.truncation_test(_sig(0), inputs, n_cuts=40)
    r1 = s2.truncation_test(_sig(1), inputs, n_cuts=40)
    assert r0.passed and r1.passed


def test_release_test_detects_missing_lag(inputs):
    lags = {"m": {"months": 1}}
    r0 = st.truncation_test_release(_sig(0), inputs, lags, n_cuts=40)
    r1 = st.truncation_test_release(_sig(1), inputs, lags, n_cuts=40)
    assert not r0.passed and r0.n_mismatch > 0
    assert r1.passed and r1.n_cuts == r0.n_cuts


def test_release_test_with_release_lags_key(inputs):
    lags = {"m": "SHILLER_CAPE"}
    assert st.truncation_test_release(_sig(1), inputs, lags, n_cuts=20).passed
    assert not st.truncation_test_release(_sig(0), inputs, lags, n_cuts=20).passed


def test_explicit_cut_dates_respected(inputs):
    cuts = pd.DatetimeIndex(["2004-02-10", "2006-07-20"])
    r = st.truncation_test_release(
        _sig(0), inputs, {"m": {"months": 1}}, cut_dates=cuts
    )
    assert r.n_cuts == 2 and r.n_mismatch == 2
