"""Seed registry.csv: benchmark rows, backfilled trials, planned shortlist. Idempotent."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bt_registry as br  # noqa: E402

BENCH_CSV = HERE / "benchmarks" / "benchmarks.csv"
TODAY = "2026-10-18"

HEADER = """Trial registry

Every strategy variant evaluated under the frozen primary metric is a *trial*; the
distinct `(strategy, params)` count below feeds the deflated Sharpe ratio.

**Primary metric (frozen 2026-10-18):** excess-return Sharpe net of costs. Pass =
dev AND val Sharpe > SMA200 and > buy-and-hold, one-sided block-bootstrap p <= 0.10
vs SMA200 in both, DSR >= 0.95 with the trial count below; holdout (2010+) is
confirmatory only. Periods: dev 1934-02..1989-12, val 1990..2009, holdout 2010+.

Status: `benchmark` reference row, `run` evaluated before the metric was frozen
(not under the pass rule), `pass`/`fail` evaluated under the rule, `planned` not yet run.
"""


def benchmark_rows() -> list[dict]:
    b = pd.read_csv(BENCH_CSV)
    rows = []
    for _, r in b.iterrows():
        if r["benchmark"] == "tbill":
            continue
        rows.append(
            {
                "trial_id": f"BENCH-{r['benchmark']}/{r['period']}",
                "date": TODAY,
                "strategy": r["benchmark"],
                "notebook": "benchmarks/benchmarks.ipynb",
                "params": (
                    "sma=200;rebalance=monthly;exec=next_close;cost=5bp"
                    if r["benchmark"] == "sma200"
                    else (
                        "w=0.6;rebalance=monthly" if r["benchmark"] == "mix60" else ""
                    )
                ),
                "period": r["period"],
                "sharpe": r["Sharpe"],
                "status": "benchmark",
                "note": f"CAGR {r['CAGR']:.2%}, MaxDD {r['Max DD']:.2%}",
            }
        )
    return rows


BACKFILL = [
    # (trial_id, strategy, notebook, params, period, sharpe, d_sma200, d_bh, note)
    (
        "BF-sma200-long",
        "sma200",
        "sma/sma200_regime_analysis.ipynb",
        "sma=200;rebalance=monthly;exec=next_close;cost=5bp;sample=long_1934",
        "full",
        0.64,
        0.0,
        0.13,
        "pre-freeze long sample; B&H 0.51",
    ),
    (
        "BF-sma200-spy",
        "sma200",
        "sma/sma200_regime_analysis.ipynb",
        "sma=200;rebalance=monthly;exec=next_close;cost=5bp;sample=SPY_1993",
        "full",
        0.65,
        0.0,
        0.13,
        "pre-freeze SPY sample; B&H 0.52",
    ),
    (
        "BF-sma_trend-spy",
        "sma_trend",
        "sma/sma_trend_backtest.ipynb",
        "sma=200;rebalance=monthly;exec=next_open;cost=5bp;sample=SPY_1995",
        "full",
        0.69,
        None,
        0.16,
        "pre-freeze; B&H 0.53",
    ),
    (
        "BF-timesfm-sma200",
        "timesfm_vs_sma200",
        "timesfm/timesfm_forecast_backtest.ipynb",
        "model=timesfm-2.5-200m;baseline=sma200",
        "full",
        0.63,
        0.0,
        0.15,
        "pre-freeze; SMA200 baseline 0.63, B&H 0.48 in that window",
    ),
]

SHORTLIST = [
    (
        "S01",
        "cape_excess_yield",
        "valuation/cape_excess_yield.ipynb",
        "REFERENCE: Shiller CAPE yield minus 10y yield, PIT lag",
    ),
    (
        "S02",
        "credit_term_spread",
        "macro/credit_term_spread.ipynb",
        "BAA-AAA and 10y-3m spreads",
    ),
    (
        "S03",
        "sahm_rule",
        "macro/sahm_rule.ipynb",
        "unemployment 3m avg vs 12m low, PIT lag",
    ),
    (
        "S04",
        "vol_managed",
        "vol/vol_managed.ipynb",
        "target-vol scaling of equity exposure",
    ),
    (
        "S05",
        "tsmom_12_1",
        "momentum/tsmom_12_1.ipynb",
        "12-1 month time-series momentum",
    ),
    (
        "S06",
        "halloween_tom",
        "seasonal/halloween_tom.ipynb",
        "Halloween + turn-of-month",
    ),
    (
        "S07",
        "edgar_agg_earnings",
        "fundamental/edgar_agg_earnings.ipynb",
        "2009+ only, short sample",
    ),
    (
        "S08",
        "ml_goyal_walkforward",
        "ml/ml_goyal_walkforward.ipynb",
        "walk-forward with purge/embargo (bt_ml)",
    ),
    (
        "S09",
        "vix_term_structure",
        "vol/vix_term_structure.ipynb",
        "VIX/VIX3M, 2009+ only",
    ),
    (
        "S10",
        "sma200_cape_ensemble",
        "ensemble/sma200_cape_ensemble.ipynb",
        "combine S01 with SMA200",
    ),
]


def backfill_rows() -> list[dict]:
    out = []
    for tid, strat, nb, params, period, sh, d_s, d_b, note in BACKFILL:
        out.append(
            {
                "trial_id": tid,
                "date": TODAY,
                "strategy": strat,
                "notebook": nb,
                "params": params,
                "period": period,
                "sharpe": sh,
                "d_sma200": d_s,
                "d_bh": d_b,
                "status": "run",
                "note": note,
            }
        )
    return out


def planned_rows() -> list[dict]:
    return [
        {
            "trial_id": tid,
            "date": TODAY,
            "strategy": strat,
            "notebook": nb,
            "params": "",
            "period": "",
            "status": "planned",
            "note": note,
        }
        for tid, strat, nb, note in SHORTLIST
    ]


def main(path: Path = br.REGISTRY_CSV) -> None:
    rows = benchmark_rows() + backfill_rows() + planned_rows()
    br.append_trials(rows, path)
    md = br.render_registry(path, title=HEADER)
    print(
        f"{len(rows)} rows seeded -> {path.name}; trials counted: {br.trial_count(path)}"
    )
    print(md[:300])


if __name__ == "__main__":
    main()
