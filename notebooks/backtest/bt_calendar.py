"""Exchange-calendar helpers (Stage 3 follow-up NS4, audit findings A1-02 / A6-01).

``bt_common.check_days`` and the S06 builder use pandas ``BDay`` (Mon-Fri, no
holidays).  The helpers here derive the exchange calendar from the price index
itself - every weekday between the first and last bar that has no bar is a holiday
- and express month-end / turn-of-month logic in trading days instead of business
days.  Additive: nothing in ``bt_common`` is changed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import bt_common as bc

RULES = ("halloween", "tom", "halloween_or_tom")
WINTER_MONTHS = (11, 12, 1, 2, 3, 4)


def exchange_holidays_from_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Weekdays inside the index span that carry no bar (closed-exchange days)."""
    if len(index) == 0:
        return pd.DatetimeIndex([])
    idx = pd.DatetimeIndex(index).normalize()
    weekdays = pd.bdate_range(idx[0], idx[-1])
    return weekdays.difference(idx)


def trading_day_offset(
    index: pd.DatetimeIndex, holidays=None
) -> pd.offsets.CustomBusinessDay:
    """A 1-trading-day offset that skips weekends and ``holidays``.

    ``holidays`` defaults to the gaps of ``index``; pass an explicit list to cover
    dates after the last bar (the index cannot know future closures).
    """
    if holidays is None:
        holidays = exchange_holidays_from_index(index)
    return pd.offsets.CustomBusinessDay(holidays=list(pd.DatetimeIndex(holidays)))


def check_days_exchange(
    index: pd.DatetimeIndex, rebalance: str, holidays=None
) -> pd.Series:
    """``bt_common.check_days`` with the last bar judged on the exchange calendar.

    Interior bars are identical to ``check_days`` (a period change between
    consecutive bars needs no calendar).  The last bar is a period end only if the
    next *trading* day - skipping weekends and ``holidays`` - starts a new period.
    """
    freq = bc.REBALANCE_FREQ[rebalance]
    if freq is None:
        return pd.Series(True, index=index)
    out = bc.check_days(index, rebalance).copy()
    nxt = index[-1] + trading_day_offset(index, holidays)
    out.iloc[-1] = nxt.to_period(freq) != index[-1].to_period(freq)
    return out


def nth_trading_day(index: pd.DatetimeIndex) -> pd.Series:
    """1-based position of each bar within its calendar month (trading days)."""
    ones = pd.Series(1, index=index)
    return ones.groupby([index.year, index.month]).cumsum()


def is_last_trading_day(index: pd.DatetimeIndex) -> pd.Series:
    """True on the final bar of each calendar month present in ``index``.

    The last bar of the sample counts as a month end only if its month is complete
    on the Mon-Fri calendar (same convention as ``bt_common.check_days``).
    """
    month = pd.Series(index.month, index=index)
    last = month != month.shift(-1)
    last.iloc[-1] = (index[-1] + pd.offsets.BDay(1)).month != index[-1].month
    return last


def desired_calendar(index: pd.DatetimeIndex, rule: str, n_first: int = 3) -> pd.Series:
    """Intended S06 holding flag per trading day on the exchange calendar.

    ``tom`` = last trading day of the month or one of the first ``n_first``;
    ``halloween`` = Nov-Apr; ``halloween_or_tom`` = either.
    """
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}; expected one of {RULES}")
    halloween = np.isin(index.month, WINTER_MONTHS)
    tom = is_last_trading_day(index).values | (nth_trading_day(index).values <= n_first)
    flags = {"halloween": halloween, "tom": tom, "halloween_or_tom": halloween | tom}
    return pd.Series(flags[rule].astype(float), index=index)


def signal_for_lag(desired: pd.Series, lag: int = 2) -> pd.Series:
    """Signal to hand to the engine so that ``target.shift(lag)`` lands on ``desired``.

    ``bt_common.backtest_signal(execution="next_close")`` holds the signal of bar
    t-2 on bar t, so the signal on bar t must be the desired position of bar t+2
    *on the trading calendar*.  The last ``lag`` bars have no future bar and are
    filled with the last known desired value.
    """
    return desired.shift(-lag).ffill()
