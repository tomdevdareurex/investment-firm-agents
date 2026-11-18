"""Statistical evidence for the backtest programme (frozen primary metric).

PRIMARY metric = Sharpe of daily excess returns (strategy minus T-bill), net
of costs. A trial *passes* when, in dev AND val, its Sharpe beats both the
SMA200 benchmark and buy-and-hold, the block-bootstrap one-sided p-value of
the Sharpe difference vs SMA200 is <= P_MAX, the deflated Sharpe ratio is
>= DSR_MIN given the number of registered trials, and the holdout difference
vs SMA200 is positive (confirmatory only).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as sps

import bt_common as bc

N_BOOT = 10_000
BLOCK_MONTHS = 6
BLOCK_DAYS = 21 * BLOCK_MONTHS
NW_LAGS = 6
SEED = 42
P_MAX = 0.10
DSR_MIN = 0.95
ANN = 252


def _validate_evidence_version(evidence_version):
    if evidence_version not in ("legacy", "matched-v1"):
        raise ValueError("evidence_version must be 'legacy' or 'matched-v1'")


def excess_sharpe(ret: pd.Series, rf: pd.Series | None = None) -> float:
    """Annualised Sharpe of (ret - rf). rf=None treats ret as already excess."""
    ret = ret.dropna()
    if rf is not None:
        ret = ret - rf.reindex(ret.index).fillna(0.0)
    sd = ret.std()
    return float(ret.mean() / sd * math.sqrt(ANN)) if sd > 0 else float("nan")


def _sharpe_np(x: np.ndarray) -> np.ndarray:
    """Row-wise annualised Sharpe for a 2-D array of excess returns."""
    mu = x.mean(axis=1)
    sd = x.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, mu / sd * math.sqrt(ANN), np.nan)


@dataclass
class BootResult:
    sharpe_a: float
    sharpe_b: float
    diff: float
    p_value: float  # one-sided P(diff <= 0)
    ci_low: float
    ci_high: float
    n_boot: int
    block: int

    @property
    def significant(self) -> bool:
        return self.p_value <= P_MAX

    def row(self) -> dict:
        return {
            "sharpe_a": self.sharpe_a,
            "sharpe_b": self.sharpe_b,
            "diff": self.diff,
            "p_one_sided": self.p_value,
            "ci90_low": self.ci_low,
            "ci90_high": self.ci_high,
        }


def sharpe_diff_bootstrap(
    r_a: pd.Series,
    r_b: pd.Series,
    rf: pd.Series | None = None,
    n_boot: int = N_BOOT,
    block: int = BLOCK_DAYS,
    rng: np.random.Generator | None = None,
) -> BootResult:
    """Paired moving-block bootstrap of Sharpe(a) - Sharpe(b).

    Both series are resampled with the *same* block indices so common market
    shocks cancel; the one-sided p-value is the share of bootstrap draws in
    which a fails to beat b.
    """
    rng = rng or np.random.default_rng(SEED)
    df = pd.concat([r_a.rename("a"), r_b.rename("b")], axis=1).dropna()
    if rf is not None:
        rf = rf.reindex(df.index).fillna(0.0)
        df = df.sub(rf.values, axis=0)
    n = len(df)
    block = max(1, min(block, n))
    a = df["a"].to_numpy()
    b = df["b"].to_numpy()
    sa, sb = excess_sharpe(df["a"]), excess_sharpe(df["b"])
    idx = bc.block_indices(n, n_boot, block, rng)
    diffs = _sharpe_np(a[idx]) - _sharpe_np(b[idx])
    diffs = diffs[np.isfinite(diffs)]
    p = float((diffs <= 0).mean()) if len(diffs) else float("nan")
    lo, hi = np.percentile(diffs, [5, 95]) if len(diffs) else (np.nan, np.nan)
    return BootResult(sa, sb, sa - sb, p, float(lo), float(hi), n_boot, block)


# ---------------------------------------------------------------------------
# Placebo: random signals with the same time-in-market
# ---------------------------------------------------------------------------


def placebo_test(
    px: pd.DataFrame,
    signal: pd.Series,
    cash: pd.Series,
    n_placebo: int = 500,
    cost_bps: float = 5.0,
    execution: str = "next_close",
    rebalance: str = "monthly",
    rng: np.random.Generator | None = None,
    stat: str = "Sharpe",
    *,
    evidence_version: str = "legacy",
) -> dict:
    """Compare the real signal against random regime signals.

    Each placebo is a Markov on/off chain with the same unconditional
    time-in-market and the same average regime length as the real signal, so
    it earns the same beta and pays similar costs but carries no information.
    Returns the real stat, placebo quantile and a one-sided p-value.
    """
    _validate_evidence_version(evidence_version)
    if evidence_version == "matched-v1":
        from bt_placebo import placebo_test as matched_placebo_test

        return matched_placebo_test(
            px=px,
            signal=signal,
            cash=cash,
            n_placebo=n_placebo,
            cost_bps=cost_bps,
            execution=execution,
            rebalance=rebalance,
            rng=rng,
            stat=stat,
        )
    rng = rng or np.random.default_rng(SEED)
    real = bc.backtest_signal(px, signal, cash, cost_bps, execution, None, rebalance)
    real_stat = bc.perf_stats(real["r_strat"], real["r_cash"])[stat]
    s = signal.reindex(px.index).ffill().fillna(0.0).to_numpy()
    s = (s > 0.5).astype(int)
    share = s.mean()
    runs = max(1, int((np.diff(s) != 0).sum()))
    mean_len = len(s) / (runs + 1)
    # symmetric-ish two-state chain: P(stay) chosen to reproduce mean_len
    p_stay = 1 - 1 / mean_len
    vals = np.empty(n_placebo)
    for k in range(n_placebo):
        chain = np.empty(len(s), dtype=int)
        chain[0] = rng.random() < share
        u = rng.random(len(s))
        for t in range(1, len(s)):
            if u[t] < p_stay:
                chain[t] = chain[t - 1]
            else:
                chain[t] = rng.random() < share
        fake = pd.Series(chain.astype(float), index=px.index)
        df = bc.backtest_signal(px, fake, cash, cost_bps, execution, None, rebalance)
        vals[k] = bc.perf_stats(df["r_strat"], df["r_cash"])[stat]
    vals = vals[np.isfinite(vals)]
    return {
        "stat": stat,
        "real": float(real_stat),
        "placebo_mean": float(vals.mean()),
        "placebo_q95": float(np.percentile(vals, 95)),
        "quantile": float((vals < real_stat).mean()),
        "p_one_sided": float((vals >= real_stat).mean()),
        "n_placebo": int(len(vals)),
        "time_in_market": float(share),
    }


# ---------------------------------------------------------------------------
# Deflated Sharpe ratio (Bailey & Lopez de Prado 2014)
# ---------------------------------------------------------------------------

_EULER = 0.5772156649015329


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] over n_trials i.i.d. trials with Sharpe variance var_sr (per period)."""
    if n_trials <= 1:
        return 0.0
    z1 = sps.norm.ppf(1 - 1 / n_trials)
    z2 = sps.norm.ppf(1 - 1 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe(
    ret: pd.Series,
    n_trials: int,
    rf: pd.Series | None = None,
    var_sr: float | None = None,
) -> dict:
    """Probability the observed Sharpe exceeds the max expected from n_trials noise.

    Works on per-period (daily) Sharpe; `var_sr` is the cross-trial variance of
    per-period Sharpe (defaults to the sampling variance of this trial's SR).
    """
    x = ret.dropna()
    if rf is not None:
        x = x - rf.reindex(x.index).fillna(0.0)
    T = len(x)
    sd = x.std()
    sr = float(x.mean() / sd) if sd > 0 else float("nan")
    skew = float(sps.skew(x)) if T > 2 else 0.0
    kurt = float(sps.kurtosis(x, fisher=False)) if T > 3 else 3.0
    if var_sr is None:
        var_sr = (1 - skew * sr + (kurt - 1) / 4 * sr**2) / max(T - 1, 1)
    sr0 = expected_max_sharpe(n_trials, var_sr)
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    z = (sr - sr0) * math.sqrt(max(T - 1, 1)) / denom
    return {
        "sr_daily": sr,
        "sr_annual": sr * math.sqrt(ANN),
        "sr0_daily": sr0,
        "n_trials": int(n_trials),
        "T": int(T),
        "skew": skew,
        "kurt": kurt,
        "dsr": float(sps.norm.cdf(z)),
        "passes": bool(sps.norm.cdf(z) >= DSR_MIN),
    }


# ---------------------------------------------------------------------------
# Cost sensitivity
# ---------------------------------------------------------------------------


def cost_sensitivity(
    px: pd.DataFrame,
    signal: pd.Series,
    cash: pd.Series,
    bps_list=(0, 5, 10, 25, 50),
    execution: str = "next_close",
    rebalance: str = "monthly",
) -> pd.DataFrame:
    """Sharpe / CAGR / MaxDD of the strategy at several one-way cost levels."""
    rows = {}
    for bps in bps_list:
        df = bc.backtest_signal(px, signal, cash, bps, execution, None, rebalance)
        st = bc.perf_stats(df["r_strat"], df["r_cash"])
        rows[bps] = {
            "Sharpe": st["Sharpe"],
            "CAGR": st["CAGR"],
            "Max DD": st["Max DD"],
            "turnover_pa": float(df["turnover"].sum() / (len(df) / ANN)),
        }
    out = pd.DataFrame(rows).T
    out.index.name = "cost_bps"
    return out


def breakeven_cost_bps(
    px: pd.DataFrame,
    signal: pd.Series,
    cash: pd.Series,
    bench_sharpe: float,
    execution: str = "next_close",
    rebalance: str = "monthly",
    hi: float = 200.0,
) -> float:
    """One-way cost (bps) at which the strategy Sharpe equals ``bench_sharpe``.

    Bisection on [0, hi]; returns 0 if already below the benchmark at zero cost
    and ``hi`` if still above it at ``hi`` bps.
    """

    def sh(bps):
        df = bc.backtest_signal(px, signal, cash, bps, execution, None, rebalance)
        return bc.perf_stats(df["r_strat"], df["r_cash"])["Sharpe"]

    lo = 0.0
    if sh(lo) <= bench_sharpe:
        return 0.0
    if sh(hi) > bench_sharpe:
        return hi
    for _ in range(20):
        mid = (lo + hi) / 2
        if sh(mid) > bench_sharpe:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 1)


# ---------------------------------------------------------------------------
# Primary metric and pass/fail criteria (FROZEN)
# ---------------------------------------------------------------------------

CRITERIA = {
    "metric": "excess-return Sharpe, net of costs",
    "beat_benchmarks_in": ("dev", "val"),
    "benchmarks": ("sma200", "bh"),
    "bootstrap_vs": "sma200",
    "p_max": P_MAX,
    "dsr_min": DSR_MIN,
    "holdout": "confirmatory: d_sma200 > 0",
    "n_boot": N_BOOT,
    "block_days": BLOCK_DAYS,
    "seed": SEED,
}


@dataclass
class PrimaryResult:
    sharpe: dict[str, float] = field(default_factory=dict)
    d_sma200: dict[str, float] = field(default_factory=dict)
    d_bh: dict[str, float] = field(default_factory=dict)
    p_vs_sma200: dict[str, float] = field(default_factory=dict)
    dsr: float = float("nan")
    n_trials: int = 1
    checks: dict[str, bool] = field(default_factory=dict)
    evidence_version: str = "legacy"
    dsr_full: float = float("nan")

    @property
    def passes(self) -> bool:
        """All hard criteria; the holdout check is confirmatory and excluded."""
        return all(v for k, v in self.checks.items() if not k.startswith("holdout"))

    @property
    def holdout_confirms(self) -> bool:
        return bool(self.checks.get("holdout_d_sma200_pos", False))

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Sharpe": self.sharpe,
                "d_sma200": self.d_sma200,
                "d_bh": self.d_bh,
                "p_vs_sma200": self.p_vs_sma200,
            }
        )

    def row(self) -> dict:
        out = {"dsr": self.dsr, "n_trials": self.n_trials, "passes": self.passes}
        if self.evidence_version == "matched-v1":
            out.update(
                evidence_version=self.evidence_version,
                dsr_full=self.dsr_full,
                dsr_sample="dev+val",
            )
        for p, v in self.sharpe.items():
            out[f"sharpe_{p}"] = v
        for p, v in self.d_sma200.items():
            out[f"d_sma200_{p}"] = v
        for p, v in self.p_vs_sma200.items():
            out[f"p_{p}"] = v
        return out


def _finite_execution_sample(frame):
    """Missing/empty/nonfinite execution evidence must not qualify a hard gate."""
    return (
        isinstance(frame, pd.DataFrame)
        and len(frame) >= 2
        and {"r_strat", "r_cash"}.issubset(frame.columns)
        and np.isfinite(frame[["r_strat", "r_cash"]].to_numpy()).all()
    )


def _pre_holdout_sample(runs):
    """Validate chronology without sorting or deduplicating away bad evidence."""
    periods = {}
    for name in ("dev", "val", "holdout"):
        frame = runs.get(name)
        if frame is None or frame.empty:
            continue
        idx = frame.index
        if (
            not isinstance(idx, pd.DatetimeIndex)
            or idx.hasnans
            or not idx.is_unique
            or not idx.is_monotonic_increasing
        ):
            raise ValueError("matched-v1 periods must be chronological and unique")
        periods[name] = frame
    names = [name for name in ("dev", "val", "holdout") if name in periods]
    for left, right in zip(names, names[1:]):
        if periods[left].index[-1] >= periods[right].index[0]:
            raise ValueError(
                "matched-v1 periods must be chronological and nonoverlapping"
            )
    if not all(_finite_execution_sample(runs.get(p)) for p in ("dev", "val")):
        return None
    return pd.concat([runs["dev"], runs["val"]])


def primary_metric(
    runs: dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    n_trials: int = 1,
    n_boot: int = N_BOOT,
    block: int = BLOCK_DAYS,
    rng: np.random.Generator | None = None,
    *,
    evidence_version: str = "legacy",
) -> PrimaryResult:
    """Evaluate runs against frozen criteria; legacy retains full-sample DSR.

    Opt-in matched-v1 gates DSR on concatenated DEV+VAL execution returns only.
    Missing/invalid samples fail closed; unordered or overlapping periods raise
    ValueError. Full-sample DSR is descriptive only; the estimator is unchanged.
    """
    _validate_evidence_version(evidence_version)
    matched = evidence_version == "matched-v1"
    train = _pre_holdout_sample(runs) if matched else None
    rng = rng or np.random.default_rng(SEED)
    res = PrimaryResult(n_trials=n_trials, evidence_version=evidence_version)
    for name, bt in runs.items():
        if matched and not _finite_execution_sample(bt):
            continue
        b = bench.reindex(bt.index)
        s = excess_sharpe(bt["r_strat"], bt["r_cash"])
        res.sharpe[name] = s
        res.d_sma200[name] = s - excess_sharpe(b["sma200"], b["tbill"])
        res.d_bh[name] = s - excess_sharpe(b["bh"], b["tbill"])
        if name in ("dev", "val"):
            boot = sharpe_diff_bootstrap(
                bt["r_strat"], b["sma200"], bt["r_cash"], n_boot, block, rng
            )
            res.p_vs_sma200[name] = boot.p_value
    if matched:
        if train is not None:
            res.dsr = deflated_sharpe(train["r_strat"], n_trials, train["r_cash"])[
                "dsr"
            ]
        if _finite_execution_sample(runs.get("full")):
            full = runs["full"]
            res.dsr_full = deflated_sharpe(full["r_strat"], n_trials, full["r_cash"])[
                "dsr"
            ]
    elif "full" in runs:
        full = runs["full"]
        res.dsr = deflated_sharpe(full["r_strat"], n_trials, full["r_cash"])["dsr"]
    for p in CRITERIA["beat_benchmarks_in"]:
        has = p in res.sharpe if matched else p in runs
        res.checks[f"{p}_beats_sma200"] = has and res.d_sma200[p] > 0
        res.checks[f"{p}_beats_bh"] = has and res.d_bh[p] > 0
        res.checks[f"{p}_p_le_{P_MAX}"] = has and res.p_vs_sma200[p] <= P_MAX
    res.checks[f"dsr_ge_{DSR_MIN}"] = bool(res.dsr >= DSR_MIN)
    res.checks["holdout_d_sma200_pos"] = (
        "holdout" in res.sharpe if matched else "holdout" in runs
    ) and res.d_sma200["holdout"] > 0
    return res


def passes_criteria(res: PrimaryResult) -> bool:
    return res.passes


__all__ = [
    "N_BOOT",
    "BLOCK_MONTHS",
    "BLOCK_DAYS",
    "NW_LAGS",
    "SEED",
    "P_MAX",
    "DSR_MIN",
    "CRITERIA",
    "excess_sharpe",
    "BootResult",
    "sharpe_diff_bootstrap",
    "placebo_test",
    "expected_max_sharpe",
    "deflated_sharpe",
    "cost_sensitivity",
    "breakeven_cost_bps",
    "PrimaryResult",
    "primary_metric",
    "passes_criteria",
]
