"""A6 - S06 calendar strategy: is the position really held on the intended days?

The S06 signal on trading day t is ``desired(t + 2 BDays)`` (Mon-Fri calendar) and the engine
holds ``target.shift(2)`` with next_close execution, i.e. the position earning the return of
row t is the signal of row t-2.  When no exchange holiday lies between t-2 and t the two cancel
and the position on day t equals ``desired(t)``.  Here we measure how often that holds on the
real trading calendar, and what the intended-days version would have earned instead.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import _audit_common as ac
import bt_common as bc
import bt_long
import bt_periods as bp
import bt_stats as bs

sys.path.insert(0, str(ac.BT / "seasonality"))
import build_s06 as b  # noqa: E402

sample = bt_long.long_sample()
px, cash = sample["px"], sample["cash"]
ns = dict(np=np, pd=pd)
exec(b.SIGNAL, ns)
desired, build_signal = ns["desired"], ns["build_signal"]


def intended_on_trading_calendar(idx: pd.DatetimeIndex, rule: str) -> pd.Series:
    """Intended holding flag per trading day using the actual exchange calendar."""
    month = idx.month
    halloween = np.isin(month, [11, 12, 1, 2, 3, 4])
    nxt = pd.Series(idx, index=idx).shift(-1)
    last = (nxt.dt.month != month) | nxt.isna()
    nth = pd.Series(1, index=idx).groupby([idx.year, idx.month]).cumsum()
    tom = last.values | (nth.values <= 3)
    out = {"halloween": halloween, "tom": tom, "halloween_or_tom": halloween | tom}[
        rule
    ]
    return pd.Series(out.astype(float), index=idx)


def main() -> None:
    ac.banner("A6 S06: realised position vs intended calendar days")
    rows = []
    for rule in ("tom", "halloween", "halloween_or_tom"):
        sig = build_signal({"px": px}, rule=rule)
        df = bc.backtest_signal(
            px, sig, cash, cost_bps=5, execution="next_close", rebalance="daily"
        )
        want = intended_on_trading_calendar(df.index, rule)
        mism = (df["pos"] != want).astype(int)
        # the Mon-Fri construction evaluated on the realised day (no holiday effect)
        same_day = pd.Series(desired(df.index, rule).astype(float), index=df.index)
        rows.append(
            dict(
                rule=rule,
                days=len(df),
                pos_eq_intended=1 - mism.mean(),
                pos_eq_monfri_same_day=(df["pos"] == same_day).mean(),
                mismatch_days=int(mism.sum()),
                held_share=df["pos"].mean(),
                intended_share=want.mean(),
                sharpe_realised=bs.excess_sharpe(df["r_strat"], df["r_cash"]),
            )
        )
    out = pd.DataFrame(rows).set_index("rule")
    print(out.to_string())
    return out


def per_period_tom() -> pd.DataFrame:
    """Sharpe of registry S06 'tom' vs a version whose position is exactly the intended days."""
    sig = build_signal({"px": px}, rule="tom")
    want = intended_on_trading_calendar(px.index, "tom")
    exact = want.shift(-2)  # so that target.shift(2) lands on the intended day exactly
    runs_reg = bp.run_periods(px, sig, cash, rebalance="daily")
    runs_ex = bp.run_periods(px, exact, cash, rebalance="daily")
    rows = {}
    for p in runs_reg:
        rows[p] = dict(
            registry=bs.excess_sharpe(runs_reg[p]["r_strat"], runs_reg[p]["r_cash"]),
            exact=bs.excess_sharpe(runs_ex[p]["r_strat"], runs_ex[p]["r_cash"]),
        )
    return pd.DataFrame(rows).T


if __name__ == "__main__":
    out = main()
    ac.banner(
        "A6 S06 tom: registry construction vs exact intended-day position, Sharpe per period"
    )
    pp = per_period_tom()
    print(pp.round(4).to_string())
    tom = out.loc["tom"]
    ac.record(
        id="A6-01",
        area="calendar/holidays",
        strategy="S06",
        severity="minor",
        finding="S06 builds the signal as desired(t+2 BDays) on a Mon-Fri calendar and the engine holds it with a "
        "2-bar lag, so around exchange holidays the realised position misses the intended turn-of-month / "
        "Nov-Apr day by one trading day.",
        evidence=f"a6_s06_calendar.py: tom position == intended trading-calendar day on {tom['pos_eq_intended']:.4f} of "
        f"{int(tom['days'])} days ({int(tom['mismatch_days'])} mismatches); halloween "
        f"{out.loc['halloween','pos_eq_intended']:.4f}; exact-day tom Sharpe dev {pp.loc['dev','exact']:.4f} vs registry "
        f"{pp.loc['dev','registry']:.4f}, val {pp.loc['val','exact']:.4f} vs {pp.loc['val','registry']:.4f}",
        effect="Small mis-timing on holiday-adjacent days; does not change the FAIL verdict (val p 0.84 in registry). "
        "Documented in the notebook caveats ('windows can be off by one trading day').",
        fixed="no",
        file="notebooks/backtest/seasonality/build_s06.py",
    )
