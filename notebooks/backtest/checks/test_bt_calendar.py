"""Tests for bt_calendar (NS4): exchange-calendar helpers derived from the index."""

import numpy as np
import pandas as pd
import pytest

import bt_calendar as cal
import bt_common as bc


def _index(start="2023-01-02", end="2023-12-29", drop=()):
    idx = pd.bdate_range(start, end)
    return idx.difference(pd.DatetimeIndex(drop))


def test_holidays_detected_from_gaps():
    idx = _index(drop=["2023-07-04", "2023-11-23"])
    hol = cal.exchange_holidays_from_index(idx)
    assert list(hol) == [pd.Timestamp("2023-07-04"), pd.Timestamp("2023-11-23")]
    assert (
        len(
            cal.exchange_holidays_from_index(pd.bdate_range("2023-01-02", "2023-01-31"))
        )
        == 0
    )


def test_trading_day_offset_skips_holiday():
    idx = _index(drop=["2023-07-04"])
    off = cal.trading_day_offset(idx)
    assert pd.Timestamp("2023-07-03") + off == pd.Timestamp("2023-07-05")
    assert pd.Timestamp("2023-07-05") + off == pd.Timestamp("2023-07-06")


def test_check_days_exchange_matches_check_days_without_holidays():
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    for reb in ("monthly", "weekly", "daily"):
        a = bc.check_days(idx, reb)
        b = cal.check_days_exchange(idx, reb)
        pd.testing.assert_series_equal(a, b)


def test_check_days_exchange_last_bar_before_holiday_month_end():
    # 2024-05-31 is a Friday; the sample ends 2024-05-30 (Thu). On the Mon-Fri
    # calendar the 30th is not the month end, but if the 31st is an exchange
    # holiday, the next trading day is 2024-06-03 -> the 30th IS the month end.
    idx = pd.bdate_range("2024-01-01", "2024-05-30")
    assert not bc.check_days(idx, "monthly").iloc[-1]
    assert not cal.check_days_exchange(idx, "monthly").iloc[-1]
    assert cal.check_days_exchange(idx, "monthly", holidays=["2024-05-31"]).iloc[-1]
    # interior flags unchanged
    a = bc.check_days(idx, "monthly").iloc[:-1]
    b = cal.check_days_exchange(idx, "monthly", holidays=["2024-05-31"]).iloc[:-1]
    pd.testing.assert_series_equal(a, b)


def test_nth_and_last_trading_day_on_holiday_month():
    # Drop 2023-11-01 (Wed) and 2023-11-30 (Thu) to perturb both ends of November.
    idx = _index(drop=["2023-11-01", "2023-11-30"])
    nth = cal.nth_trading_day(idx)
    last = cal.is_last_trading_day(idx)
    nov = idx[idx.month == 11]
    assert nth[nov[0]] == 1 and nov[0] == pd.Timestamp("2023-11-02")
    assert nth[pd.Timestamp("2023-11-06")] == 3  # Nov 2, 3, 6
    assert last[pd.Timestamp("2023-11-29")]
    assert not last[pd.Timestamp("2023-11-28")]
    # October's last bar is normal
    assert last[pd.Timestamp("2023-10-31")]


def test_is_last_trading_day_final_bar_convention():
    idx = pd.bdate_range("2023-01-02", "2023-03-31")  # Fri 31 Mar -> next BDay April
    assert cal.is_last_trading_day(idx).iloc[-1]
    idx2 = pd.bdate_range("2023-01-02", "2023-03-30")
    assert not cal.is_last_trading_day(idx2).iloc[-1]


def test_desired_calendar_rules():
    idx = _index(drop=["2023-07-04"])
    tom = cal.desired_calendar(idx, "tom")
    hal = cal.desired_calendar(idx, "halloween")
    both = cal.desired_calendar(idx, "halloween_or_tom")
    assert set(tom.unique()) <= {0.0, 1.0}
    # July: 4th is a holiday, so first three trading days are 3, 5, 6
    assert tom[pd.Timestamp("2023-07-03")] == 1
    assert tom[pd.Timestamp("2023-07-06")] == 1
    assert tom[pd.Timestamp("2023-07-07")] == 0
    assert tom[pd.Timestamp("2023-06-30")] == 1
    assert hal[pd.Timestamp("2023-07-10")] == 0 and hal[pd.Timestamp("2023-11-10")] == 1
    assert (both >= tom).all() and (both >= hal).all()
    with pytest.raises(ValueError):
        cal.desired_calendar(idx, "nope")


def test_signal_for_lag_roundtrips_through_engine_shift():
    idx = _index(drop=["2023-07-04", "2023-11-23", "2023-12-25"])
    desired = cal.desired_calendar(idx, "tom")
    sig = cal.signal_for_lag(desired, 2)
    held = sig.shift(2)
    # exact match everywhere except the first two bars (no prior signal)
    mism = (held.iloc[2:] != desired.iloc[2:]).sum()
    assert mism == 0
    assert held.iloc[:2].isna().all()


def test_signal_for_lag_differs_from_bday_construction_at_holidays():
    """The Mon-Fri BDay construction used by build_s06 mis-times days adjacent to a
    holiday; the trading-calendar construction does not."""
    idx = _index(drop=["2023-11-30"])
    desired = cal.desired_calendar(idx, "tom")
    # replicate build_s06.desired(idx + 2 BDays, "tom") on the Mon-Fri calendar
    days = idx + 2 * pd.offsets.BDay()
    last = (days + pd.offsets.BDay()).month != days.month
    first = (
        np.busday_count(
            days.values.astype("datetime64[M]"), days.values.astype("datetime64[D]")
        )
        + 1
    )
    bday_sig = pd.Series((last | (first <= 3)).astype(float), index=idx)
    bday_held = bday_sig.shift(2)
    cal_held = cal.signal_for_lag(desired, 2).shift(2)
    diff = (bday_held != cal_held) & cal_held.notna()
    # with the exchange closed on Nov 30, Nov 29 is the last trading day of the
    # month: the exchange calendar holds it, the Mon-Fri construction does not
    assert diff[pd.Timestamp("2023-11-29")]
    assert cal_held[pd.Timestamp("2023-11-29")] == 1.0
    assert bday_held[pd.Timestamp("2023-11-29")] == 0.0
    assert diff.sum() <= 2
    assert not diff[idx.month == 3].any()
