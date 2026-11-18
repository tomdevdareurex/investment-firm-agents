"""A11 - independent pandas-only replication of the engine, benchmarks and
three strategies (S06 tom, S10 avg, S09 ratio<0.95).

Deliberately imports NOTHING from bt_common / bt_periods / bt_stats / stage2.
Inputs come from rep_inputs.pkl (raw prices, cash, Shiller, VIX) written by
rep_dump_inputs.py via the data loaders only.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _audit_common import banner, record  # noqa: E402

INPUTS = pd.read_pickle(HERE / "rep_inputs.pkl")
PX, CASH, SHILLER = INPUTS["px"], INPUTS["cash"], INPUTS["shiller"]
VIX, VIX3M = INPUTS["vix"], INPUTS["vix3m"]
ANN = 252
COST_BPS = 5.0
PERIODS = {
    "dev": ("1934-02-01", "1989-12-31"),
    "val": ("1990-01-01", "2009-12-31"),
    "holdout": ("2010-01-01", None),
}
LATE = {
    "dev": ("1900-01-01", "2013-12-31"),
    "val": ("2014-01-01", "2017-12-31"),
    "holdout": ("2018-01-01", None),
}


def month_end_flags(index: pd.DatetimeIndex) -> pd.Series:
    """True on the last trading day of each calendar month (own construction:
    a bar is month-end when the next bar, or the next business day after the
    final bar, falls in a different month)."""
    nxt = index[1:].append(pd.DatetimeIndex([index[-1] + pd.offsets.BDay(1)]))
    flags = (nxt.year != index.year) | (nxt.month != index.month)
    return pd.Series(flags, index=index)


def indep_backtest(signal, check="monthly", lag=2, cost_bps=COST_BPS):
    """Minimal engine: read the signal on check days, hold until the next
    check, fill `lag` bars later, pay cost_bps per unit of turnover.

    Returns a DataFrame with pos, r_eq, r_cash, r_strat (net) on rows where
    all three inputs exist.
    """
    idx = PX.index
    sig = signal.reindex(idx)
    if check == "monthly":
        chk = month_end_flags(idx)
    else:
        chk = pd.Series(True, index=idx)
    chk = chk & sig.notna()
    first = sig.first_valid_index()
    if first is not None:
        chk.loc[first] = True
    target = sig.where(chk).ffill()
    pos = target.shift(lag)
    r_eq = PX["tr_close"].pct_change()
    r_cash = CASH.reindex(idx)
    df = pd.DataFrame({"pos": pos, "r_eq": r_eq, "r_cash": r_cash}).dropna()
    turnover = df["pos"].diff().abs()
    turnover.iloc[0] = abs(df["pos"].iloc[0])
    df["r_strat"] = df["pos"] * df["r_eq"] + (1 - df["pos"]) * df["r_cash"]
    df["r_strat"] -= turnover * cost_bps / 1e4
    return df


def indep_sharpe(ret: pd.Series, rf: pd.Series) -> float:
    ex = ret - rf.reindex(ret.index).fillna(0.0)
    return float(ex.mean() / ex.std() * np.sqrt(ANN))


def slice_periods(df, periods, warmup=0, min_rows=60):
    body = df.iloc[warmup:] if warmup else df
    out = {}
    for name, (a, b) in periods.items():
        part = body.loc[a:b]
        if len(part) >= min_rows:
            out[name] = part
    out["full"] = body
    return out


# ---------------------------------------------------------------------------
# Signals, rebuilt independently from the raw inputs
# ---------------------------------------------------------------------------


def sma_on(window=200) -> pd.Series:
    close = PX["close"]
    sma = close.rolling(window, min_periods=window).mean()
    return (close > sma).astype(float).where(sma.notna())


def monthly_pit(monthly: pd.Series, months=1, days=0) -> pd.Series:
    """Month M value becomes usable on the first calendar day of M+1+months
    (+days), then forward-filled onto the trading calendar."""
    m = monthly.dropna().copy()
    avail = pd.DatetimeIndex(
        [
            pd.Timestamp(p.start_time) + pd.offsets.MonthBegin(1 + months)
            for p in m.index
        ]
    ) + pd.Timedelta(days=days)
    s = pd.Series(m.values, index=avail)
    union = PX.index.union(s.index)
    return s.reindex(union).ffill().reindex(PX.index)


def cape_on(warmup_months=120) -> pd.Series:
    sh = SHILLER.copy()
    sh.index = pd.PeriodIndex(sh.index, freq="M")
    ey = 1.0 / sh["CAPE"] - sh["GS10"] / 100.0
    median = ey.expanding(min_periods=warmup_months).median().shift(1)
    sig = (ey > median).astype(float).where(median.notna())
    return monthly_pit(sig, months=1, days=0)


def s10_avg_signal() -> pd.Series:
    return 0.5 * sma_on(200) + 0.5 * cape_on()


def s06_tom_signal() -> pd.Series:
    """Position for business day t+2 (Mon-Fri calendar): long on the last
    business day of the month and the first three business days."""
    idx = PX.index
    days = idx + 2 * pd.offsets.BDay()
    last = (days + pd.offsets.BDay()).month != days.month
    start = days.values.astype("datetime64[M]").astype("datetime64[D]")
    nth = np.busday_count(start, days.values.astype("datetime64[D]")) + 1
    return pd.Series((last | (nth <= 3)).astype(float), index=idx)


def s09_signal(thr=0.95) -> pd.Series:
    ratio = (VIX / VIX3M).dropna().sort_index()
    union = PX.index.union(ratio.index)
    lagged = ratio.reindex(union).ffill().shift(1).reindex(PX.index)
    return (lagged < thr).astype(float).where(lagged.notna())


# ---------------------------------------------------------------------------
# Reference numbers
# ---------------------------------------------------------------------------

BENCH_REF = pd.read_csv(HERE.parent / "benchmarks" / "benchmarks.csv")
REG = pd.read_csv(HERE.parent / "registry.csv")


def registry_sharpe(prefix: str) -> dict:
    rows = REG[REG["trial_id"].str.startswith(prefix + "/")]
    return {r["period"]: float(r["sharpe"]) for _, r in rows.iterrows()}


def bench_sharpe(name: str) -> dict:
    rows = BENCH_REF[BENCH_REF["benchmark"] == name]
    return {r["period"]: float(r["Sharpe"]) for _, r in rows.iterrows()}


def compare(label, got: dict, ref: dict, rows: list, tol=0.01):
    for period, s_ref in ref.items():
        s_got = got.get(period, np.nan)
        diff = s_got - s_ref
        rows.append(
            dict(
                item=label,
                period=period,
                original=round(s_ref, 4),
                independent=round(s_got, 4),
                diff=round(diff, 4),
                within_tol=abs(diff) <= tol if np.isfinite(diff) else False,
            )
        )


def main():
    rows = []
    banner("A11 independent replication (pandas only)")

    # Benchmarks: SMA200 monthly, next_close, 5bp, warm-up 252 bars after the
    # SMA window; buy-and-hold on the same rows.
    sma = indep_backtest(sma_on(200), check="monthly")
    parts = slice_periods(sma, PERIODS, warmup=252)
    compare(
        "bench sma200",
        {k: indep_sharpe(v["r_strat"], v["r_cash"]) for k, v in parts.items()},
        bench_sharpe("sma200"),
        rows,
    )
    compare(
        "bench bh",
        {k: indep_sharpe(v["r_eq"], v["r_cash"]) for k, v in parts.items()},
        bench_sharpe("bh"),
        rows,
    )

    # S06 tom: daily rebalance, main protocol (warm-up 252).
    s06 = indep_backtest(s06_tom_signal(), check="daily")
    parts = slice_periods(s06, PERIODS, warmup=252)
    compare(
        "S06 tom",
        {k: indep_sharpe(v["r_strat"], v["r_cash"]) for k, v in parts.items()},
        registry_sharpe("S06"),
        rows,
    )

    # S10 avg: monthly, main protocol.
    s10 = indep_backtest(s10_avg_signal(), check="monthly")
    parts = slice_periods(s10, PERIODS, warmup=252)
    compare(
        "S10 avg",
        {k: indep_sharpe(v["r_strat"], v["r_cash"]) for k, v in parts.items()},
        registry_sharpe("S10"),
        rows,
    )

    # S09 ratio<0.95: daily, late protocol (no warm-up drop).
    s09 = indep_backtest(s09_signal(0.95), check="daily")
    parts = slice_periods(s09, LATE, warmup=0)
    compare(
        "S09 ratio<0.95",
        {k: indep_sharpe(v["r_strat"], v["r_cash"]) for k, v in parts.items()},
        registry_sharpe("S09"),
        rows,
    )

    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    out.to_csv(HERE / "rep_independent.csv", index=False)

    worst = out["diff"].abs().max()
    n_bad = int((~out["within_tol"]).sum())
    record(
        id="A11-01",
        area="replication",
        strategy="bench,S06,S09,S10",
        severity="none" if n_bad == 0 else "major",
        finding="Independent pandas-only engine reproduces benchmark and strategy Sharpes",
        evidence=f"audit/rep_independent.py; {len(out)} period comparisons, max |diff| {worst:.4f}, "
        f"{n_bad} outside 0.01",
        effect=(
            "Engine timing, costs, cash leg and period slicing confirmed"
            if n_bad == 0
            else "See rep_independent.csv for the mismatching periods"
        ),
        fixed="no",
        file="audit/rep_independent.csv",
    )


if __name__ == "__main__":
    main()
