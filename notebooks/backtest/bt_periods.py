"""Period split (dev / val / holdout), per-period runner and the benchmark set.

Every shortlist idea is evaluated with the same splits and against the same
benchmarks so trials in the registry are comparable.  Nothing here fetches data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import bt_common as bc

PERIODS = {
    "dev": ("1934-02-01", "1989-12-31"),
    "val": ("1990-01-01", "2009-12-31"),
    "holdout": ("2010-01-01", None),
}
PERIOD_ORDER = ("dev", "val", "holdout", "full")

BENCH_SMA_WINDOW = 200
BENCH_REBALANCE = "monthly"
BENCH_EXECUTION = "next_close"
BENCH_COST_BPS = 5.0


def period_bounds(
    name: str, index: pd.DatetimeIndex
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Start/end timestamps of a named period clipped to the available index."""
    if name == "full":
        return index[0], index[-1]
    start, end = PERIODS[name]
    lo = max(index[0], pd.Timestamp(start))
    hi = index[-1] if end is None else min(index[-1], pd.Timestamp(end))
    return lo, hi


def slice_period(df: pd.DataFrame | pd.Series, name: str):
    lo, hi = period_bounds(name, df.index)
    return df.loc[lo:hi]


def run_periods(
    px: pd.DataFrame,
    signal: pd.Series,
    cash: pd.Series,
    cost_bps: float = BENCH_COST_BPS,
    execution: str = BENCH_EXECUTION,
    rebalance: str = BENCH_REBALANCE,
    periods=("dev", "val", "holdout", "full"),
    warmup_days: int = 252,
    extra: dict | None = None,
) -> dict[str, pd.DataFrame]:
    """Run ``bc.backtest_signal`` over the full sample once, then slice per period.

    Running once and slicing keeps the position path identical across periods
    (a period never starts flat because of a warm-up) and means the first
    ``warmup_days`` of the full sample are the only rows lost to the signal
    warm-up.  Returned frames carry ``attrs['period']``.
    """
    full = bc.backtest_signal(
        px, signal, cash, cost_bps, execution, None, rebalance, extra=extra
    )
    full = full.iloc[warmup_days:] if warmup_days else full
    out = {}
    for name in periods:
        part = slice_period(full, name).copy()
        if len(part) < 60:
            continue
        part.attrs["period"] = name
        out[name] = part
    return out


def period_table(
    runs: dict[str, pd.DataFrame], column: str = "r_strat"
) -> pd.DataFrame:
    """perf_stats of ``column`` (vs r_cash) for each period, one row per period."""
    rows = {}
    for name, bt in runs.items():
        st = bc.perf_stats(bt[column], bt["r_cash"])
        st.update(bc.strategy_stats(bt)) if column == "r_strat" else None
        rows[name] = st
    return pd.DataFrame(rows).T.reindex([p for p in PERIOD_ORDER if p in rows])


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


def constant_mix_returns(
    r_eq: pd.Series, r_cash: pd.Series, weight: float = 0.6, rebalance: str = "monthly"
) -> pd.Series:
    """Equity/cash constant mix rebalanced at ``rebalance`` (no costs)."""
    r_eq = r_eq.fillna(0.0)
    r_cash = r_cash.reindex(r_eq.index).fillna(0.0)
    checks = bc.check_days(r_eq.index, rebalance)
    w = weight
    out = np.empty(len(r_eq))
    eq_v, ca_v = w, 1 - w
    for i, (re, rc, chk) in enumerate(zip(r_eq.values, r_cash.values, checks)):
        eq_v *= 1 + re
        ca_v *= 1 + rc
        tot = eq_v + ca_v
        out[i] = tot - 1
        if chk:
            eq_v, ca_v = w, 1 - w
        else:
            eq_v, ca_v = eq_v / tot, ca_v / tot
    return pd.Series(out, index=r_eq.index, name=f"mix{int(weight*100)}")


def benchmark_returns(
    px: pd.DataFrame,
    cash: pd.Series,
    cost_bps: float = BENCH_COST_BPS,
    execution: str = BENCH_EXECUTION,
    rebalance: str = BENCH_REBALANCE,
    sma_window: int = BENCH_SMA_WINDOW,
    warmup_days: int = 252,
) -> pd.DataFrame:
    """Daily return columns of the benchmark set on the full sample.

    Columns: ``bh`` (buy and hold total return), ``sma200`` (price > SMA rule,
    monthly check, next-close execution, costs), ``mix60`` (60/40 equity/T-bill,
    monthly rebalance) and ``tbill``.  ``attrs['sma_bt']`` keeps the SMA frame.
    """
    sma = bc.sma_backtest(px, cash, sma_window, cost_bps, execution, None, rebalance)
    sma = sma.iloc[warmup_days:] if warmup_days else sma
    out = pd.DataFrame(
        {
            "bh": sma["r_bh"],
            "sma200": sma["r_strat"],
            "mix60": constant_mix_returns(sma["r_bh"], sma["r_cash"], 0.6, rebalance),
            "tbill": sma["r_cash"],
        }
    )
    out.attrs["sma_bt"] = sma
    return out


def benchmark_table(bench: pd.DataFrame, periods=PERIOD_ORDER) -> pd.DataFrame:
    """MultiIndex (period, benchmark) -> perf_stats."""
    rows = {}
    for name in periods:
        part = slice_period(bench, name)
        if len(part) < 60:
            continue
        for col in ("bh", "sma200", "mix60", "tbill"):
            rows[(name, col)] = bc.perf_stats(part[col], part["tbill"])
    return pd.DataFrame(rows).T


def compare_to_benchmarks(
    runs: dict[str, pd.DataFrame], bench: pd.DataFrame
) -> pd.DataFrame:
    """Strategy Sharpe next to each benchmark's Sharpe, per period, plus diffs."""
    rows = {}
    for name, bt in runs.items():
        b = bench.reindex(bt.index)
        s = bc.perf_stats(bt["r_strat"], bt["r_cash"])["Sharpe"]
        row = {"strategy": s}
        for col in ("bh", "sma200", "mix60"):
            row[col] = bc.perf_stats(b[col], b["tbill"])["Sharpe"]
            row[f"d_{col}"] = s - row[col]
        rows[name] = row
    return pd.DataFrame(rows).T.reindex([p for p in PERIOD_ORDER if p in rows])


__all__ = [
    "PERIODS",
    "PERIOD_ORDER",
    "BENCH_SMA_WINDOW",
    "BENCH_REBALANCE",
    "BENCH_EXECUTION",
    "BENCH_COST_BPS",
    "period_bounds",
    "slice_period",
    "run_periods",
    "period_table",
    "constant_mix_returns",
    "benchmark_returns",
    "benchmark_table",
    "compare_to_benchmarks",
]
