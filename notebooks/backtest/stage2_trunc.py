"""Release-aware truncation test (Stage 3, NS3; audit finding A5-01).

``stage2.truncation_test`` cuts monthly inputs as soon as the month has *ended*.
That rule coincides with a zero-release-lag signal, so a signal that uses month
M's value on the first trading day of M+1 is reproduced identically after
truncation and the missing publication lag goes undetected.

This module adds, without touching ``stage2``:

* ``truncate_inputs_release`` - keeps only observations whose *release date* is
  on or before the cut (monthly: first day of M+1 + ``months`` + ``days``, the
  ``bt_pit.monthly_to_daily_pit`` convention; daily: observation date +
  ``days`` business days, the ``bt_pit.daily_pit`` convention);
* ``release_window_cuts`` - cut dates placed between a month's end and its
  declared release, where a missing lag is visible;
* ``truncation_test_release`` - the test itself (same ``TruncResult`` type).

A signal that uses data no earlier than its declared release passes; one that
uses it earlier mismatches on the window cuts.  Still blind to data revisions
(single vintage) and to lags declared too short in ``lags`` itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import bt_pit
import bt_stats as bs
import stage2 as s2

Lag = dict[str, int]


def resolve_lag(spec) -> Lag:
    """``{"months": m, "days": d}`` from a dict, a ``RELEASE_LAGS`` key or None."""
    if spec is None:
        return {"months": 0, "days": 0}
    if isinstance(spec, str):
        spec = bt_pit.RELEASE_LAGS[spec]
    return {"months": int(spec.get("months", 0)), "days": int(spec.get("days", 0))}


def monthly_release_dates(index, lag: Lag) -> pd.DatetimeIndex:
    """Release date of each monthly observation (period- or timestamp-dated)."""
    if isinstance(index, pd.PeriodIndex):
        start = index.to_timestamp(how="start")
    else:
        start = pd.DatetimeIndex(index).to_period("M").to_timestamp(how="start")
    return (
        start
        + pd.offsets.MonthBegin(1 + lag["months"])
        + pd.Timedelta(days=lag["days"])
    )


def truncate_inputs_release(inputs: dict, cut, lags: dict | None = None) -> dict:
    """Inputs as *released* by the close of ``cut``.

    ``lags`` maps input key -> lag spec (dict, ``RELEASE_LAGS`` key or None).
    Keys absent from ``lags`` fall back to ``stage2.truncate_inputs`` semantics
    (daily <= cut; monthly: month has ended).
    """
    cut = pd.Timestamp(cut)
    lags = lags or {}
    base = s2.truncate_inputs(inputs, cut)
    out = {}
    for key, val in inputs.items():
        if key not in lags or not isinstance(val, (pd.Series, pd.DataFrame)):
            out[key] = base[key]
            continue
        lag = resolve_lag(lags[key])
        idx = val.index
        if isinstance(idx, pd.PeriodIndex) or s2._is_monthly(val):
            keep = monthly_release_dates(idx, lag) <= cut
        else:
            keep = idx <= cut - pd.offsets.BDay(lag["days"])
        out[key] = val[np.asarray(keep)]
    return out


def release_window_cuts(
    inputs: dict,
    lags: dict,
    index: pd.DatetimeIndex,
    n_cuts: int = 30,
    seed: int = bs.SEED,
) -> pd.DatetimeIndex:
    """Cut dates where a missing release lag would be visible.

    For every monthly input in ``lags``, candidate cuts are the ``index`` dates
    strictly after the month end and strictly before the declared release date
    (release-day cuts are excluded: on that day the value is legitimately known).
    For daily inputs with ``days`` > 0 every ``index`` date qualifies.  A random
    subset of size ``n_cuts`` is returned, sorted.
    """
    cands = []
    for key, spec in lags.items():
        val = inputs.get(key)
        if not isinstance(val, (pd.Series, pd.DataFrame)):
            continue
        lag = resolve_lag(spec)
        idx = val.dropna().index if isinstance(val, pd.Series) else val.index
        if isinstance(idx, pd.PeriodIndex) or s2._is_monthly(val):
            rel = monthly_release_dates(idx, lag)
            start = monthly_release_dates(idx, {"months": 0, "days": 0})
            for a, b in zip(start, rel):
                if b > a:
                    win = index[(index >= a) & (index < b)]
                    cands.extend(win.tolist())
        elif lag["days"] > 0:
            cands.extend(index.tolist())
    cands = pd.DatetimeIndex(sorted(set(cands)))
    cands = cands[(cands > index[0]) & (cands < index[-1])]
    if len(cands) <= n_cuts:
        return cands
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(cands), size=n_cuts, replace=False))
    return cands[pick]


def truncation_test_release(
    build_signal,
    inputs: dict,
    lags: dict,
    n_cuts: int = 30,
    cut_dates=None,
    tol: float = 1e-9,
    seed: int = bs.SEED,
    **params,
) -> s2.TruncResult:
    """``stage2.truncation_test`` with release-aware truncation and cut dates.

    ``build_signal(inputs, **params)`` must return the daily signal on
    ``inputs["px"].index``.  Inputs are cut by *release date* (``lags``), and
    cuts default to dates inside the month-end -> release window.  A signal that
    consumes a value before its declared release mismatches; one that respects
    the lag passes.  Cuts where the full signal is NaN are skipped.
    """
    full = build_signal(inputs, **params)
    index = inputs["px"].index
    if cut_dates is None:
        cut_dates = release_window_cuts(inputs, lags, index, n_cuts=n_cuts, seed=seed)
    mism, max_diff = [], 0.0
    for cut in cut_dates:
        part = build_signal(truncate_inputs_release(inputs, cut, lags), **params)
        a = full.get(cut, np.nan)
        b = part.get(cut, np.nan) if len(part) else np.nan
        if pd.isna(a) and pd.isna(b):
            continue
        if pd.isna(a) or pd.isna(b):
            mism.append((cut, a, b))
            max_diff = np.inf
            continue
        d = abs(float(a) - float(b))
        max_diff = max(max_diff, d)
        if d > tol:
            mism.append((cut, a, b))
    return s2.TruncResult(len(cut_dates), len(mism), float(max_diff), mism)


__all__ = [
    "Lag",
    "resolve_lag",
    "monthly_release_dates",
    "truncate_inputs_release",
    "release_window_cuts",
    "truncation_test_release",
]
