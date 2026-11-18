"""Build benchmarks/benchmarks.ipynb cell by cell (nbformat), then execute it."""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
OUT = HERE / "benchmarks.ipynb"

cells = []

cells.append(new_markdown_cell("""# Benchmarks per evaluation period

Reference figures every trial in `REGISTRY.md` is compared against. Nothing is
tuned here; the four benchmarks and the three periods are **frozen** in
`bt_periods.py`.

| Benchmark | Definition |
|---|---|
| `bh` | Buy and hold the S&P 500 total-return series |
| `sma200` | Long equities when close > SMA200 else T-bills; monthly check, next-close execution, 5 bp per switch |
| `mix60` | 60/40 equity / T-bill constant mix, monthly rebalance, no costs |
| `tbill` | 3-month T-bill (FRED `TB3MS`) |

Periods: **dev** 1934-02 to 1989-12, **val** 1990 to 2009, **holdout** 2010 onward
(the holdout is confirmatory only and never used for selection).

Primary metric (frozen): excess-return Sharpe net of costs, see `PLAN.md` §2.
"""))

cells.append(
    new_code_cell(
        """import sys
from pathlib import Path

import pandas as pd
from IPython.display import display

_root = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists()), Path.cwd())
sys.path.insert(0, str(_root / "notebooks" / "backtest"))
import bt_common as bc  # noqa: E402
import bt_periods as bp  # noqa: E402
import bt_long as bl  # noqa: E402

pd.set_option("display.width", 160)
pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
print("periods:", {k: (str(v[0])[:10], str(v[1])[:10] if v[1] is not None else None) for k, v in bp.PERIODS.items()})"""
    )
)

cells.append(new_markdown_cell("## 1. Long sample (1934 onward)"))
cells.append(new_code_cell("""S = bl.long_sample("1934-01-01")
px, cash = S["px"], S["cash"]
print(px.index[0].date(), "->", px.index[-1].date(), len(px), "days")
display(px.tail(3))"""))

cells.append(new_markdown_cell("## 2. Benchmark returns and per-period statistics"))
cells.append(new_code_cell("""bench = bp.benchmark_returns(px, cash)
tbl = bp.benchmark_table(bench)
tbl.index.names = ["period", "benchmark"]
display(tbl[["CAGR", "Vol", "Sharpe", "Max DD"]])"""))

cells.append(new_markdown_cell("### Sharpe matrix (rows: period, cols: benchmark)"))
cells.append(
    new_code_cell(
        """sharpe = tbl["Sharpe"].unstack("benchmark").reindex([p for p in bp.PERIOD_ORDER if p in tbl.index.get_level_values(0)])
display(sharpe)
sma_bt = bench.attrs["sma_bt"]
print("SMA200 switches (full):", int((sma_bt["pos"].diff().abs() > 0).sum()), "| time in equities:", f"{sma_bt['pos'].mean():.2%}")"""
    )
)

cells.append(new_markdown_cell("## 3. Equity curves (log scale)"))
cells.append(new_code_cell("""import plotly.graph_objects as go

eq = (1 + bench[["bh", "sma200", "mix60", "tbill"]].fillna(0)).cumprod()
fig = go.Figure()
for c in eq.columns:
    fig.add_trace(go.Scatter(x=eq.index, y=eq[c], name=c, mode="lines"))
for name in ("dev", "val", "holdout"):
    lo, hi = bp.period_bounds(name, eq.index)
    fig.add_vrect(x0=lo, x1=hi, opacity=0.06, line_width=0, annotation_text=name, annotation_position="top left")
fig.update_yaxes(type="log", title="growth of 1")
fig.update_layout(height=450, title="Benchmarks, S&P 500 TR vs T-bills, 1934 onward", legend_orientation="h")
fig.show()"""))

cells.append(new_markdown_cell("## 4. Export reference figures for the registry"))
cells.append(
    new_code_cell("""out = tbl[["CAGR", "Vol", "Sharpe", "Max DD"]].reset_index()
out_path = Path.cwd() / "benchmarks.csv"
out.to_csv(out_path, index=False, float_format="%.6f", lineterminator="\\n")
print("written", out_path.name, out.shape)
display(out)""")
)

cells.append(new_markdown_cell("""## 5. Reading the table

* `sma200` is the bar to beat: a trial *passes* only if its Sharpe exceeds **both**
  `sma200` and `bh` in dev **and** val (bootstrap p <= 0.10 vs `sma200`).
* `mix60` shows how much of the SMA edge is simply lower equity exposure.
* The holdout column is reported for completeness; it does not enter the pass rule."""))


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
            timeout=900,
            kernel_name="python3",
            resources={"metadata": {"path": str(HERE)}},
        ).execute()
        nbformat.write(nb, p)
        print("executed", p)
