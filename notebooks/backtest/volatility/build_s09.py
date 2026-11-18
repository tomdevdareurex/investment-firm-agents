"""Build volatility/vix_term_structure.ipynb (S09). Usage: python build_s09.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S09 - VIX term structure (volatility, late-data)

**Hypothesis.** Implied volatility is normally upward-sloping (1-month VIX below 3-month VIX3M).
When the curve inverts (backwardation), the market prices acute near-term stress; such episodes
cluster around crashes. Holding T-bills while VIX / VIX3M is high should avoid the worst days.

| Variant | Risk-on (hold S&P 500) when ... |
|---|---|
| ratio_lt_1.00 | previous day's VIX / VIX3M < 1.00 (contango) |
| ratio_lt_0.95 | previous day's VIX / VIX3M < 0.95 (stricter: de-risk earlier) |

**Inputs and point-in-time lags**

| Series | Source | Start | Lag used |
|---|---|---|---|
| VIX close | FRED `VIXCLS` (Cboe) | 1990 | previous trading day (+1 day) |
| VIX3M close | FRED `VXVCLS` (Cboe) | 2007-12 | previous trading day (+1 day) |

Daily check, next-close execution, 5 bp per switch. **Late-data protocol**: dev = data start..2013
(includes 2008), val 2014-2017, holdout 2018+, separate leaderboard, weaker evidence.

**Sources.** Cboe VIX / VIX3M methodology (https://www.cboe.com/tradable_products/vix/); Johnson
(2017), *Risk premia and the VIX term structure*, JFQA; FRED, https://fred.stlouisfed.org.

> Decision-support research only; never places orders."""

DATA = """vix, vix3m = bt_long.fred_series("VIXCLS"), bt_long.fred_series("VXVCLS")
inputs = {"px": px, "vix": vix, "vix3m": vix3m}
print("VIX", vix.index[0].date(), "->", vix.index[-1].date(), "| VIX3M", vix3m.index[0].date(), "->", vix3m.index[-1].date())"""

SIGNAL = """def build_signal(inputs, thr=1.0):
    ratio = (inputs["vix"] / inputs["vix3m"]).dropna()
    ratio = bt_pit.daily_pit(ratio, inputs["px"].index, days=1)
    return (ratio < thr).astype(float).where(ratio.notna())


VARIANTS = {"ratio_lt_1.00": dict(thr=1.0), "ratio_lt_0.95": dict(thr=0.95)}
PARAMS_TEXT = {n: f"{n}; FRED VIXCLS/VXVCLS, lag 1 day; daily; next_close; 5bp" for n in VARIANTS}"""

CHART = """ratio = (vix / vix3m).dropna()
fig = go.Figure(go.Scatter(x=ratio.index, y=ratio, name="VIX / VIX3M", line=dict(width=1)))
fig.add_hline(y=1.0, line_dash="dash", line_color="red")
fig.update_layout(title="VIX term-structure ratio (> 1 = backwardation)", height=340)
fig.show()
print(f"share of days in backwardation: {(ratio >= 1).mean():.1%}")"""

CAVEATS = """* Backwardation spells are short and sharp; with a one-day data lag plus next-close execution the rule
  often exits after the first big down day and re-enters after the rebound has started.
* Daily switching: costs matter, see the cost table.
* The ratio is observable only since 2007-12; one full bear market (2008) and two crashes (2020, 2025 if
  any) in sample: weak evidence."""

SPEC = dict(
    trial_id="S09",
    strategy="vix_term_structure",
    folder="volatility",
    name="vix_term_structure",
    title="S09",
    protocol="late",
    rebalance="daily",
    header_md=HEADER,
    data_code=DATA,
    signal_code=SIGNAL,
    chart_code=CHART,
    caveats_md=CAVEATS,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
