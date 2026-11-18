"""Tests for bt_registry."""

from __future__ import annotations

import pytest

import bt_registry as br


def _row(tid="t1/dev", **kw):
    base = {
        "trial_id": tid,
        "strategy": "cape_excess_yield",
        "notebook": "valuation/cape_excess_yield.ipynb",
        "params": "thr=2.0",
        "period": "dev",
        "sharpe": 0.71234,
        "d_sma200": 0.05,
        "d_bh": 0.2,
        "p_vs_sma200": 0.08,
        "dsr": None,
        "n_trials": 3,
        "passes": True,
        "status": "run",
        "note": "first | pass",
    }
    base.update(kw)
    return base


def test_empty_registry(tmp_path):
    p = tmp_path / "r.csv"
    df = br.load_registry(p)
    assert list(df.columns) == br.COLUMNS and df.empty
    assert br.trial_count(p) == 0


def test_append_and_reload(tmp_path):
    p = tmp_path / "r.csv"
    br.append_trial(_row(), p)
    df = br.load_registry(p)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["sharpe"] == "0.7123" and r["dsr"] == "" and r["passes"] == "True"
    assert r["n_trials"] == "3" and r["date"]


def test_replace_same_trial_id(tmp_path):
    p = tmp_path / "r.csv"
    br.append_trial(_row(sharpe=0.1), p)
    br.append_trial(_row(sharpe=0.9), p)
    df = br.load_registry(p)
    assert len(df) == 1 and df.iloc[0]["sharpe"] == "0.9000"
    with pytest.raises(ValueError):
        br.append_trial(_row(), p, replace=False)


def test_validation(tmp_path):
    p = tmp_path / "r.csv"
    with pytest.raises(ValueError):
        br.append_trial(_row(tid=""), p)
    with pytest.raises(ValueError):
        br.append_trial(_row(status="bogus"), p)


def test_trial_count_distinct_params(tmp_path):
    p = tmp_path / "r.csv"
    br.append_trial(_row("a/dev", params="thr=2", period="dev"), p)
    br.append_trial(_row("a/val", params="thr=2", period="val"), p)
    br.append_trial(_row("b/dev", params="thr=3"), p)
    br.append_trial(_row("bench", strategy="sma200", params="", status="benchmark"), p)
    br.append_trial(_row("plan", strategy="x", params="", status="planned"), p)
    assert br.trial_count(p) == 2
    assert br.trial_count(p, include_benchmarks=True) == 3


def test_rows_from_primary(tmp_path):
    import bt_stats as bs

    res = bs.PrimaryResult(
        sharpe={"dev": 0.7, "val": 0.6, "full": 0.65},
        d_sma200={"dev": 0.1, "val": 0.05},
        d_bh={"dev": 0.2, "val": 0.1},
        p_vs_sma200={"dev": 0.05, "val": 0.09},
        dsr=0.97,
        n_trials=4,
    )
    rows = br.rows_from_primary("S01", "cape", "nb.ipynb", "thr=2", res, note="x")
    assert [r["period"] for r in rows] == ["dev", "val", "full"]
    assert rows[0]["trial_id"] == "S01/dev"
    assert rows[2]["dsr"] == 0.97 and rows[0]["dsr"] is None
    p = tmp_path / "r.csv"
    df = br.append_trials(rows, p)
    assert len(df) == 3 and br.trial_count(p) == 1


def test_render_registry(tmp_path):
    p = tmp_path / "r.csv"
    md = tmp_path / "R.md"
    br.append_trial(_row(), p)
    text = br.render_registry(p, md, title="T")
    assert text.startswith("# T") and md.exists()
    assert "first \\| pass" in text
    assert "| " + " | ".join(br.COLUMNS) + " |" in text
    assert "**1**" in text
