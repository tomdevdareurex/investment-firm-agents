"""Build volatility/vol_managed.ipynb (S04). Usage: python build_s04.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S04 - Volatility-managed exposure (volatility)

**Hypothesis.** Volatility clusters and is persistent, but high volatility is not followed by
proportionally higher returns. Scaling equity exposure down when recent realised volatility is
high should raise the Sharpe ratio (Moreira & Muir 2017). Here without leverage: the weight is
capped at 100% equities, the rest earns T-bills.

| Variant | Equity weight at each monthly check |
|---|---|
| lb21_t10, lb21_t15 | min(1, 10% or 15% / realised vol of the last 21 trading days) |
| lb63_t10, lb63_t15 | same with a 63-day window |

**Inputs and point-in-time lags**

| Series | Source | Lag used |
|---|---|---|
| S&P 500 daily total return | `bt_long.long_sample` (spliced Shiller / ^SP500TR) | realised vol uses returns up to the decision close; next-close fill |

Monthly check, next-close execution, 5 bp per unit of turnover (fractional weight changes).

**Sources.** Moreira & Muir (2017), *Volatility-managed portfolios*, Journal of Finance,
NBER w22208; Cederburg, O'Doherty, Wang & Yan (2020), *On the performance of
volatility-managed portfolios*, JFE doi:10.1016/j.jfineco.2020.04.015 (out-of-sample doubts);
Harvey et al. (2018), *The impact of volatility targeting*, SSRN 3175538.

> Decision-support research only; never places orders."""

DATA = """inputs = {"px": px}
r = px["tr_close"].pct_change(fill_method=None)
print("realised vol (21d, annualised), last:", round(float(r.tail(21).std() * np.sqrt(252)), 4))"""

SIGNAL = """def build_signal(inputs, lb=21, target=0.10):
    r = inputs["px"]["tr_close"].pct_change(fill_method=None)
    vol = r.rolling(lb).std() * np.sqrt(252)
    return (target / vol).clip(upper=1.0).where(vol.notna())


VARIANTS = {
    f"lb{lb}_t{int(t * 100)}": dict(lb=lb, target=t) for lb in (21, 63) for t in (0.10, 0.15)
}
PARAMS_TEXT = {n: f"{n}; weight=min(1,target/realised vol); monthly; next_close; 5bp/turnover" for n in VARIANTS}"""

CHART = """w = build_signal(inputs, lb=63, target=0.10)
fig = go.Figure()
fig.add_trace(go.Scatter(x=w.index, y=w.rolling(21).mean(), name="weight lb63_t10 (21d avg)"))
fig.update_layout(title="Volatility-managed equity weight", height=320, yaxis_tickformat=".0%")
fig.show()"""

CAVEATS = """* Fractional weights: the placebo test binarises the signal at 50%, so it is only indicative here.
* No leverage: the published gains of volatility management rely partly on levering up in calm
  markets; capped at 100% the strategy can only de-risk.
* Monthly rebalancing ignores intra-month volatility spikes (e.g. 1987, 2020)."""

SPEC = dict(
    trial_id="S04",
    strategy="vol_managed",
    folder="volatility",
    name="vol_managed",
    title="S04",
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
