"""Build valuation/cape_excess_yield.ipynb (S01 reference trial) cell by cell."""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
OUT = HERE / "cape_excess_yield.ipynb"

cells = []

cells.append(new_markdown_cell("""# S01 - CAPE excess yield (reference trial)

**Status: REFERENCE.** One fixed rule, no parameter search. Its job is to show the
full Stage 1 pipeline end to end (point-in-time alignment, look-ahead test, three
frozen periods, bootstrap vs SMA200, deflated Sharpe, registry row) on a signal
everyone knows. Pass or fail is reported as is.

## Rule

* `ey_t = 1 / CAPE_t - GS10_t / 100` - Shiller cyclically adjusted earnings yield
  minus the 10-year Treasury yield (both from the monthly Shiller file).
* Long equities when `ey` is above its own **expanding median** (first 10 years
  used as warm-up, median lagged one month); otherwise 3-month T-bills.
* Monthly check, next-close execution, 5 bp per switch - identical to the SMA200
  benchmark so the comparison is like for like.

## Point-in-time convention

Shiller publishes month *M* roughly one month late, and the Shiller `P` for month
*M* is itself a monthly average. We therefore make the month-*M* observation usable
only from the first trading day of **M+2** (`bt_pit.RELEASE_LAGS["SHILLER_CAPE"]`,
one extra month on top of the usual M+1). The raw S&P series ends 2024-09 in the
file used here, so the signal is frozen (forward-filled) from 2024-11 onward; the
holdout period therefore includes ~2 years of a stale signal, which is noted below.
"""))

cells.append(
    new_code_cell(
        """import sys
from pathlib import Path

import numpy as np
import pandas as pd
from IPython.display import display

_root = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists()), Path.cwd())
sys.path.insert(0, str(_root / "notebooks" / "backtest"))
import bt_common as bc  # noqa: E402
import bt_long  # noqa: E402
import bt_periods as bp  # noqa: E402
import bt_pit  # noqa: E402
import bt_registry as br  # noqa: E402
import bt_stats as bs  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

TRIAL_ID = "S01"
STRATEGY = "cape_excess_yield"
NOTEBOOK = "valuation/cape_excess_yield.ipynb"
PARAMS = "ey=1/CAPE-GS10; rule=ey>expanding_median(min 120m, lag 1m); pit M+2; monthly; 5bp"
WARMUP_MONTHS = 120
LAG = bt_pit.RELEASE_LAGS["SHILLER_CAPE"]

sample = bt_long.long_sample()
px, cash, shiller = sample["px"], sample["cash"], sample["shiller"]
print("prices", px.index[0].date(), "->", px.index[-1].date(), "| shiller ends", shiller.index[-1])"""
    )
)

cells.append(
    new_markdown_cell(
        """## 1. Signal construction (monthly, then point-in-time daily)"""
    )
)

cells.append(
    new_code_cell(
        """m = shiller[["CAPE", "GS10"]].dropna().copy()
m.index = m.index.to_timestamp(how="start")
ey = (1.0 / m["CAPE"] - m["GS10"] / 100.0).rename("ey")
median = ey.expanding(min_periods=WARMUP_MONTHS).median().shift(1)
sig_m = (ey > median).astype(float)
sig_m[median.isna()] = np.nan

# month M observation usable from first trading day of M+2
signal = bt_pit.monthly_to_daily_pit(sig_m, px.index, **LAG).rename("signal")
ey_daily = bt_pit.monthly_to_daily_pit(ey, px.index, **LAG).rename("ey")
median_daily = bt_pit.monthly_to_daily_pit(median, px.index, **LAG).rename("ey_median")

first = signal.first_valid_index()
switches = int((signal.diff().abs() > 0).sum())
print(f"first signal {first.date()} | share in equities {signal.mean():.1%} | monthly switches {switches}")
print("last CAPE month in file:", m.index[-1].date(), "-> signal frozen after", (m.index[-1] + pd.offsets.MonthBegin(2)).date())
display(pd.concat([ey, median.rename("median"), sig_m.rename("signal")], axis=1).tail(6))"""
    )
)

cells.append(new_code_cell("""fig = go.Figure()
fig.add_trace(go.Scatter(x=ey.index, y=ey * 100, name="excess yield (%)"))
fig.add_trace(go.Scatter(x=median.index, y=median * 100, name="expanding median (%)", line=dict(dash="dash")))
fig.add_trace(go.Scatter(x=sig_m.index, y=sig_m * 10 - 15, name="signal (1 = equities, offset)", line=dict(width=1)))
fig.update_layout(title="CAPE excess yield vs expanding median", height=420, legend=dict(orientation="h"))
fig.show()"""))

cells.append(new_markdown_cell("""## 2. Look-ahead test

Shift the daily signal by -21 .. +21 trading days. If *peeking* (negative shifts)
does **not** improve the Sharpe, the signal as aligned may already contain future
information. We expect a clear gain from peeking for a genuinely lagged signal."""))

cells.append(
    new_code_cell(
        """la = bt_pit.lookahead_test(px, signal, cash)
display(la.to_frame().T.round(3))
print(f"peek gain (Sharpe at -21d minus at 0): {la.peek_gain:+.3f} | suspicious: {la.suspicious}")"""
    )
)

cells.append(new_markdown_cell("""## 3. Backtest per frozen period vs benchmarks

Periods and benchmarks come from `bt_periods` (dev 1934-02..1989-12, val 1990..2009,
holdout 2010.., full). The holdout is confirmatory only."""))

cells.append(
    new_code_cell(
        """runs = bp.run_periods(px, signal, cash, extra={"ey": ey_daily, "ey_median": median_daily})
bench = bp.benchmark_returns(px, cash)
cmp = bp.compare_to_benchmarks(runs, bench)
display(cmp.round(3))
stats = pd.DataFrame({p: bc.perf_stats(df["r_strat"], df["r_cash"]) for p, df in runs.items()}).T
display(stats)"""
    )
)

cells.append(new_code_cell("""full = runs["full"]
eq = (1 + full["r_strat"]).cumprod()
eq_bh = (1 + full["r_bh"]).cumprod()
sma = (1 + bench["sma200"].reindex(full.index).fillna(0)).cumprod()
fig = go.Figure()
fig.add_trace(go.Scatter(x=eq.index, y=eq, name="S01 CAPE excess yield"))
fig.add_trace(go.Scatter(x=eq_bh.index, y=eq_bh, name="buy & hold"))
fig.add_trace(go.Scatter(x=sma.index, y=sma, name="SMA200 benchmark"))
for name, (a, b) in bp.PERIODS.items():
    fig.add_shape(type="line", x0=a, x1=a, y0=0, y1=1, yref="paper", line=dict(color="grey", dash="dot"))
    fig.add_annotation(x=a, y=1, yref="paper", text=name, showarrow=False, yanchor="bottom")
fig.update_layout(title="Growth of 1 (log scale)", yaxis_type="log", height=480, legend=dict(orientation="h"))
fig.show()"""))

cells.append(new_markdown_cell("""## 4. Primary metric (frozen) and robustness

* Pass rule: Sharpe > SMA200 **and** > B&H in dev and val, one-sided block-bootstrap
  p <= 0.10 vs SMA200 in both, deflated Sharpe >= 0.95 using the registry trial
  count (this trial included).
* Cost sensitivity and a placebo test (signal dates shuffled in blocks) follow."""))

cells.append(
    new_code_cell("""n_trials = br.trial_count() + 1  # registered so far plus this one
res = bs.primary_metric(runs, bench, n_trials=n_trials, rng=np.random.default_rng(bs.SEED))
display(res.to_frame().round(3))
print(f"n_trials={res.n_trials} | DSR={res.dsr:.3f} | passes={res.passes} | holdout confirms={res.holdout_confirms}")
display(pd.Series(res.checks, name="check"))""")
)

cells.append(
    new_code_cell(
        """cs = bs.cost_sensitivity(px, signal, cash)
display(cs.round(3))
bench_full = bc.perf_stats(bench["sma200"], bench["tbill"])["Sharpe"]
be = bs.breakeven_cost_bps(px, signal, cash, bench_sharpe=bench_full)
print(f"break-even cost to match SMA200 full-sample Sharpe ({bench_full:.3f}): {be:.1f} bp")"""
    )
)

cells.append(
    new_code_cell(
        """pl = bs.placebo_test(px, signal, cash, n_placebo=200, rng=np.random.default_rng(bs.SEED))
display(pd.DataFrame([pl]).T.rename(columns={0: "placebo"}))"""
    )
)


cells.append(new_markdown_cell("""## 5. Register the trial

The planned placeholder row `S01` is replaced by one row per period
(`S01/dev`, `S01/val`, `S01/holdout`, `S01/full`). The status is whatever the
frozen metric says; a REFERENCE trial that fails is still recorded."""))

cells.append(
    new_code_cell(
        """import seed_registry

reg = br.load_registry()
reg = reg[reg["trial_id"] != TRIAL_ID]
reg.to_csv(br.REGISTRY_CSV, index=False, lineterminator="\\n")

if res.passes:
    note = "REFERENCE trial; passes frozen metric"
else:
    note = "REFERENCE trial; fails frozen metric (does not beat SMA200 in dev/val); Shiller file ends 2024-09 so holdout tail is a frozen signal"
rows = br.rows_from_primary(TRIAL_ID, STRATEGY, NOTEBOOK, PARAMS, res, note=note)
br.append_trials(rows)
br.render_registry(title=seed_registry.HEADER)
print("registry trial count:", br.trial_count())
display(br.load_registry().query("trial_id.str.startswith(@TRIAL_ID)", engine="python"))"""
    )
)

cells.append(
    new_markdown_cell("""## 6. Interpretation

* The excess-yield rule is a slow valuation timer: it sits in equities only about a
  quarter of the time and switches a few dozen times in ninety years.
* It beats buy & hold in the development period but not the SMA200 benchmark, and it
  trails both in validation, so it **fails the frozen primary metric**. That is the
  expected outcome for a reference trial: it anchors the registry and sets the bar for
  Stage 2 ideas, which must beat SMA200 in dev *and* val.
* The look-ahead test is flagged `suspicious` (peek gain -0.02): shifting the daily signal
  by +/-21 days barely moves the Sharpe (0.44-0.49). With only ~23 switches in ninety
  years the test has almost no power for this signal, so the flag is uninformative rather
  than evidence of leakage; the M+2 point-in-time lag is applied explicitly in section 1.
* Holdout figures are reported for completeness only and do not enter the pass rule.
  Shiller data ends 2024-09, so from 2024-11 the signal is frozen at its last value.""")
)


def build() -> Path:
    nb = new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {
        "display_name": ".venv",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {"name": "python"}
    nbformat.write(nb, OUT)
    return OUT


if __name__ == "__main__":
    p = build()
    print("built", p)
    if "--execute" in sys.argv:
        from nbclient import NotebookClient

        nb = nbformat.read(p, 4)
        NotebookClient(
            nb,
            timeout=1800,
            kernel_name="python3",
            resources={"metadata": {"path": str(HERE)}},
        ).execute()
        nbformat.write(nb, p)
        print("executed", p)
