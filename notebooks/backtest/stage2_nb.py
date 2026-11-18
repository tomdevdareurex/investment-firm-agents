"""Notebook generator for Stage 2 strategy notebooks (one standard layout).

A builder passes a ``spec`` dict; ``build(spec, execute=True)`` writes
``<folder>/<name>.ipynb`` and runs it with nbclient.  Required spec keys:
trial_id, strategy, folder, name, title, protocol ("main"|"late"), rebalance,
header_md, data_code (defines ``inputs`` with key "px"), signal_code (defines
``build_signal(inputs, **params)``, ``VARIANTS`` {name: params} and
``PARAMS_TEXT`` {name: str}), caveats_md.  Optional: chart_code, interpretation_md, and
data_cells -- a list of (markdown, code) pairs shown step by step instead of the single
data_code cell (the last code cell must define ``inputs``). ``evidence_version``
opts into ``matched-v1``; omitted/``legacy`` retains historical evaluation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
PENDING = "_Interpretation pending: written after the first execution._"

SETUP = """import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import display

_root = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists()), Path.cwd())
sys.path.insert(0, str(_root / "notebooks" / "backtest"))
import bt_common as bc  # noqa: E402
import bt_long  # noqa: E402
import bt_periods as bp  # noqa: E402
import bt_pit  # noqa: E402
import bt_registry as br  # noqa: E402
import bt_stats as bs  # noqa: E402
import seed_registry  # noqa: E402
import stage2 as s2  # noqa: E402

bc.setup_plotly("cdn")
pd.set_option("display.width", 180)
TRIAL_ID, STRATEGY, NOTEBOOK = {trial_id!r}, {strategy!r}, {notebook!r}
PROTOCOL, REBALANCE = {protocol!r}, {rebalance!r}

sample = bt_long.long_sample()
px, cash = sample["px"], sample["cash"]
bench = bp.benchmark_returns(px, cash)  # SMA200 monthly / B&H / 60-40 / T-bills, frozen settings
print("prices", px.index[0].date(), "->", px.index[-1].date(), "| registry trials so far:", br.trial_count())"""

TRUNC = """trunc = {}
for name, params in VARIANTS.items():
    trunc[name] = s2.truncation_test(build_signal, inputs, n_cuts=N_CUTS, **params)
display(pd.DataFrame({k: v.row() for k, v in trunc.items()}).T)
bad = [k for k, v in trunc.items() if not v.passed]
assert not bad, f"look-ahead detected in variants {bad}: fix before any backtest"
print("all variants pass the truncation look-ahead test")"""

SWEEP = """signals = {name: build_signal(inputs, **params) for name, params in VARIANTS.items()}
sweep, CHOSEN = s2.dev_sweep(px, cash, bench, signals, PARAMS_TEXT, trial_id=TRIAL_ID, strategy=STRATEGY,
                             notebook=NOTEBOOK, protocol=PROTOCOL, rebalance=REBALANCE)
display(sweep)
print("chosen on dev Sharpe only:", CHOSEN, "|", PARAMS_TEXT[CHOSEN])"""

EVAL = """signal = signals[CHOSEN]
runs, cmp, stats, res = s2.evaluate(px, cash, bench, signal, protocol=PROTOCOL, rebalance=REBALANCE)
display(cmp.round(3))
display(stats)
display(res.to_frame().round(3))
print(f"n_trials={res.n_trials} | DSR={res.dsr:.3f} | passes={res.passes} | holdout confirms={res.holdout_confirms}")
display(pd.Series(res.checks, name="check"))"""

ROBUST = """cs = bs.cost_sensitivity(px, signal, cash, rebalance=REBALANCE)
display(cs.round(3))
sma_full = bs.excess_sharpe(bench["sma200"].reindex(runs["full"].index), bench["tbill"].reindex(runs["full"].index))
be = bs.breakeven_cost_bps(px, signal, cash, bench_sharpe=sma_full, rebalance=REBALANCE)
print(f"break-even one-way cost vs SMA200 Sharpe over the same window ({sma_full:.3f}): {be:.1f} bp")
pl = bs.placebo_test(px, signal, cash, n_placebo=200, rebalance=REBALANCE, rng=np.random.default_rng(bs.SEED))
display(pd.Series(pl, name="placebo").to_frame())
peek = bt_pit.lookahead_test(px, signal, cash, rebalance=REBALANCE)
print(f"peek test: Sharpe by shift {peek.sharpe_by_shift.round(3).to_dict()} | gain {peek.peek_gain:+.3f}")
display(s2.decade_table(runs["full"], bench).style.format("{:.2f}"))"""

REGISTER = """note = ("passes" if res.passes else "fails") + f" frozen metric; chosen {CHOSEN} on dev; protocol {PROTOCOL}"
rows = s2.register_final(TRIAL_ID, STRATEGY, NOTEBOOK, PARAMS_TEXT[CHOSEN], res, note=note, header=seed_registry.HEADER)
display(rows)
print("registry trial count:", br.trial_count())"""

CURRENT = """last = signal.dropna()
print(f"latest signal ({CHOSEN}) on {last.index[-1].date()}: equity weight {last.iloc[-1]:.2f}")
chk = bc.check_days(px.index, REBALANCE)
display(last[chk.reindex(last.index).fillna(False)].tail(6).to_frame("equity weight at decision"))
print("Research output only -- not a recommendation or an order.")"""

SUMMARY = """for line in s2.evidence_lines(res, trunc[CHOSEN], peek, pl, be):
    print("*", line)"""


def _cells(spec: dict) -> list:
    evidence_version = spec.get("evidence_version", "legacy")
    if evidence_version not in ("legacy", "matched-v1"):
        raise ValueError(f"unknown evidence_version {evidence_version!r}")
    nb_rel = f"{spec['folder']}/{spec['name']}.ipynb"
    setup = SETUP.format(
        trial_id=spec["trial_id"],
        strategy=spec["strategy"],
        notebook=nb_rel,
        protocol=spec["protocol"],
        rebalance=spec["rebalance"],
    )
    sweep, evaluation, robust, register = SWEEP, EVAL, ROBUST, REGISTER
    sweep_note = evaluation_note = robust_note = ""
    if evidence_version == "matched-v1":
        setup += f"\nEVIDENCE_VERSION = {evidence_version!r}"
        version_kw = ", evidence_version=EVIDENCE_VERSION"
        sweep = SWEEP.replace(
            "rebalance=REBALANCE)", "rebalance=REBALANCE" + version_kw + ")"
        )
        evaluation = EVAL.replace(
            "rebalance=REBALANCE)", "rebalance=REBALANCE" + version_kw + ")"
        )
        evaluation += '\nprint(f"Evidence: {EVIDENCE_VERSION}; gated DSR uses dev+val only; descriptive full DSR={res.dsr_full:.3f}")'
        robust = ROBUST.replace(
            "rng=np.random.default_rng(bs.SEED))",
            "rng=np.random.default_rng(bs.SEED)" + version_kw + ")",
        )
        register = REGISTER.replace(
            " frozen metric;", " {EVIDENCE_VERSION} metric (DSR dev+val);"
        )
        sweep_note = (
            "\n\n**matched-v1:** score variants and benchmarks on common valid development "
            "dates, retaining their execution paths (no boundary resets)."
        )
        evaluation_note = (
            "\n\n**matched-v1:** thresholds and the DSR estimator are unchanged; the DSR "
            "acceptance sample is dev + val only. Full-sample DSR is descriptive, not a gate. "
            "This is distinct from the separate `bt_stats_v2` estimator. Previously inspected "
            "holdout data do not become an untouched holdout merely by correcting this code."
        )
        robust_note = (
            "\n\n**matched-v1:** real and placebo paths use identical executed dates and "
            "signal availability; equity probability is calibrated on executed exposure. "
            "The legacy persistence approximation remains; exact turnover matching is not claimed."
        )
    md, code = new_markdown_cell, new_code_cell
    cells = [
        md(spec["header_md"]),
        code(setup),
        md("## 1. Data and point-in-time inputs"),
    ]
    if spec.get("data_cells"):
        for md_text, code_text in spec["data_cells"]:
            cells += [md(md_text), code(code_text)]
    else:
        cells.append(code(spec["data_code"]))
    cells += [
        md("## 2. Signal and variant grid (fixed before any backtest)"),
        code(spec["signal_code"]),
    ]
    if spec.get("chart_code"):
        cells.append(code(spec["chart_code"]))
    cells += [
        md(
            "## 3. Look-ahead checks\n\nEvery variant is recomputed with all inputs cut at "
            "past dates (monthly inputs: completed months only) and must equal the full-data "
            "signal on those dates (`stage2.truncation_test`). No backtest runs unless all pass."
        ),
        code(f"N_CUTS = {spec.get('n_cuts', 30)}\n" + TRUNC),
        md(
            "## 4. Development-period sweep\n\nEach variant is scored on the **dev** period only "
            "and registered as a trial. The best dev Sharpe is chosen; validation and holdout "
            "results are never used for the choice." + sweep_note
        ),
        code(sweep),
        md(
            "## 5. Frozen evaluation of the chosen variant\n\nFrozen primary metric "
            "(`PLAN.md` section 2): beat SMA200 and buy & hold in dev **and** val, one-sided "
            "block-bootstrap p <= 0.10 vs SMA200 in both, deflated Sharpe >= 0.95 with the "
            "registry trial count. Holdout is confirmatory only." + evaluation_note
        ),
        code(evaluation),
        code("s2.plot_growth(runs, bench, f'{TRIAL_ID} {CHOSEN}', PROTOCOL).show()"),
        md("## 6. Robustness: costs, placebo, peek test, decades" + robust_note),
        code(robust),
        md("## 7. Register the result"),
        code(register),
        md("## 8. Current signal"),
        code(CURRENT),
        md("## 9. Evidence summary (computed)"),
        code(SUMMARY),
        md("## 10. Caveats\n\n" + spec["caveats_md"]),
        md("## 11. Interpretation\n\n" + spec.get("interpretation_md", PENDING)),
    ]
    return cells


def build(spec: dict, execute: bool = False, timeout: int = 3600) -> Path:
    folder = HERE / spec["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{spec['name']}.ipynb"
    nb = new_notebook(cells=_cells(spec))
    nb.metadata["kernelspec"] = {
        "display_name": ".venv",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {"name": "python"}
    nbformat.write(nb, out)
    if execute:
        from nbclient import NotebookClient

        nb = nbformat.read(out, 4)
        NotebookClient(
            nb,
            timeout=timeout,
            kernel_name="python3",
            resources={"metadata": {"path": str(folder)}},
        ).execute()
        nbformat.write(nb, out)
    return out


def set_interpretation(nb_path: Path, text: str) -> None:
    """Replace the interpretation cell of an executed notebook (no re-execution)."""
    nb = nbformat.read(nb_path, 4)
    for cell in reversed(nb.cells):
        if cell.cell_type == "markdown" and cell.source.startswith(
            "## 11. Interpretation"
        ):
            cell.source = "## 11. Interpretation\n\n" + text
            break
    else:
        raise ValueError("interpretation cell not found")
    nbformat.write(nb, nb_path)


def main(spec: dict) -> None:
    """CLI used by builders: ``python build_sXX.py [--execute]``."""
    p = build(spec, execute="--execute" in sys.argv)
    print("built" + (" and executed" if "--execute" in sys.argv else ""), p)
