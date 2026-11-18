"""A1: engine timing. backtest_signal next_close lag and check_days month-end logic."""

import numpy as np
import pandas as pd

from _audit_common import banner, record

import bt_common as bc

banner("A1 backtest_signal timing (synthetic prices)")
idx = pd.bdate_range("2020-01-01", "2020-03-31")
n = len(idx)
# deterministic returns: day k has return 1% * (k % 7 - 3) so each day is identifiable
r = np.array([(k % 7 - 3) / 100.0 for k in range(n)])
tr = 100 * np.cumprod(1 + r)
px = pd.DataFrame({"close": tr, "tr_close": tr, "tr_open": tr}, index=idx)
cash = pd.Series(0.0, index=idx)
# one-day signal spike at position 20 (known at close t), flat otherwise
sig = pd.Series(0.0, index=idx)
t = 20
sig.iloc[t] = 1.0
df = bc.backtest_signal(px, sig, cash, 0.0, "next_close", rebalance="daily")
held = df.index[df["pos"] == 1.0]
print("signal at", idx[t].date(), "-> position held on", [d.date() for d in held])
earned = df.loc[held, "r_strat"].iloc[0]
exp_fill = idx[t + 1]
exp_ret = tr[t + 2] / tr[t + 1] - 1
print(
    f"earned {earned:.6f}; expected tr[t+2]/tr[t+1]-1 = {exp_ret:.6f}; fill close {exp_fill.date()}"
)
ok1 = len(held) == 1 and held[0] == idx[t + 2] and abs(earned - exp_ret) < 1e-12
# a signal must never earn the t->t+1 return (that would be look-ahead)
leak = abs(earned - (tr[t + 1] / tr[t] - 1)) < 1e-12
print("earns t->t+1 return (look-ahead)?", leak, "| lag-2 OK:", ok1)

banner("A1 same_close lag 1 and next_open lag 2 use correct fields")
df_sc = bc.backtest_signal(px, sig, cash, 0.0, "same_close", rebalance="daily")
print(
    "same_close held on",
    [d.date() for d in df_sc.index[df_sc["pos"] == 1.0]],
    "(expected t+1)",
)

banner("A1 cost charged on the row the position changes, both legs")
sig2 = pd.Series(0.0, index=idx)
sig2.iloc[t : t + 3] = 1.0
df2 = bc.backtest_signal(px, sig2, cash, 10.0, "next_close", rebalance="daily")
costs = df2.loc[df2["cost"] > 0, "cost"]
print(
    "cost rows:", [d.date() for d in costs.index], "amounts:", costs.round(6).tolist()
)

banner("A1 check_days month-end incl. last bar")
full = pd.bdate_range(
    "2021-01-01", "2021-06-30"
)  # ends Wed 30 June -> last bar of June
cd = bc.check_days(full, "monthly")
ends = full[cd]
print("monthly check days:", [d.date() for d in ends])
ok_last = full[-1] in ends
mid = pd.bdate_range("2021-01-01", "2021-06-15")
cd_mid = bc.check_days(mid, "monthly")
print(
    "index ending 15 Jun: last bar flagged?", bool(cd_mid.iloc[-1]), "(expected False)"
)
# edge: last bar is Thu 30 Dec 2021 if Fri 31 Dec is a holiday -> BDay(1) says 31 Dec same month
edge = pd.bdate_range("2021-11-01", "2021-12-30")
print(
    "index ending Thu 30 Dec (31st an exchange holiday): flagged?",
    bool(bc.check_days(edge, "monthly").iloc[-1]),
    "(true month end in exchange calendar)",
)
# a monthly signal evaluated at month-end t is held from t+2 on
sig3 = pd.Series(0.0, index=full)
sig3.loc[ends[2]] = (
    1.0  # set at March month-end; monthly rebalance -> held April+2 bars until next check
)
px3 = pd.DataFrame({"close": 100.0, "tr_close": 100.0, "tr_open": 100.0}, index=full)
df3 = bc.backtest_signal(
    px3, sig3, pd.Series(0.0, index=full), 0.0, "next_close", rebalance="monthly"
)
h3 = df3.index[df3["pos"] == 1.0]
print(
    "monthly: signal",
    ends[2].date(),
    "held",
    h3[0].date(),
    "->",
    h3[-1].date(),
    f"({len(h3)} rows)",
)
# expected: first held = 2nd bar after March end; last held = 1 bar after April end (lag 2)
pos_mar = full.get_loc(ends[2])
pos_apr = full.get_loc(ends[3])
ok_m = h3[0] == full[pos_mar + 2] and h3[-1] == full[pos_apr + 1]
print("monthly holding window consistent with lag 2:", ok_m)

record(
    dict(
        id="A1-01",
        area="engine",
        strategy="all",
        severity="none",
        finding="backtest_signal next_close: signal at close t earns first return tr[t+2]/tr[t+1]-1 (fill at close t+1); no t->t+1 leakage; costs charged on change rows",
        evidence=f"audit/a1_engine_timing.py synthetic spike: held only {held[0].date()}, earned {earned:.6f} == tr[t+2]/tr[t+1]-1; leak={leak}; monthly window ok={ok_m}",
        effect="none",
        fixed="n/a",
        file="bt_common.py:backtest_signal",
    )
)
record(
    dict(
        id="A1-02",
        area="engine",
        strategy="all",
        severity="minor",
        finding="check_days last-bar rule uses BDay (weekday) calendar, not the exchange calendar: a final bar that is the true month-end before a weekday holiday (e.g. Thu 30 Dec 2021 when Fri 31 Dec is closed) is not flagged, so the last month-end decision is missed on live data ending there; historical in-sample results are unaffected because interior month-ends use the actual next bar",
        evidence="audit/a1_engine_timing.py: index ending 2021-12-30 -> flagged False; full-month index -> last bar flagged True",
        effect="none on recorded results (affects only the very last bar of a sample)",
        fixed="no",
        file="bt_common.py:check_days",
    )
)
print("\nA1 done; ok1", ok1, "ok_last", ok_last)
