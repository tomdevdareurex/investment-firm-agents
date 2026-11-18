"""Build macro/credit_term_spread.ipynb (S02). Usage: python build_s02.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S02 - Credit and term spreads (macro / credit)

**Hypothesis.** Widening corporate credit spreads signal rising default risk and tighter
financing conditions, which tend to precede equity drawdowns; an inverted yield curve
predicts recessions. Holding T-bills while credit spreads widen (or the curve is inverted)
should avoid part of the bear markets that SMA200 catches late.

| Rule | Risk-on (hold S&P 500) when ... |
|---|---|
| credit_ma6 / credit_ma12 | BAA - AAA spread <= its 6 / 12-month moving average |
| term_pos | AAA - TB3MS > 0 (curve not inverted) |
| credit12_and_term | both of the above (k = 12) |

**Inputs and point-in-time lags**

| Series | Source | Start | Lag used |
|---|---|---|---|
| BAA, AAA Moody's corporate yields, monthly averages | FRED `BAA`, `AAA` | 1919 | month M usable from M+1 + 7 days |
| 3-month T-bill, monthly average | FRED `TB3MS` | 1934 | month M usable from M+1 + 7 days |
| S&P 500 total return, T-bills | `bt_long.long_sample` | 1934 | daily, decide at close, next-close fill |

Long rate = Moody's AAA (not Shiller's pre-1953 long rate, which is interpolated from annual
data). Monthly check, next-close execution, 5 bp per switch: identical to the SMA200 benchmark.

**Sources.** Fama & French (1989), *Business conditions and expected returns*,
doi:10.1016/0304-405X(89)90095-0; Estrella & Mishkin (1996), *The yield curve as a predictor
of U.S. recessions*, NBER w5379; Gilchrist & Zakrajsek (2012), *Credit spreads and business
cycle fluctuations*, AER doi:10.1257/aer.102.4.1692. Data: https://fred.stlouisfed.org
(FRED terms of use apply).

> Decision-support research only; never places orders."""

DATA = """baa, aaa, tb3 = (bt_long.fred_series(s) for s in ("BAA", "AAA", "TB3MS"))
inputs = {"px": px, "baa": baa, "aaa": aaa, "tb3": tb3}
print("BAA/AAA", baa.index[0].date(), "->", baa.index[-1].date(), "| TB3MS", tb3.index[0].date(), "->", tb3.index[-1].date())
display(pd.DataFrame({"credit (BAA-AAA)": baa - aaa, "term (AAA-TB3MS)": aaa - tb3}).tail(4))"""

SIGNAL = """LAG = dict(months=0, days=7)  # monthly average for M known early M+1; 7-day margin


def build_signal(inputs, rule="credit", k=12):
    credit = (inputs["baa"] - inputs["aaa"]).dropna()
    term = (inputs["aaa"] - inputs["tb3"]).dropna()
    ma = credit.rolling(k).mean()
    credit_on = (credit <= ma).astype(float).where(ma.notna())
    term_on = (term > 0).astype(float).where(term.notna())
    monthly = {"credit": credit_on, "term": term_on, "both": credit_on * term_on}[rule]
    return bt_pit.monthly_to_daily_pit(monthly, inputs["px"].index, **LAG)


VARIANTS = {
    "credit_ma6": dict(rule="credit", k=6),
    "credit_ma12": dict(rule="credit", k=12),
    "term_pos": dict(rule="term"),
    "credit12_and_term": dict(rule="both", k=12),
}
PARAMS_TEXT = {n: f"{n}; FRED BAA/AAA/TB3MS monthly, lag M+1+7d; monthly; next_close; 5bp" for n in VARIANTS}"""

CHART = """credit = baa - aaa
fig = go.Figure()
fig.add_trace(go.Scatter(x=credit.index, y=credit, name="BAA - AAA (pp)"))
fig.add_trace(go.Scatter(x=credit.index, y=credit.rolling(12).mean(), name="12-month MA", line=dict(dash="dash")))
fig.add_trace(go.Scatter(x=aaa.index, y=aaa - tb3, name="AAA - TB3MS (pp)", yaxis="y2", opacity=0.6))
fig.update_layout(title="Credit and term spreads", height=420, legend=dict(orientation="h"),
                  yaxis2=dict(overlaying="y", side="right", title="term"))
fig.show()"""

CAVEATS = """* Monthly averages: the signal reacts with up to ~5 weeks' delay (month average + release lag).
* AAA - TB3MS is a corporate-curve proxy for the Treasury term spread; it inverts less often.
* Moody's index composition has changed over time; FRED values are not revised in practice.
* Only four variants were tried, all registered; the best dev variant is evaluated once."""

SPEC = dict(
    trial_id="S02",
    strategy="credit_term_spread",
    folder="macro",
    name="credit_term_spread",
    title="S02",
    protocol="main",
    rebalance="monthly",
    header_md=HEADER,
    data_code=DATA,
    signal_code=SIGNAL,
    chart_code=CHART,
    caveats_md=CAVEATS,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
