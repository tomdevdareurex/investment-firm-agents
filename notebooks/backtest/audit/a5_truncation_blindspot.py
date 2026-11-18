"""A5 - what stage2.truncation_test cannot detect.

The test cuts every input at the close of day c (monthly inputs: only months
that have ENDED by c) and compares the recomputed signal on day c with the
full-sample signal.  It therefore catches full-sample statistics, centred
windows and back-fills.  It is BLIND to a missing *release* lag whenever the
truncation rule itself already applies the correct availability rule: a
monthly value dated month M is kept as soon as M has ended, so a signal that
uses M's value on the first trading day of M+1 (release lag 0) is reproduced
identically after truncation - even though in reality the value is published
weeks later.  Likewise data revisions (vintages) are invisible because only one
vintage exists in the inputs.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import _audit_common as ac

import bt_long
import bt_pit
import stage2 as s2


def main() -> None:
    ac.banner("A5 truncation_test blind spot: missing release lag")
    sample = bt_long.long_sample()
    px = sample["px"]
    shiller = sample["shiller"]
    cape = shiller["CAPE"].dropna()
    cape.index = cape.index.to_timestamp(how="start")
    inputs = {"px": px, "cape": cape}

    def build_lag0(inputs, months=0):
        """Uses month M's CAPE on the first trading day of M+1 (no release lag)."""
        c = inputs["cape"]
        med = c.expanding(min_periods=120).median().shift(1)
        sig = (c < med).astype(float).where(med.notna())
        return bt_pit.monthly_to_daily_pit(
            sig, inputs["px"].index, months=months, days=0
        )

    r0 = s2.truncation_test(build_lag0, inputs, n_cuts=60, months=0)
    r1 = s2.truncation_test(build_lag0, inputs, n_cuts=60, months=1)
    print("lag 0 months (unrealistic):", r0.row())
    print("lag 1 month  (registry)   :", r1.row())

    # Targeted check: a monthly value used BEFORE it could be known
    # (the Shiller monthly file for month M appears early in M+1, so lag-0 use on
    # the 1st trading day of M+1 is ~1-3 weeks early; the test cannot see this).
    ac.banner(
        "A5 targeted check: does the signal on day d use a month that ended < 7 days before d?"
    )
    d = bt_pit.monthly_to_daily_pit(cape, px.index, months=0, days=0)
    first_use = d.groupby(d.values).apply(lambda s: s.index.min())
    month_end = cape.index + pd.offsets.MonthEnd(0)
    gap = pd.Series(first_use.values, index=first_use.index)
    me = pd.Series(month_end, index=cape.values)
    me = me[~me.index.duplicated()]
    joined = pd.concat(
        [gap.rename("first_use"), me.rename("month_end")], axis=1
    ).dropna()
    days_after = (joined["first_use"] - joined["month_end"]).dt.days
    print("months=0: median days between month end and first use:", days_after.median())
    print("share used within 7 days of month end:", round((days_after <= 7).mean(), 3))

    # Revisions blind spot: perturb the LAST value of a monthly input only
    # (a simulated revision) - truncation at earlier cuts never sees it.
    ac.banner("A5 revisions: a late revision is invisible to truncation_test")
    cape_rev = cape.copy()
    cape_rev.iloc[-1] = cape_rev.iloc[-1] * 1.5
    r_rev = s2.truncation_test(
        build_lag0, {"px": px, "cape": cape_rev}, n_cuts=60, months=1
    )
    print("revised last value:", r_rev.row())

    ac.record(
        id="A5-01",
        area="look-ahead/truncation_test",
        strategy="all",
        severity="major",
        finding=(
            "stage2.truncation_test passes a signal that uses month M's value on the first trading "
            "day of M+1 with zero release lag; truncate_inputs applies exactly the same 'month has ended' "
            "rule, so a missing publication lag is undetectable.  It also cannot see data revisions "
            "(single vintage) and only samples completed months."
        ),
        evidence=f"a5_truncation_blindspot.py: lag0 {r0.row()}, lag1 {r1.row()}, revised-last {r_rev.row()}",
        effect=(
            "0 mismatches in every case; the test proves 'no future-month data', not 'realistic availability'. "
            "Release-lag correctness rests on RELEASE_LAGS alone (see A3, A4)."
        ),
        fixed="no",
        file="notebooks/backtest/stage2.py:truncation_test",
    )


if __name__ == "__main__":
    main()
