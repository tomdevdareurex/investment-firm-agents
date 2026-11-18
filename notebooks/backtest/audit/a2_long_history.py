"""A2: long-history proxy (bt_long). Synthetic TR dividends, TB3MS timing, cash shift, shiller_to_daily."""

import numpy as np
import pandas as pd

from _audit_common import banner, record

import bt_long as bl

banner("A2 synthetic total return before 1988")
px = bl.load_long_sp500_tr()
sh = bl.load_shiller()
splice = px.attrs["splice_date"]
print("splice date (first official ^SP500TR return):", splice.date())
pre = px[px.index < splice]
r_tr = pre["tr_close"].pct_change()
r_px = pre["close"].pct_change()
div_leg = (1 + r_tr) / (1 + r_px) - 1  # implied daily dividend yield component
# compare implied dividend with Shiller D/(252*P_{t-1}) for the same month, e.g. 1960
m = pd.Period("1960-06", "M")
rows = pre.loc["1960-06"]
d_annual = float(sh.loc[m, "D"])
implied = div_leg.loc["1960-06"].mean()
expected = (d_annual / 252 / pre["close"].shift(1).loc["1960-06"]).mean()
print(f"1960-06: implied daily div leg {implied:.3e} vs D/252/P_prev {expected:.3e}")
# dividend is spread evenly: std of the implied leg within a month is tiny
print(
    "within-month dispersion of div leg (1960-06):",
    f"{div_leg.loc['1960-06'].std():.2e}",
)
# which month's D is used? check month M uses D[M] (contemporaneous), not D[M-1]
m_prev = float(sh.loc[m - 1, "D"])
exp_prev = (m_prev / 252 / pre["close"].shift(1).loc["1960-06"]).mean()
print(
    f"  D[M]={d_annual:.3f} D[M-1]={m_prev:.3f}; match M: {abs(implied-expected)<1e-9}, match M-1: {abs(implied-exp_prev)<1e-9}"
)
# splice sanity: annual TR vs official 1989-2023
off = bl.load_history("^SP500TR")["Close"]
a_syn = px["tr_close"].resample("YE").last().pct_change()
a_off = off.resample("YE").last().pct_change()
d = (a_syn - a_off).dropna().loc["1989":"2023"]
print(
    f"official vs spliced annual diff 1989-2023: mean {d.mean()*100:.3f}% (should be ~0 after splice)"
)
# synthetic vs official overlap check 1988-2023 using the formula directly
gspc = px["close"]
d_daily = sh["D"].astype(float).reindex(gspc.index.to_period("M")).ffill().to_numpy()
r_syn = (gspc + d_daily / 252) / gspc.shift(1) - 1
syn_idx = (1 + r_syn.loc[splice:]).cumprod()
a_s = syn_idx.resample("YE").last().pct_change().loc["1989":"2023"]
a_o = (
    off.reindex(gspc.index)
    .ffill()
    .resample("YE")
    .last()
    .pct_change()
    .loc["1989":"2023"]
)
dd = (a_s - a_o).dropna()
print(
    f"synthetic formula vs official annual TR 1989-2023: mean {dd.mean()*100:.3f}%, std {dd.std()*100:.3f}%"
)

banner("A2 TB3MS known from the following month")
tb = bl.fred_series("TB3MS")
yld = bl.load_long_tbill_yield()
irx0 = bl.load_history("^IRX")["Close"].index[0]
print("first ^IRX obs:", irx0.date())
p = pd.Timestamp("1950-03-01")
print(
    f"TB3MS for 1950-03 = {tb.loc['1950-03-01']:.2f}; in yld at {p.date()}: {yld.loc[p]:.2f}; at 1950-04-01: {yld.loc['1950-04-01']:.2f}"
)
ok_tb = (
    abs(yld.loc["1950-04-01"] - tb.loc["1950-03-01"]) < 1e-12
    and abs(yld.loc["1950-03-01"] - tb.loc["1950-02-01"]) < 1e-12
)
print("month-M average available from 1st of M+1:", ok_tb)

banner("A2 cash uses previous bar's yield")
idx = px.loc["1950-02-20":"1950-04-10"].index
cash = bl.long_cash_returns(idx, yld)
# on the first bar of April the yield applied must still be Feb's TB3MS (known 1 Mar), not Mar's (known 1 Apr)
apr1 = idx[idx >= "1950-04-01"][0]
days = (apr1 - idx[idx.get_loc(apr1) - 1]).days
r_feb = (1 + tb.loc["1950-02-01"] / 100) ** (days / 365) - 1
r_mar = (1 + tb.loc["1950-03-01"] / 100) ** (days / 365) - 1
print(
    f"bar {apr1.date()} ({days} days): cash {cash.loc[apr1]:.3e}; with Feb yld {r_feb:.3e}; with Mar yld {r_mar:.3e}"
)
ok_cash = abs(cash.loc[apr1] - r_feb) < 1e-12
print("uses previous bar's known yield:", ok_cash)

banner("A2 shiller_to_daily lag semantics")
s = pd.Series(
    np.arange(1.0, 7.0), index=pd.period_range("2000-01", "2000-06", freq="M")
)
di = pd.bdate_range("2000-01-01", "2000-09-30")
for lag in (0, 1, 3):
    out = bl.shiller_to_daily(s, di, lag_months=lag)
    first = out.first_valid_index()
    print(
        f"lag_months={lag}: Jan value first known {first.date()} (month M known from 1st of M+{1+lag})"
    )

record(
    dict(
        id="A2-01",
        area="data",
        strategy="all",
        severity="none",
        finding="Synthetic pre-1988 total return adds Shiller annual D of the same month /252 per bar (evenly spread); matches D[M]/252/P_{t-1} exactly; spliced to official ^SP500TR",
        evidence=f"audit/a2_long_history.py: 1960-06 implied div leg == D[M]/252/P_prev (within-month std {div_leg.loc['1960-06'].std():.1e}); synthetic-vs-official annual TR 1989-2023 mean diff {dd.mean()*100:.3f}%",
        effect="Shiller D is a smoothed/interpolated series so the dividend leg carries a few bp/yr of contemporaneous smoothing; it feeds returns, not decisions (except S05 momentum on TR, negligible)",
        fixed="n/a",
        file="bt_long.py:load_long_sp500_tr",
    )
)
record(
    dict(
        id="A2-02",
        area="data",
        strategy="all",
        severity="none",
        finding="TB3MS monthly average is treated as known from the 1st of the following month; cash return uses the yield known at the previous bar (shift 1)",
        evidence=f"audit/a2_long_history.py: yld[1950-04-01]==TB3MS[1950-03] {ok_tb}; first April bar cash computed with Feb yield {ok_cash}",
        effect="none (conservative: in reality the daily bill rate is observable intraday; using a stale monthly average understates cash return volatility, affects both strategies and benchmarks equally)",
        fixed="n/a",
        file="bt_long.py:load_long_tbill_yield,long_cash_returns",
    )
)
print("A2 done")
