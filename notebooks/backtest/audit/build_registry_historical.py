"""Build ``registry_historical.csv``: trials run in the earlier SMA / TimesFM
studies that were never counted in ``registry.csv`` (AUDIT.md A8-03, NS2).

These rows are kept in a separate file on purpose: ``bt_registry.trial_count``
and the quoted ``n_trials = 34`` of the frozen Stage 1/2 metric must not move.
The fuller count (34 + len(this file)) is used only by metric v2
(``bt_stats_v2``), see ``PLAN-stage3.md`` section 2.

Run from the repo root::

    .venv/Scripts/python.exe notebooks/backtest/audit/build_registry_historical.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
BT = HERE.parent
sys.path.insert(0, str(BT))

import bt_registry as br  # noqa: E402

OUT_CSV = BT / "registry_historical.csv"
GRID_CSV = HERE / "a8_sma_grid.csv"

SMA_WINDOWS = [5, 10, 20, 30, 50, 75, 100, 150, 200, 250, 300, 350, 400]
SMA_REBAL = ["daily", "weekly", "monthly", "quarterly", "yearly"]
SMA_COSTS = [0, 5, 20]
P_STAR_GRID = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
TAIL_Q10_GRID = [-0.03, -0.04, -0.05, -0.06, -0.07, -0.08, -0.10, -0.12, -0.15]
SMA_NB = "sma/sma_trend_backtest.ipynb"
TFM_NB = "timesfm/timesfm_forecast_backtest.ipynb"
DATE = "2026-10-20"
COLUMNS = list(br.COLUMNS) + ["source", "original_sample"]
NOTE_NOT_RERUN = "not re-run on the long sample; counted for multiplicity only"


def _row(
    trial_id: str, strategy: str, nb: str, params: str, source: str, sample: str, **kw
) -> dict:
    base = {c: "" for c in COLUMNS}
    base.update(
        trial_id=trial_id,
        date=DATE,
        strategy=strategy,
        notebook=nb,
        params=params,
        period="",
        status="run",
        note=NOTE_NOT_RERUN,
        source=source,
        original_sample=sample,
    )
    base.update(kw)
    return base


def sma_rows() -> list[dict]:
    grid = pd.read_csv(GRID_CSV) if GRID_CSV.exists() else pd.DataFrame()
    rows: list[dict] = []
    for w in SMA_WINDOWS:
        for reb in SMA_REBAL:
            hit = (
                grid[(grid["window"] == w) & (grid["rebalance"] == reb)]
                if len(grid)
                else grid
            )
            kw: dict = {}
            if len(hit):
                kw = dict(
                    period="dev 1934-1989 / val 1990-2009",
                    sharpe=f"{hit['dev'].iloc[0]:.3f} / {hit['val'].iloc[0]:.3f}",
                    note="re-run on the long proxy in audit/a8_sma_grid.csv (dev / val Sharpe)",
                )
            rows.append(
                _row(
                    f"H-SMA-{w}-{reb}",
                    "sma_trend",
                    SMA_NB,
                    f"window={w};rebalance={reb};cost_bps=5",
                    "sma window x rebalance sweep",
                    "SPY 1993+",
                    **kw,
                )
            )
    for w in SMA_WINDOWS:
        for c in SMA_COSTS:
            rows.append(
                _row(
                    f"H-SMA-{w}-cost{c}",
                    "sma_trend",
                    SMA_NB,
                    f"window={w};rebalance=monthly;cost_bps={c}",
                    "sma window x cost sweep",
                    "SPY 1993+",
                    note="cost sweep: same signal as the rebalance grid, "
                    "not signal-distinct (excluded from the headline count)",
                )
            )
    return rows


def timesfm_rows() -> list[dict]:
    rows = [
        _row(
            "H-TFM-R1",
            "timesfm_rule",
            TFM_NB,
            "rule=R1;median>cash",
            "timesfm rules",
            "SPY 1997+",
        ),
        _row(
            "H-TFM-R4",
            "timesfm_rule",
            TFM_NB,
            "rule=R4;median>cash&sma200",
            "timesfm rules",
            "SPY 1997+",
        ),
        _row(
            "H-TFM-ARIMA",
            "arima_rule",
            TFM_NB,
            "rule=R1;model=arima111",
            "timesfm comparisons",
            "SPY 1997+",
        ),
        _row(
            "H-TFM-MOM",
            "momentum_1m",
            TFM_NB,
            "rule=trailing_1m>cash",
            "timesfm comparisons",
            "SPY 1997+",
        ),
    ]
    for p in P_STAR_GRID:
        rows.append(
            _row(
                "H-TFM-R2-p%.2f" % p,
                "timesfm_rule",
                TFM_NB,
                f"rule=R2;p_star={p}",
                "timesfm rules",
                "SPY 1997+",
            )
        )
    for x in TAIL_Q10_GRID:
        rows.append(
            _row(
                "H-TFM-R3-q%.2f" % x,
                "timesfm_rule",
                TFM_NB,
                f"rule=R3;tail_q10={x}",
                "timesfm rules",
                "SPY 1997+",
            )
        )
    return rows


def build() -> pd.DataFrame:
    df = pd.DataFrame(sma_rows() + timesfm_rows(), columns=COLUMNS)
    df["signal_distinct"] = ~df["source"].str.contains("cost sweep")
    return df


def main() -> None:
    df = build()
    df.to_csv(OUT_CSV, index=False)
    n_sig = int(df["signal_distinct"].sum())
    n_reg = br.trial_count()
    print(f"wrote {OUT_CSV.name}: {len(df)} rows, {n_sig} signal-distinct")
    print(
        f"registered trials: {n_reg}; fuller count: {n_reg + n_sig} signal-distinct, {n_reg + len(df)} incl. cost sweeps"
    )


if __name__ == "__main__":
    main()
