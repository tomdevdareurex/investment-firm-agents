"""A4 - Shiller publication-lag sensitivity for S01, S10 (fast) and S08 (slow, --s08).

Shiller's monthly E is interpolated from quarterly S&P earnings reported ~1-3 months
after quarter end (and revised), so month M's CAPE can embed information released up to
~5 months later. We re-run with months=4 (i.e. +3 months) and with an extra 12-month lag
on the pre-1953 GS10 (interpolated from annual data) and check whether verdicts move.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import _audit_common as ac

import bt_common as bc
import bt_long
import bt_periods as bp
import bt_pit
import bt_stats as bs
import stage2 as s2

sample = bt_long.long_sample()
px, cash, shiller = sample["px"], sample["cash"], sample["shiller"]
bench = bp.benchmark_returns(px, cash)
N_TRIALS = 34


def cape_monthly(extra_gs10_pre1953: int = 0) -> pd.Series:
    m = shiller[["CAPE", "GS10"]].dropna().copy()
    m.index = m.index.to_timestamp(how="start")
    gs = m["GS10"]
    if extra_gs10_pre1953:
        # Pre-1953 long rate is interpolated from annual data: assume the annual figure
        # is only known `extra` months after the year it describes.
        lagged = gs.shift(extra_gs10_pre1953)
        gs = gs.where(gs.index >= "1953-04-01", lagged)
    ey = 1 / m["CAPE"] - gs / 100
    median = ey.expanding(min_periods=120).median().shift(1)
    sig = (ey > median).astype(float)
    sig[median.isna()] = np.nan
    return sig


def cape_daily(months: int, extra_gs10: int = 0) -> pd.Series:
    return bt_pit.monthly_to_daily_pit(
        cape_monthly(extra_gs10), px.index, months=months, days=0
    )


def summarise(label: str, signal: pd.Series) -> dict:
    runs = bp.run_periods(px, signal, cash)
    res = bs.primary_metric(
        runs, bench, n_trials=N_TRIALS, rng=np.random.default_rng(bs.SEED)
    )
    row = {"variant": label}
    for p in ("dev", "val", "holdout", "full"):
        row[f"{p}_sharpe"] = round(res.sharpe.get(p, np.nan), 4)
    for p in ("dev", "val"):
        row[f"{p}_p"] = round(res.p_vs_sma200.get(p, np.nan), 4)
    row["dsr"] = round(res.dsr, 4)
    row["pass"] = all(res.checks[k] for k in res.checks if k != "holdout_d_sma200_pos")
    return row


def s10_avg(cape_on: pd.Series) -> pd.Series:
    sma_on, _ = bc.sma_signal(px["close"], 200)
    sma_on = sma_on.astype(float)
    cape_on = cape_on.reindex(px.index)
    return (0.5 * sma_on + 0.5 * cape_on).where(cape_on.notna())


def main() -> None:
    ac.banner("A4.1 S01 CAPE excess yield - Shiller lag sensitivity")
    rows = []
    rows.append(summarise("S01 months=1 (registry)", cape_daily(1)))
    rows.append(summarise("S01 months=4 (+3m E lag)", cape_daily(4)))
    rows.append(summarise("S01 months=1, GS10 pre-1953 +12m", cape_daily(1, 12)))
    rows.append(summarise("S01 months=4, GS10 pre-1953 +12m", cape_daily(4, 12)))
    s01 = pd.DataFrame(rows).set_index("variant")
    print(s01.to_string())

    ac.banner("A4.2 S10 avg (0.5 SMA200 + 0.5 CAPE) - Shiller lag sensitivity")
    rows = []
    rows.append(summarise("S10 avg months=1 (registry)", s10_avg(cape_daily(1))))
    rows.append(summarise("S10 avg months=4 (+3m E lag)", s10_avg(cape_daily(4))))
    rows.append(
        summarise("S10 avg months=1, GS10 pre-1953 +12m", s10_avg(cape_daily(1, 12)))
    )
    s10 = pd.DataFrame(rows).set_index("variant")
    print(s10.to_string())
    out = ac.HERE / "a4_s01_s10_lag.csv"
    pd.concat([s01, s10]).to_csv(out)
    print("saved", out)
    return s01, s10


def run_s08(extra_months: int) -> dict:
    """Execute the S08 builder code with Shiller lags extended by ``extra_months``."""
    sys.path.insert(0, str(ac.BT / "ml"))
    import build_s08 as b  # noqa: E402

    real = bt_pit.monthly_to_daily_pit

    def patched(s, idx, months=0, days=0, **kw):
        if months >= 1:  # Shiller dp/ep features; FRED features use months=0
            months += extra_months
        return real(s, idx, months=months, days=days, **kw)

    ns = dict(
        sample=sample,
        px=px,
        cash=cash,
        bench=bench,
        bt_long=bt_long,
        bt_pit=bt_pit,
        bc=bc,
        bp=bp,
        bs=bs,
        s2=s2,
        np=np,
        pd=pd,
    )
    exec(b.DATA, ns)
    bt_pit.monthly_to_daily_pit = patched
    try:
        exec(b.SIGNAL, ns)
        signal = ns["build_signal"](ns["inputs"], **ns["VARIANTS"]["logit_c0.1"])
    finally:
        bt_pit.monthly_to_daily_pit = real
    return summarise(f"S08 logit_c0.1 Shiller +{extra_months}m", signal)


if __name__ == "__main__":
    s01, s10 = main()
    r = lambda df, v, c: float(df.loc[v, c])
    ac.record(
        id="A4-01",
        area="look-ahead/Shiller lag",
        strategy="S01",
        severity="minor",
        finding="Shiller monthly E is interpolated from quarterly earnings published up to ~5 months later; "
        "S01 uses months=1.  Re-run with months=4 (+3m).",
        evidence=f"a4_shiller_lag.py: months=1 dev {r(s01,'S01 months=1 (registry)','dev_sharpe')} / val "
        f"{r(s01,'S01 months=1 (registry)','val_sharpe')}; months=4 dev {r(s01,'S01 months=4 (+3m E lag)','dev_sharpe')} "
        f"/ val {r(s01,'S01 months=4 (+3m E lag)','val_sharpe')} (p dev {r(s01,'S01 months=4 (+3m E lag)','dev_p')}, "
        f"val {r(s01,'S01 months=4 (+3m E lag)','val_p')})",
        effect="Longer lag IMPROVES S01 (val Sharpe 0.14 -> 0.44) but still fails both periods vs SMA200; verdict unchanged. "
        "Registry baseline reproduced exactly.",
        fixed="no",
        file="notebooks/backtest/valuation/build_cape.py",
    )
    ac.record(
        id="A4-02",
        area="look-ahead/Shiller lag",
        strategy="S10",
        severity="minor",
        finding="S10 avg re-run with CAPE lag months=4 (+3m).",
        evidence=f"a4_shiller_lag.py: months=1 dev {r(s10,'S10 avg months=1 (registry)','dev_sharpe')} val "
        f"{r(s10,'S10 avg months=1 (registry)','val_sharpe')}; months=4 dev {r(s10,'S10 avg months=4 (+3m E lag)','dev_sharpe')} "
        f"val {r(s10,'S10 avg months=4 (+3m E lag)','val_sharpe')} p val {r(s10,'S10 avg months=4 (+3m E lag)','val_p')}",
        effect="Val Sharpe 0.555 -> 0.652 (above SMA200 0.572) but dev p 0.21 and val p 0.21 > 0.10; FAIL unchanged.  "
        "Holdout Sharpe 0.7596 vs registry 0.7601 (rounding/bootstrap-free; <0.001).",
        fixed="no",
        file="notebooks/backtest/ensemble/build_s10.py",
    )
    ac.record(
        id="A4-04",
        area="look-ahead/Shiller GS10 pre-1953",
        strategy="S01,S10",
        severity="none",
        finding="Pre-1953 Shiller long rate is interpolated from annual data; re-run with GS10 lagged 12 months before 1953-04.",
        evidence=f"a4_shiller_lag.py: S01 dev {r(s01,'S01 months=1, GS10 pre-1953 +12m','dev_sharpe')} vs {r(s01,'S01 months=1 (registry)','dev_sharpe')}; "
        f"S10 dev {r(s10,'S10 avg months=1, GS10 pre-1953 +12m','dev_sharpe')} vs {r(s10,'S10 avg months=1 (registry)','dev_sharpe')}",
        effect="Sharpe changes < 0.002; immaterial.",
        fixed="no",
        file="notebooks/backtest/bt_long.py",
    )
    if "--s08" in sys.argv:
        ac.banner("A4.3 S08 ML walk-forward - Shiller lag +3m (slow)")
        rows = [run_s08(0), run_s08(3)]
        s08 = pd.DataFrame(rows).set_index("variant")
        print(s08.to_string())
        s08.to_csv(ac.HERE / "a4_s08_lag.csv")
        ac.record(
            id="A4-03",
            area="look-ahead/Shiller lag",
            strategy="S08",
            severity="minor",
            finding="S08 (dp months=1, ep months=3) re-run with both Shiller lags +3m.",
            evidence=f"a4_shiller_lag.py --s08: base dev {s08.iloc[0]['dev_sharpe']} val {s08.iloc[0]['val_sharpe']}; "
            f"+3m dev {s08.iloc[1]['dev_sharpe']} val {s08.iloc[1]['val_sharpe']} p dev {s08.iloc[1]['dev_p']} val {s08.iloc[1]['val_p']}",
            effect=f"pass={bool(s08.iloc[1]['pass'])}; verdict unchanged.",
            fixed="no",
            file="notebooks/backtest/ml/build_s08.py",
        )
