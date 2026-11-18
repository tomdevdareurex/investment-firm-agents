"""Build seasonality/halloween_tom.ipynb (S06). Usage: python build_s06.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S06 - Halloween and turn-of-the-month seasonality (calendar)

**Hypothesis.** Equity returns are concentrated in November-April ("sell in May", Bouman &
Jacobsen 2002) and around the turn of the month, i.e. the last trading day and the first three of
the next month (Lakonishok & Smidt 1988; McConnell & Xu 2008). Holding equities only in those
windows and T-bills otherwise should earn most of the premium with less time in the market.

| Variant | Hold the S&P 500 on return day d when ... |
|---|---|
| halloween | d falls in November-April |
| tom | d is the last business day of a month or one of the first three of the next |
| halloween_or_tom | November-April, plus the turn-of-month days in May-October |

**Point-in-time.** The rule depends only on the calendar, which is known in advance. The engine
fills at the next close and earns from the following day, so the signal on day t encodes the
desired position for business day t+2 (Mon-Fri calendar; exchange holidays can shift a window by a
day). Daily check, next-close execution, 5 bp per switch (turn-of-month trades ~24 times a year).

**Sources.** Bouman & Jacobsen (2002), *The Halloween indicator*, AER, SSRN 76248; McConnell &
Xu (2008), *Equity returns at the turn of the month*, FAJ, SSRN 917884; Lakonishok & Smidt (1988),
*Are seasonal anomalies real?*, RFS.

> Decision-support research only; never places orders."""

DATA = """inputs = {"px": px}
print("calendar rule on", len(px), "trading days")"""

SIGNAL = """BD = pd.offsets.BDay()


def desired(days, rule):
    month = days.month
    halloween = np.isin(month, [11, 12, 1, 2, 3, 4])
    last = (days + BD).month != month
    start = days.values.astype("datetime64[M]").astype("datetime64[D]")
    nth = np.busday_count(start, days.values.astype("datetime64[D]")) + 1
    tom = last | (nth <= 3)
    return {"halloween": halloween, "tom": tom, "halloween_or_tom": halloween | tom}[rule]


def build_signal(inputs, rule="halloween"):
    idx = inputs["px"].index
    return pd.Series(desired(idx + 2 * BD, rule).astype(float), index=idx)


VARIANTS = {r: dict(rule=r) for r in ("halloween", "tom", "halloween_or_tom")}
PARAMS_TEXT = {n: f"{n}; calendar (Mon-Fri), signal for t+2 bdays; daily; next_close; 5bp" for n in VARIANTS}"""

CHART = """r = px["tr_close"].pct_change(fill_method=None)
by_month = r.groupby(r.index.month).mean() * 21
fig = go.Figure(go.Bar(x=by_month.index, y=by_month, marker_color=["#1f77b4" if m in (11, 12, 1, 2, 3, 4) else "#ff7f0e" for m in by_month.index]))
fig.update_layout(title="Average monthly total return by calendar month, full sample (blue = Nov-Apr)", yaxis_tickformat=".1%", height=340)
fig.show()"""

CAVEATS = """* The chart above uses the whole sample (descriptive only); the rule itself is fixed by the calendar.
* Turn-of-month trading costs ~24 switches a year; the cost table shows how fast the edge erodes.
* Calendar anomalies were widely published in the 1980s-2000s; post-publication decay is expected.
* Mon-Fri calendar without exchange holidays: windows can be off by one trading day."""

SPEC = dict(
    trial_id="S06",
    strategy="halloween_tom",
    folder="seasonality",
    name="halloween_tom",
    title="S06",
    protocol="main",
    rebalance="daily",
    header_md=HEADER,
    data_code=DATA,
    signal_code=SIGNAL,
    chart_code=CHART,
    caveats_md=CAVEATS,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
