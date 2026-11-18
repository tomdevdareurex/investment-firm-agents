"""Offline tests for the S07b quarterly YoY events in fundamentals/edgar_data.py (synthetic facts)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fundamentals"))
import edgar_data as ed  # noqa: E402

K_FILED = "2017-02-20"


def _fact(start, end, val, form, filed, accn, cik=1):
    return {
        "cik": cik,
        "start": pd.Timestamp(start),
        "end": pd.Timestamp(end),
        "val": float(val),
        "form": form,
        "filed": pd.Timestamp(filed),
        "accn": accn,
    }


def _facts(rows):
    df = pd.DataFrame(rows)
    df["days"] = (df["end"] - df["start"]).dt.days
    return df


def _q3(filed="2016-11-01", accn="q3-16"):
    return [
        _fact("2016-07-01", "2016-09-30", 30, "10-Q", filed, accn),
        _fact("2015-07-01", "2015-09-30", 20, "10-Q", filed, accn),
        _fact("2016-01-01", "2016-09-30", 90, "10-Q", filed, accn),
        _fact("2015-01-01", "2015-09-30", 60, "10-Q", filed, accn),
    ]


def _tenk(tag_q4: bool):
    rows = [
        _fact("2016-01-01", "2016-12-31", 130, "10-K", K_FILED, "k-16"),
        _fact("2015-01-01", "2015-12-31", 100, "10-K", K_FILED, "k-16"),
    ]
    if tag_q4:  # deliberately != derived (40 / 40) to see which one is used
        rows += [
            _fact("2016-10-01", "2016-12-31", 41, "10-K", K_FILED, "k-16"),
            _fact("2015-10-01", "2015-12-31", 39, "10-K", K_FILED, "k-16"),
        ]
    return rows


def _q4_row(ev):
    rows = ev[ev["form"] == "10-K"]
    assert len(rows) <= 1
    return None if rows.empty else rows.iloc[0]


def test_reported_q4_is_used_when_tagged():
    ev = ed.quarterly_yoy_events(_facts(_q3() + _tenk(tag_q4=True)))
    r = _q4_row(ev)
    assert r["basis"] == "q4_reported"
    assert (r["ni"], r["ni_prior"]) == (41.0, 39.0)
    assert r["period_end"] == pd.Timestamp("2016-12-31")
    assert r.name == pd.Timestamp(K_FILED) + pd.Timedelta(days=1)


def test_q4_derived_as_fy_minus_nine_months_when_not_tagged():
    r = _q4_row(ed.quarterly_yoy_events(_facts(_q3() + _tenk(tag_q4=False))))
    assert r["basis"] == "q4_derived"
    assert (r["ni"], r["ni_prior"]) == (130.0 - 90.0, 100.0 - 60.0)


def test_no_q4_event_without_tag_or_q3_filing():
    assert _q4_row(ed.quarterly_yoy_events(_facts(_tenk(tag_q4=False)))) is None


def test_q3_filed_after_the_10k_is_not_used():
    late = _q3(filed="2017-03-01")
    assert _q4_row(ed.quarterly_yoy_events(_facts(late + _tenk(tag_q4=False)))) is None


def test_latest_q3_amendment_before_the_10k_wins():
    amended = [
        _fact("2016-01-01", "2016-09-30", 95, "10-Q/A", "2016-12-01", "q3a-16"),
        _fact("2015-01-01", "2015-09-30", 62, "10-Q/A", "2016-12-01", "q3a-16"),
    ]
    r = _q4_row(ed.quarterly_yoy_events(_facts(_q3() + amended + _tenk(False))))
    assert (r["ni"], r["ni_prior"]) == (35.0, 38.0)


def test_10q_events_identical_to_yoy_events():
    facts = _facts(_q3() + _tenk(tag_q4=True))
    new = ed.quarterly_yoy_events(facts)
    old = ed.yoy_events(facts)
    a = old[old["form"].str.startswith("10-Q")]
    b = new[new["basis"] == "quarter"].drop(columns="basis")
    pd.testing.assert_frame_equal(a, b[a.columns])
    assert (b["ni"].iloc[0], b["ni_prior"].iloc[0]) == (30.0, 20.0)


def test_validate_q4_flags_mismatch():
    v = ed.validate_q4(_facts(_q3() + _tenk(tag_q4=True)))
    assert len(v) == 1
    assert v["match"].iloc[0]  # |41 - 40| is below the $1m floor
    big = [dict(r, val=r["val"] * 1e9) for r in _q3() + _tenk(tag_q4=True)]
    vb = ed.validate_q4(_facts(big))
    assert not vb["match_cur"].iloc[0] and not vb["match_prior"].iloc[0]
    assert vb["same_direction"].iloc[0] == (np.sign(41 - 39) == np.sign(40 - 40))


def test_add_acceleration_uses_previous_quarter_available_earlier():
    ev = pd.DataFrame(
        {
            "cik": [1, 1, 1, 1],
            "filed": pd.to_datetime(
                ["2016-05-01", "2016-08-01", "2016-11-01", "2016-11-01"]
            ),
            "period_end": pd.to_datetime(
                ["2016-03-31", "2016-06-30", "2016-09-30", "2016-06-30"]
            ),
            "form": ["10-Q", "10-Q", "10-Q", "10-Q/A"],
            "ni": [10.0, 30.0, 25.0, 31.0],
            "ni_prior": [5.0, 10.0, 15.0, 10.0],
        },
        index=pd.to_datetime(
            ["2016-05-02", "2016-08-02", "2016-11-02", "2016-11-02"]
        ).rename("avail"),
    )
    acc = ed.add_acceleration(ev)["accel"].tolist()
    assert np.isnan(acc[0])  # no previous quarter
    assert acc[1] == 1.0  # change 20 > 5
    assert acc[2] == 0.0  # change 10 < 20 (Q2 event available earlier)
    assert acc[3] == 1.0  # amended Q2 (change 21) vs Q1 (5); same-day Q3 not used
