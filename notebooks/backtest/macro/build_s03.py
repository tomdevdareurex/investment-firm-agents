"""Build macro/sahm_rule.ipynb (S03). Usage: python build_s03.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S03 - Sahm-rule unemployment signal (macro)

**Hypothesis.** A recession is under way once the 3-month average unemployment rate rises 0.5 pp
above its low of the previous 12 months (Sahm 2019). Recessions coincide with most deep bear
markets, so holding T-bills while the rule is triggered should cut drawdowns.

| Variant | Risk-on (hold S&P 500) when ... |
|---|---|
| comp_thr05 / comp_thr03 | Sahm indicator from current-vintage UNRATE < 0.5 / 0.3 |
| rt_thr05 | FRED real-time Sahm indicator (built from first-release data) < 0.5 |
| rt_hyst | real-time: risk-off when >= 0.5, back on only once < 0.25 |

**Inputs and point-in-time lags**

| Series | Source | Start | Lag used |
|---|---|---|---|
| Unemployment rate, monthly (current vintage, revised) | FRED `UNRATE` | 1948 | month M usable from M+1 + 7 days |
| Real-time Sahm indicator (first-release data) | FRED `SAHMREALTIME` | 1959-12 | month M usable from M+1 + 7 days |

The employment report comes out on the first Friday of M+1, so day 7 is conservative.
The current-vintage variants carry a small revision look-ahead (seasonal revisions, a few
tenths at most); the real-time variants do not. Monthly check, next-close, 5 bp per switch.
Before the data start the strategy has no signal, so its periods begin in 1949 / 1960 and
the benchmarks are compared on the same rows.

**Sources.** Sahm (2019), *Direct stimulus payments to individuals*, Hamilton Project /
Brookings; FRED series `SAHMREALTIME` and `UNRATE`, https://fred.stlouisfed.org.

> Decision-support research only; never places orders."""

DATA = """unrate = bt_long.fred_series("UNRATE")
sahm_rt = bt_long.fred_series("SAHMREALTIME")
inputs = {"px": px, "unrate": unrate, "sahm_rt": sahm_rt}
print("UNRATE", unrate.index[0].date(), "->", unrate.index[-1].date(), "| SAHMREALTIME", sahm_rt.index[0].date(), "->", sahm_rt.index[-1].date())"""

SIGNAL = """LAG = dict(months=0, days=7)


def sahm_from_unrate(u):
    u3 = u.rolling(3).mean()
    return u3 - u3.shift(1).rolling(12).min()


def hysteresis(ind, off=0.5, on=0.25):
    out, state = [], 1.0
    for v in ind.to_numpy():
        if np.isnan(v):
            out.append(np.nan)
            continue
        state = 0.0 if v >= off else (1.0 if v < on else state)
        out.append(state)
    return pd.Series(out, index=ind.index)


def build_signal(inputs, source="comp", thr=0.5, hyst=False):
    ind = sahm_from_unrate(inputs["unrate"]) if source == "comp" else inputs["sahm_rt"]
    ind = ind.dropna()
    m = hysteresis(ind, thr, thr / 2) if hyst else (ind < thr).astype(float)
    return bt_pit.monthly_to_daily_pit(m, inputs["px"].index, **LAG)


VARIANTS = {
    "comp_thr05": dict(source="comp", thr=0.5),
    "comp_thr03": dict(source="comp", thr=0.3),
    "rt_thr05": dict(source="rt", thr=0.5),
    "rt_hyst": dict(source="rt", thr=0.5, hyst=True),
}
PARAMS_TEXT = {n: f"{n}; FRED UNRATE/SAHMREALTIME, lag M+1+7d; monthly; next_close; 5bp" for n in VARIANTS}"""

CHART = """fig = go.Figure()
fig.add_trace(go.Scatter(x=sahm_rt.index, y=sahm_rt, name="real-time Sahm"))
comp = sahm_from_unrate(unrate)
fig.add_trace(go.Scatter(x=comp.index, y=comp, name="Sahm from current UNRATE", opacity=0.6))
fig.add_hline(y=0.5, line_dash="dash", line_color="red")
fig.update_layout(title="Sahm recession indicator (pp)", height=380, legend=dict(orientation="h"))
fig.show()"""

CAVEATS = """* The rule is a coincident recession signal: it usually triggers months after the equity peak, and
  equities often bottom before unemployment peaks, so it can sell late and buy back late.
* Few events (about 11 recessions since 1948), so any Sharpe difference has a wide confidence interval.
* Current-vintage UNRATE is revised; the real-time variants avoid that look-ahead.
* Data start 1948 / 1959: the dev period is shorter than for price-based rules."""

SPEC = dict(
    trial_id="S03",
    strategy="sahm_rule",
    folder="macro",
    name="sahm_rule",
    title="S03",
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
