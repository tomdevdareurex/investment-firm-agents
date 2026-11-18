"""Re-score S01-S10 under deflated-Sharpe v2 (benchmark-relative and cross-trial).

Reads the cached strategy returns from the Stage 3 audit (audit/a8_returns.pkl),
the registry (for the cross-trial variance of dev Sharpe) and the Stage 1
benchmarks, and writes audit/metric_v2_scores.csv plus a markdown table printed
to stdout.  Offline; no notebook is re-executed.  The frozen v1 gate is reported
unchanged alongside.
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
BT = HERE.parent
sys.path.insert(0, str(BT))

import bt_long as bl  # noqa: E402
import bt_periods as bp  # noqa: E402
import bt_stats_v2 as v2  # noqa: E402

N_REGISTRY = 34  # distinct strategy/parameter trials in registry.csv
N_FULL = 119  # + SMA grid (65) + cost sweep (39) + TimesFM rules (20), AUDIT.md 6.3
PERIODS = ["dev", "val", "holdout", "full"]


def main() -> int:
    cache = pickle.load(open(HERE / "a8_returns.pkl", "rb"))
    reg = pd.read_csv(BT / "registry.csv")
    dev = reg[(reg.period == "dev") & (reg.status != "benchmark")]
    var_cross = v2.cross_trial_variance(dev.drop_duplicates("sharpe")["sharpe"])
    sample = bl.long_sample()
    bench = bp.benchmark_returns(sample["px"], sample["cash"])
    sma = bench["sma200"]
    cash = sample["cash"]
    print(
        f"cross-trial daily var of Sharpe = {var_cross:.3e} (n={dev.sharpe.nunique()})"
    )
    frames = []
    for per in PERIODS:
        runs = {}
        for sid, d in cache.items():
            lo, hi = d["periods"][per]
            runs[sid] = d["r_strat"].loc[lo:hi]
        tab = v2.score_table(runs, sma, cash, N_REGISTRY, N_FULL, var_cross)
        tab.insert(0, "period", per)
        frames.append(tab.reset_index())
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(HERE / "metric_v2_scores.csv", index=False)
    show = out[out.period.isin(["dev", "val"])].copy()
    cols = [
        "strategy",
        "period",
        "sr_annual",
        "active_sr_annual",
        "dsr_v1",
        "dsr_vs_bench",
        "dsr_cross_reg",
        "dsr_cross_full",
        "pass_v1",
        "pass_v2",
    ]
    print(show[cols].round(3).to_string(index=False))
    both = out[out.period.isin(["dev", "val"])].groupby("strategy")["pass_v2"].all()
    print("\npass_v2 in BOTH dev and val:", list(both[both].index) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
