"""Deflated Sharpe, version 2 (Stage 3 follow-up; additive, frozen metric untouched).

Why a v2
--------
``bt_stats.deflated_sharpe`` (frozen, PLAN.md section 2) uses the trial's own
sampling variance (~1/T) as the cross-trial variance and tests the *absolute*
Sharpe against the expected maximum of ``n_trials`` pure-noise trials.  With
T ~ 14,000 daily bars the hurdle SR0 is 0.02-0.05 annualised, so almost any
strategy with a positive Sharpe scores DSR ~ 1.0 (audit finding A8-02).  It
therefore answers "is the Sharpe above zero, after a very small multiple-testing
penalty?", not "does it beat the benchmark after the trials we actually ran?".

v2 definitions (both are reported, neither replaces the frozen gate):

* ``deflated_sharpe_vs_benchmark`` - the Bailey & Lopez de Prado DSR applied to
  the *active* return (strategy minus benchmark).  SR0 is built from the
  cross-trial variance of the active Sharpe across the trials registered, and
  the test is "active Sharpe > E[max active Sharpe of n noise trials]".
* ``deflated_sharpe_cross_trial`` - the DSR of the strategy's excess return with
  SR0 built from an externally supplied cross-trial variance (e.g. the spread
  of dev Sharpe across the registry) and a fuller trial count.

Both return the same dict shape as ``bt_stats.deflated_sharpe`` plus the inputs
used, so they can be tabulated side by side.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import scipy.stats as sps

import bt_stats as bs

ANN = bs.ANN
DSR_MIN = bs.DSR_MIN


def _moments(x: pd.Series) -> tuple[float, int, float, float]:
    """Daily Sharpe, T, skew and (non-excess) kurtosis of a return series."""
    x = x.dropna()
    T = len(x)
    sd = x.std(ddof=1)
    sr = float(x.mean() / sd) if (T > 1 and sd > 0) else float("nan")
    skew = float(sps.skew(x)) if T > 2 else 0.0
    kurt = float(sps.kurtosis(x, fisher=False)) if T > 3 else 3.0
    return sr, T, skew, kurt


def _dsr_from(sr: float, T: int, skew: float, kurt: float, sr0: float) -> float:
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    z = (sr - sr0) * math.sqrt(max(T - 1, 1)) / denom
    return float(sps.norm.cdf(z))


def cross_trial_variance(sharpes_annual, min_n: int = 2) -> float:
    """Variance of *daily* Sharpe across trials given annualised Sharpe ratios.

    ``sharpes_annual`` is the list of one Sharpe per distinct trial (e.g. the
    dev-period Sharpe of every registered strategy/parameter trial).  Returns
    NaN when fewer than ``min_n`` values are available.
    """
    s = pd.Series(list(sharpes_annual), dtype=float).dropna()
    if len(s) < min_n:
        return float("nan")
    return float((s / math.sqrt(ANN)).var(ddof=1))


def deflated_sharpe_cross_trial(
    ret: pd.Series,
    n_trials: int,
    var_sr_daily: float,
    rf: pd.Series | None = None,
) -> dict:
    """DSR of the excess return with an external cross-trial Sharpe variance.

    ``var_sr_daily`` is the variance of daily Sharpe across trials (see
    ``cross_trial_variance``).  ``n_trials`` should be the *fuller* count,
    including sweeps run before the registry existed.
    """
    x = ret.dropna()
    if rf is not None:
        x = x - rf.reindex(x.index).fillna(0.0)
    sr, T, skew, kurt = _moments(x)
    if not np.isfinite(var_sr_daily):
        raise ValueError("var_sr_daily must be finite; see cross_trial_variance")
    sr0 = bs.expected_max_sharpe(int(n_trials), float(var_sr_daily))
    dsr = _dsr_from(sr, T, skew, kurt, sr0)
    return {
        "variant": "cross_trial",
        "sr_daily": sr,
        "sr_annual": sr * math.sqrt(ANN),
        "sr0_daily": sr0,
        "sr0_annual": sr0 * math.sqrt(ANN),
        "var_sr_daily": float(var_sr_daily),
        "n_trials": int(n_trials),
        "T": int(T),
        "skew": skew,
        "kurt": kurt,
        "dsr": dsr,
        "passes": bool(dsr >= DSR_MIN),
    }


def deflated_sharpe_vs_benchmark(
    ret: pd.Series,
    bench: pd.Series,
    n_trials: int,
    var_sr_daily: float | None = None,
) -> dict:
    """DSR of the *active* return (strategy minus benchmark).

    Tests whether the Sharpe of ``ret - bench`` exceeds the expected maximum
    active Sharpe of ``n_trials`` noise trials.  ``var_sr_daily`` is the
    cross-trial variance of the daily active Sharpe; when ``None`` the trial's
    own sampling variance is used (the frozen convention), which makes SR0
    tiny but still answers the benchmark-relative question.
    """
    a = (ret - bench.reindex(ret.index)).dropna()
    sr, T, skew, kurt = _moments(a)
    if var_sr_daily is None:
        var_sr_daily = (1 - skew * sr + (kurt - 1) / 4 * sr**2) / max(T - 1, 1)
    sr0 = bs.expected_max_sharpe(int(n_trials), float(var_sr_daily))
    dsr = _dsr_from(sr, T, skew, kurt, sr0)
    return {
        "variant": "vs_benchmark",
        "sr_daily": sr,
        "sr_annual": sr * math.sqrt(ANN),
        "sr0_daily": sr0,
        "sr0_annual": sr0 * math.sqrt(ANN),
        "var_sr_daily": float(var_sr_daily),
        "n_trials": int(n_trials),
        "T": int(T),
        "skew": skew,
        "kurt": kurt,
        "dsr": dsr,
        "passes": bool(dsr >= DSR_MIN),
    }


def score_table(
    runs: dict[str, dict],
    bench: pd.Series,
    rf: pd.Series,
    n_trials_registry: int,
    n_trials_full: int,
    var_cross_daily: float,
    var_active_daily: float | None = None,
) -> pd.DataFrame:
    """Side-by-side v1/v2 deflated Sharpe for several strategies.

    ``runs`` maps strategy id -> daily strategy return series (already cut to
    the period of interest).  ``bench`` and ``rf`` are daily benchmark and cash
    returns on a superset index.  One row per strategy with the frozen v1 DSR,
    the benchmark-relative v2 and the cross-trial v2 at both trial counts.
    """
    rows = []
    for sid, r in runs.items():
        r = r.dropna()
        v1 = bs.deflated_sharpe(r, n_trials_registry, rf)
        vb = deflated_sharpe_vs_benchmark(r, bench, n_trials_full, var_active_daily)
        vx = deflated_sharpe_cross_trial(r, n_trials_registry, var_cross_daily, rf)
        vxf = deflated_sharpe_cross_trial(r, n_trials_full, var_cross_daily, rf)
        rows.append(
            {
                "strategy": sid,
                "sr_annual": v1["sr_annual"],
                "active_sr_annual": vb["sr_annual"],
                "dsr_v1": v1["dsr"],
                "dsr_vs_bench": vb["dsr"],
                "dsr_cross_reg": vx["dsr"],
                "dsr_cross_full": vxf["dsr"],
                "sr0_cross_full_annual": vxf["sr0_annual"],
                "pass_v1": v1["passes"],
                "pass_v2": bool(vb["passes"] and vxf["passes"]),
            }
        )
    return pd.DataFrame(rows).set_index("strategy")


__all__ = [
    "ANN",
    "DSR_MIN",
    "cross_trial_variance",
    "deflated_sharpe_cross_trial",
    "deflated_sharpe_vs_benchmark",
    "score_table",
]
