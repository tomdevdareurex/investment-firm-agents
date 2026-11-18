"""A3 - point-in-time alignment lags (bt_pit) and their use in S02/S03/S09."""

import _audit_common as ac
import numpy as np
import pandas as pd

import bt_long
import bt_pit

px = bt_long.load_long_sp500_tr()
idx = px.index

ac.banner("A3.1 monthly_to_daily_pit: months=k -> first usable date")
m = pd.Series([1.0, 2.0, 3.0], index=pd.period_range("2015-01", "2015-03", freq="M"))
m.index = m.index.to_timestamp(how="start")
for k in (0, 1, 3):
    d = bt_pit.monthly_to_daily_pit(m, idx, months=k)
    first_2 = d[d == 2.0].index[0]
    print(f"months={k}: Feb-2015 value first usable {first_2.date()}")
    exp = pd.Timestamp("2015-03-01") + pd.offsets.MonthBegin(k)
    assert first_2 >= exp and first_2 <= exp + pd.Timedelta(days=4)
d = bt_pit.monthly_to_daily_pit(m, idx, months=0, days=7)
print("months=0, days=7: Feb-2015 first usable", d[d == 2.0].index[0].date())

ac.banner("A3.2 daily_pit on union index (S09 VIX/VIX3M ratio)")
vix, vix3m = bt_long.fred_series("VIXCLS"), bt_long.fred_series("VXVCLS")
ratio = (vix / vix3m).dropna()
pit = bt_pit.daily_pit(ratio, idx, days=1)
sub = idx[idx >= ratio.index[0]]
union = ratio.index.union(sub)
extra_ratio_days = ratio.index.difference(idx)
extra_px_days = sub.difference(ratio.index)
print(
    "ratio days not in px index:",
    len(extra_ratio_days),
    list(extra_ratio_days[:5].date),
)
print("px days without ratio    :", len(extra_px_days), list(extra_px_days[:8].date))
# reference: value used on px day t must be the ratio of the previous *px* day (ffilled)
ref = ratio.reindex(sub).ffill().shift(1)
diff = (pit.reindex(sub) - ref).abs()
bad = diff[diff > 1e-12].dropna()
print("px days where daily_pit != ratio of previous px trading day:", len(bad))
if len(bad):
    print(bad.head(10))
    for t in bad.index[:3]:
        pos = union.get_loc(t)
        print(
            t.date(),
            "union prev =",
            union[pos - 1].date(),
            "px prev =",
            sub[sub.get_loc(t) - 1].date(),
        )
# leak check: does the value used on t ever equal the raw ratio dated t when it changed?
same_day = ((pit.reindex(sub) - ratio.reindex(sub)).abs() < 1e-12) & (
    ratio.reindex(sub).diff().abs() > 1e-12
)
print(
    "days where pit value == same-day raw ratio (after a change):", int(same_day.sum())
)
ac.banner("A3.3 UNRATE first-Friday release vs S02/S03 LAG (months=0, days=7)")
months = pd.period_range("1948-01", "2025-12", freq="M")
rows = []
for p in months:
    nxt = (p + 1).to_timestamp(how="start")
    # first Friday of M+1 (BLS Employment Situation schedule; ignores shutdown delays)
    first_fri = nxt + pd.Timedelta(days=(4 - nxt.weekday()) % 7)
    usable = idx[idx >= nxt + pd.Timedelta(days=7)]
    usable = usable[0] if len(usable) else pd.NaT
    rows.append((p, first_fri, usable))
df = pd.DataFrame(rows, columns=["month", "first_friday", "first_usable"]).set_index(
    "month"
)
gap = (df.first_usable - df.first_friday).dt.days
print(
    "gap (first_usable - first_friday) days: min",
    gap.min(),
    "median",
    gap.median(),
    "max",
    gap.max(),
)
print("months where usable date <= release date:", int((gap <= 0).sum()))
print("months where usable == release + 1 day:", int((gap == 1).sum()))

ac.banner(
    "A3.4 Moody's BAA/AAA monthly average: known at end of M -> M+1+7d conservative"
)
baa = bt_long.fred_series("BAA")
print("BAA index sample:", list(baa.index[:3].date), "freq monthly, dated 1st of month")
d = bt_pit.monthly_to_daily_pit(baa, idx, months=0, days=7)
chg = d[d.diff().abs() > 0].index
print(
    "BAA changes applied on px dates (first 3):",
    list(chg[:3].date),
    "-> all >= 8th:",
    bool((chg.day >= 8).all()),
)

ac.record(
    id="A3-01",
    area="pit",
    strategy="S01,S02,S03,S08,S10",
    severity="none",
    finding="monthly_to_daily_pit(months=k, days=d) makes month M usable from the first index date >= 1st of M+1+k plus d days; months=1 => from 1st of M+2 as documented.",
    evidence="audit/a3_pit_lags.py A3.1: Feb-2015 value first usable 2015-03-02 (k=0), 2015-04-01 (k=1), 2015-06-01 (k=3), 2015-03-09 (k=0,d=7).",
    effect="none; semantics match the docstring and the builders' LAG comments",
    fixed="n/a",
    file="bt_pit.py:monthly_to_daily_pit",
)
ac.record(
    id="A3-02",
    area="pit",
    strategy="S09",
    severity="none",
    finding="daily_pit(days=1) shifts on the union index; because every FRED VIXCLS/VXVCLS date is also an S&P trading day, the effective lag is exactly one trading day for the S09 ratio.",
    evidence="audit/a3_pit_lags.py A3.2: 0 ratio dates outside px index; 0 px dates where the value used differs from the previous px-day ratio; 0 same-day leaks.",
    effect="none for S09. Latent risk: a daily series with dates not in the price index (e.g. a 7-day crypto series) would get <1 trading-day lag - documented, not exploited here.",
    fixed="n/a",
    file="bt_pit.py:daily_pit",
)
ac.record(
    id="A3-03",
    area="pit",
    strategy="S02,S03",
    severity="minor",
    finding="LAG months=0 days=7 makes UNRATE for month M usable from >= the 8th of M+1. The BLS Employment Situation is published on the first Friday of M+1 (1st-7th), so the margin is >=1 calendar day in every scheduled month, but it does not cover shutdown-delayed releases (e.g. Sep-2013 report on 2013-10-22) or pre-1960s release practice, which were not verified offline.",
    evidence="audit/a3_pit_lags.py A3.3: usable-minus-first-Friday gap min/median computed over 1948-2025; 0 months with usable<=release under the scheduled calendar.",
    effect="at most a handful of months with a 0-2 week early signal in delayed-release episodes; S03 fails by a wide margin (dev p 0.99) so no verdict impact. BAA/AAA monthly averages are known at month-end, so the same lag is conservative for S02.",
    fixed="no",
    file="macro/build_s02.py:LAG, macro/build_s03.py:LAG",
)
print("recorded A3-01..A3-03")
ac.record(
    id="A3-04",
    area="pit",
    strategy="S03",
    severity="minor",
    finding="S03 'comp' variants build the Sahm rule from current-vintage UNRATE (FRED, revised seasonal factors), not from first-release data; only the 'rt' variants use SAHMREALTIME. Revisions are small (typically 0.1pp) but systematic smoothing makes the current-vintage rule cleaner than what was knowable.",
    evidence="macro/build_s03.py variants + bt_long.fred_series('UNRATE') (single vintage); documented in the notebook caveats.",
    effect="direction: favours S03 comp variants; S03 fails by a wide margin (dev Sharpe 0.34 vs 0.64), so no verdict change.",
    fixed="no",
    file="macro/build_s03.py",
)
print("recorded A3-04")
