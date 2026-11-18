"""Point-in-time alignment helpers and a look-ahead sanity test.

Every predictor must be lagged to the date on which its value was actually
available.  ``RELEASE_LAGS`` records conservative publication lags for the
series used by the shortlist; ``pit_align`` applies them to a daily index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

import bt_common as bc

# Conservative publication lag after the period the observation refers to.
# Monthly series: the value for month M is used from the first trading day of
# M + 1 + ``months`` (plus ``days`` extra).  Daily series: shift by ``days``.
RELEASE_LAGS: dict[str, dict] = {
    # FRED macro (monthly, period-end dated)
    "UNRATE": {"months": 0, "days": 7},  # first Friday of next month
    "PAYEMS": {"months": 0, "days": 7},
    "CPIAUCSL": {"months": 0, "days": 15},  # mid next month
    "INDPRO": {"months": 0, "days": 17},
    "GDPC1": {"months": 1, "days": 0},  # quarterly, advance ~1 month
    "SAHMREALTIME": {"months": 0, "days": 7},
    # Shiller monthly data: price averages for month M are known at M-end,
    # earnings carry a longer lag (quarterly reports) -> conservative 1 month
    "SHILLER_CAPE": {"months": 1, "days": 0},
    "SHILLER_PRICE": {"months": 0, "days": 1},
    # Daily market series: known at the close, used next day by ``execution``
    "TB3MS": {"months": 0, "days": 1},
    "DGS10": {"days": 1},
    "BAA": {"days": 1},
    "AAA": {"days": 1},
    "VIX": {"days": 1},
    "VIX3M": {"days": 1},
}


def monthly_to_daily_pit(
    monthly: pd.Series, index: pd.DatetimeIndex, months: int = 0, days: int = 0
) -> pd.Series:
    """Forward-fill a period-dated monthly series onto ``index`` with release lag.

    Observation for month M becomes available on the first ``index`` date that is
    >= first calendar day of M+1 + ``months`` months + ``days`` calendar days.
    """
    m = monthly.dropna()
    avail = (
        m.index.to_period("M").to_timestamp(how="start")
        + pd.offsets.MonthBegin(1 + months)
        + pd.Timedelta(days=days)
    )
    s = pd.Series(m.values, index=avail).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def daily_pit(series: pd.Series, index: pd.DatetimeIndex, days: int = 1) -> pd.Series:
    """Shift a daily series by ``days`` trading days then align to ``index``."""
    s = series.dropna().sort_index()
    s = s.reindex(s.index.union(index)).ffill()
    return s.shift(days).reindex(index)


def pit_align(
    series: pd.Series, index: pd.DatetimeIndex, key: str | None = None, **lag
) -> pd.Series:
    """Align ``series`` to ``index`` using the lag from ``RELEASE_LAGS[key]`` or kwargs."""
    spec = dict(RELEASE_LAGS.get(key, {})) if key else {}
    spec.update(lag)
    if not spec:
        raise KeyError(f"no release lag for {key!r}; pass months=/days=")
    obs = series.dropna().index
    freq = (pd.infer_freq(obs[:12]) or "") if len(obs) >= 3 else ""
    if not freq and len(obs) >= 2 and (obs[1] - obs[0]).days >= 25:
        freq = "M"
    monthly_like = "months" in spec or freq.startswith(
        ("M", "Q", "ME", "QE", "MS", "QS")
    )
    if monthly_like:
        return monthly_to_daily_pit(
            series, index, spec.get("months", 0), spec.get("days", 0)
        )
    return daily_pit(series, index, spec.get("days", 1))


@dataclass
class LookAheadResult:
    sharpe_by_shift: pd.Series  # index = shift in trading days (negative = peeking)
    peek_gain: float  # Sharpe(shift=-k) - Sharpe(shift=0)
    suspicious: bool  # true when peeking does NOT help -> signal may already leak

    def to_frame(self) -> pd.DataFrame:
        return self.sharpe_by_shift.to_frame("Sharpe")


def lookahead_test(
    px: pd.DataFrame,
    signal: pd.Series,
    cash: pd.Series,
    shifts: tuple[int, ...] = (-21, -5, -1, 0, 1, 5, 21),
    cost_bps: float = 5.0,
    execution: str = "next_close",
    rebalance: str = "monthly",
    peek_k: int = 21,
    min_gain: float = 0.05,
) -> LookAheadResult:
    """Shift the signal by ``k`` bars and re-run the backtest.

    A genuinely point-in-time signal should get *better* when allowed to peek
    (negative shift) and *worse* when delayed.  If peeking adds nothing the
    signal is probably already using future information.
    """
    out = {}
    for k in shifts:
        sig = signal.shift(k).reindex(px.index)
        bt = bc.backtest_signal(
            px, sig, cash, cost_bps=cost_bps, execution=execution, rebalance=rebalance
        )
        out[k] = bc.perf_stats(bt["r_strat"], bt["r_cash"])["Sharpe"]
    s = pd.Series(out, name="Sharpe").sort_index()
    gain = float(s.get(-peek_k, np.nan) - s.get(0, np.nan))
    return LookAheadResult(s, gain, bool(np.isfinite(gain) and gain <= min_gain))


def assert_no_future_dates(feature: pd.Series, source: pd.Series, key: str) -> None:
    """Raise if any aligned feature value appears before its source observation date."""
    spec = RELEASE_LAGS[key]
    first_src = source.dropna().index[0]
    first_use = feature.dropna().index[0]
    earliest = (
        first_src
        + pd.DateOffset(months=spec.get("months", 0))
        + pd.Timedelta(days=spec.get("days", 0))
    )
    if first_use < earliest:
        raise AssertionError(
            f"{key}: first use {first_use.date()} precedes release {first_src.date()}+lag"
        )


__all__ = [
    "RELEASE_LAGS",
    "monthly_to_daily_pit",
    "daily_pit",
    "pit_align",
    "LookAheadResult",
    "lookahead_test",
    "assert_no_future_dates",
]
