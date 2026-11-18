"""Stage 2 helpers: truncation look-ahead test, late-data periods, dev-only sweep,
frozen evaluation, registration and standard charts.

Additive on top of the Stage 1 infrastructure (``bt_periods``, ``bt_stats``,
``bt_registry``); nothing here changes their behaviour.  Research only: never
places orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import bt_common as bc
import bt_periods as bp
import bt_registry as br
import bt_stats as bs

# Late-data protocol (signals whose data starts after 1990), PLAN-stage2.md section 2.
LATE_PERIODS = {
    "dev": ("1900-01-01", "2013-12-31"),
    "val": ("2014-01-01", "2017-12-31"),
    "holdout": ("2018-01-01", None),
}


# ---------------------------------------------------------------------------
# Truncation look-ahead test
# ---------------------------------------------------------------------------


def _is_monthly(obj) -> bool:
    """Period-indexed or month-spaced (median gap >= 25 days) series / frame."""
    idx = obj.index
    if isinstance(idx, pd.PeriodIndex):
        return True
    idx = (
        obj.dropna(how="all").index
        if isinstance(obj, pd.DataFrame)
        else obj.dropna().index
    )
    if len(idx) < 3:
        return False
    return float(pd.Series(idx).diff().dt.days.median()) >= 25


def truncate_inputs(inputs: dict, cut: pd.Timestamp) -> dict:
    """Inputs as they would have existed at the close of ``cut``.

    Daily data: observations dated <= cut.  Monthly data (dated by period or by
    month start): only months that have *ended* on or before ``cut``.  Non-pandas
    values (parameters) pass through unchanged.
    """
    cut = pd.Timestamp(cut)
    out = {}
    for key, val in inputs.items():
        if not isinstance(val, (pd.Series, pd.DataFrame)):
            out[key] = val
            continue
        idx = val.index
        if isinstance(idx, pd.PeriodIndex):
            keep = (idx + 1).to_timestamp(how="start") <= cut + pd.Timedelta(days=1)
        elif _is_monthly(val):
            keep = (idx + pd.offsets.MonthEnd(0)) <= cut
        else:
            keep = idx <= cut
        out[key] = val[np.asarray(keep)]
    return out


@dataclass
class TruncResult:
    n_cuts: int
    n_mismatch: int
    max_abs_diff: float
    mismatches: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.n_mismatch == 0

    def row(self) -> dict:
        return {
            "cuts": self.n_cuts,
            "mismatches": self.n_mismatch,
            "max_abs_diff": self.max_abs_diff,
            "passed": self.passed,
        }


def truncation_test(
    build_signal,
    inputs: dict,
    n_cuts: int = 30,
    cut_dates=None,
    tol: float = 1e-9,
    seed: int = bs.SEED,
    **params,
) -> TruncResult:
    """Recompute the signal with every input truncated at past dates.

    ``build_signal(inputs, **params)`` must return the daily signal on
    ``inputs["px"].index``.  A point-in-time signal computed from data cut at the
    close of day c must equal the full-data signal on day c.  Any difference means
    the full-data signal used information from after c (full-sample statistics,
    centred windows, back-fills, missing release lags on incomplete months).
    """
    full = build_signal(inputs, **params)
    valid = full.dropna().index
    if cut_dates is None:
        rng = np.random.default_rng(seed)
        k = min(n_cuts, max(len(valid) - 1, 0))
        pick = np.sort(rng.choice(len(valid) - 1, size=k, replace=False))
        cut_dates = valid[pick]
    mism, max_diff = [], 0.0
    for cut in cut_dates:
        part = build_signal(truncate_inputs(inputs, cut), **params)
        a = full.get(cut, np.nan)
        b = part.get(cut, np.nan) if len(part) else np.nan
        if pd.isna(a) and pd.isna(b):
            continue
        if pd.isna(a) or pd.isna(b):
            mism.append((cut, a, b))
            max_diff = np.inf
            continue
        d = abs(float(a) - float(b))
        max_diff = max(max_diff, d)
        if d > tol:
            mism.append((cut, a, b))
    return TruncResult(len(cut_dates), len(mism), float(max_diff), mism)


# ---------------------------------------------------------------------------
# Periods, dev sweep, frozen evaluation, registration
# ---------------------------------------------------------------------------


def run_protocol(
    px: pd.DataFrame,
    signal: pd.Series,
    cash: pd.Series,
    protocol: str = "main",
    rebalance: str = "monthly",
    cost_bps: float = bp.BENCH_COST_BPS,
    execution: str = bp.BENCH_EXECUTION,
    extra: dict | None = None,
) -> dict[str, pd.DataFrame]:
    """Per-period backtests: ``main`` = ``bt_periods.run_periods`` (unchanged);
    ``late`` = one full run sliced into ``LATE_PERIODS`` (no extra warm-up drop,
    the signal's own data start is the warm-up)."""
    if protocol == "main":
        return bp.run_periods(
            px, signal, cash, cost_bps, execution, rebalance, extra=extra
        )
    if protocol != "late":
        raise ValueError(f"protocol must be 'main' or 'late', got {protocol!r}")
    full = bc.backtest_signal(
        px, signal, cash, cost_bps, execution, None, rebalance, extra=extra
    )
    out = {}
    for name, (a, b) in LATE_PERIODS.items():
        part = full.loc[a:b].copy()
        if len(part) >= 60:
            part.attrs["period"] = name
            out[name] = part
    full.attrs["period"] = "full"
    out["full"] = full
    return out


def _matched_dev_paths(px, cash, bench, signals, protocol, rebalance):
    """Execute first, then intersect finite DEV returns across all contenders.

    Score strictly after the latest first available DEV execution row. This
    conservative boundary convention removes forced initial-entry asymmetry
    (also when a path has already been warmed up). Never rerun/rebase execution:
    all transaction costs on retained dates remain in the scored returns.
    """
    if not signals:
        raise ValueError("matched-v1 requires variants with a valid DEV sample")
    paths = {}
    for name, sig in signals.items():
        if sig is None or sig.dropna().empty:
            raise ValueError(f"matched-v1 missing signal for {name!r}")
        dev = run_protocol(px, sig, cash, protocol, rebalance).get("dev")
        if dev is None or dev.empty:
            raise ValueError(f"matched-v1 missing DEV sample for {name!r}")
        if not dev.index.is_unique or not dev.index.is_monotonic_increasing:
            raise ValueError("matched-v1 DEV paths must be chronological and unique")
        paths[name] = dev
    if not bench.index.is_unique:
        raise ValueError("matched-v1 benchmark dates must be unique")
    valid = np.isfinite(bench[["sma200", "bh", "tbill"]]).all(axis=1)
    common = bench.index[valid]
    for dev in paths.values():
        valid = np.isfinite(dev[["r_strat", "r_cash"]]).all(axis=1)
        common = common.intersection(dev.index[valid])
    boundary = max(dev.index[0] for dev in paths.values())
    common = common[common > boundary].sort_values()
    if len(common) < 60:
        raise ValueError("matched-v1 requires at least 60 common finite DEV rows")
    return {name: dev.loc[common] for name, dev in paths.items()}


def dev_sweep(
    px: pd.DataFrame,
    cash: pd.Series,
    bench: pd.DataFrame,
    signals: dict[str, pd.Series],
    params_text: dict[str, str],
    *,
    trial_id: str,
    strategy: str,
    notebook: str,
    protocol: str = "main",
    rebalance: str = "monthly",
    register: bool = True,
    evidence_version: str = "legacy",
) -> tuple[pd.DataFrame, str]:
    """Score every variant on DEV and return the table and best-Sharpe variant.

    Legacy retains variant-specific windows. Opt-in matched-v1 uses a common
    finite sample after the latest first DEV execution row (see helper above),
    with at least 60 rows; all scores are validated before trial registration.
    """
    bs._validate_evidence_version(evidence_version)
    matched = evidence_version == "matched-v1"
    paths = (
        _matched_dev_paths(px, cash, bench, signals, protocol, rebalance)
        if matched
        else None
    )
    table, rows = {}, []
    for k, (name, sig) in enumerate(signals.items(), start=1):
        dev = (
            paths[name]
            if matched
            else run_protocol(px, sig, cash, protocol, rebalance)["dev"]
        )
        b = bench.reindex(dev.index)
        s = bs.excess_sharpe(dev["r_strat"], dev["r_cash"])
        d_sma = s - bs.excess_sharpe(b["sma200"], b["tbill"])
        d_bh = s - bs.excess_sharpe(b["bh"], b["tbill"])
        if matched and not np.isfinite([s, d_sma, d_bh]).all():
            raise ValueError(f"matched-v1 nonfinite DEV score for {name!r}")
        st = bc.strategy_stats(dev)
        table[name] = {
            "dev_sharpe": s,
            "d_sma200": d_sma,
            "d_bh": d_bh,
            "time_in_market": st["Time in market"],
            "switches_pa": st["Switches / yr"],
            "dev_start": dev.index[0].date(),
        }
        note = f"dev-only sweep, variant {name}"
        if matched:
            table[name].update(dev_end=dev.index[-1].date(), dev_n=len(dev))
            note += (
                f"; evidence_version={evidence_version}; common DEV "
                f"{dev.index[0].date()}..{dev.index[-1].date()}; dev_n={len(dev)}; "
                "after latest first DEV execution row, retained costs unchanged"
            )
        rows.append(
            {
                "trial_id": f"{trial_id}-v{k}/dev",
                "strategy": strategy,
                "notebook": notebook,
                "params": params_text[name],
                "period": "dev",
                "sharpe": s,
                "d_sma200": d_sma,
                "d_bh": d_bh,
                "status": "run",
                "note": note,
            }
        )
    if register:
        br.append_trials(rows)
    tab = pd.DataFrame(table).T
    return tab, str(tab["dev_sharpe"].astype(float).idxmax())


def evaluate(
    px: pd.DataFrame,
    cash: pd.Series,
    bench: pd.DataFrame,
    signal: pd.Series,
    *,
    protocol: str = "main",
    rebalance: str = "monthly",
    n_trials: int | None = None,
    evidence_version: str = "legacy",
):
    """Frozen evaluation of the chosen variant: ``(runs, compare, stats, res)``."""
    bs._validate_evidence_version(evidence_version)
    runs = run_protocol(px, signal, cash, protocol, rebalance)
    cmp = bp.compare_to_benchmarks(runs, bench)
    stats = bp.period_table(runs)
    n = n_trials if n_trials is not None else max(br.trial_count(), 1)
    res = bs.primary_metric(
        runs,
        bench,
        n_trials=n,
        rng=np.random.default_rng(bs.SEED),
        evidence_version=evidence_version,
    )
    return runs, cmp, stats, res


def register_final(
    trial_id: str,
    strategy: str,
    notebook: str,
    params: str,
    res,
    note: str = "",
    header: str | None = None,
) -> pd.DataFrame:
    """Drop the planned placeholder row, register one row per period, re-render."""
    if getattr(res, "evidence_version", "legacy") == "matched-v1":
        note = (note + "; " if note else "") + (
            "evidence_version=matched-v1; DSR gate sample=dev+val execution returns "
            "(pre-holdout); full DSR descriptive only"
        )
    reg = br.load_registry()
    reg = reg[reg["trial_id"] != trial_id]
    reg.to_csv(br.REGISTRY_CSV, index=False, lineterminator="\n")
    br.append_trials(
        br.rows_from_primary(trial_id, strategy, notebook, params, res, note=note)
    )
    br.render_registry(title=header)
    reg = br.load_registry()
    return reg[reg["trial_id"].str.startswith(trial_id)]


# ---------------------------------------------------------------------------
# Charts, tables, summary
# ---------------------------------------------------------------------------


def period_starts(protocol: str = "main") -> dict[str, str]:
    src = bp.PERIODS if protocol == "main" else LATE_PERIODS
    return {k: v[0] for k, v in src.items()}


def plot_growth(runs: dict, bench: pd.DataFrame, label: str, protocol: str = "main"):
    """Growth of 1 (log), equity weight and drawdown on the full run."""
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    full = runs["full"]
    b = bench.reindex(full.index).fillna(0.0)
    curves = {
        label: (1 + full["r_strat"]).cumprod(),
        "Buy & hold": (1 + full["r_bh"]).cumprod(),
        "SMA200 benchmark": (1 + b["sma200"]).cumprod(),
    }
    colors = ["#1f77b4", "#ff7f0e", "#333333"]
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.15, 0.30],
        vertical_spacing=0.05,
        subplot_titles=("Growth of 1 (log)", f"{label}: equity weight", "Drawdown"),
    )
    for (name, eq), c in zip(curves.items(), colors):
        fig.add_trace(
            go.Scatter(x=eq.index, y=eq, name=name, line=dict(color=c, width=1.3)), 1, 1
        )
        dd = eq / eq.cummax() - 1
        fig.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd,
                name=f"DD {name}",
                line=dict(color=c, width=1),
                showlegend=False,
            ),
            3,
            1,
        )
    fig.add_trace(
        go.Scatter(
            x=full.index,
            y=full["pos"],
            name="equity weight",
            line_shape="hv",
            fill="tozeroy",
            line=dict(color="#ff7f0e", width=0),
        ),
        2,
        1,
    )
    lo = full.index[0]
    for name, start in period_starts(protocol).items():
        x = max(pd.Timestamp(start), lo)
        fig.add_shape(
            type="line",
            x0=x,
            x1=x,
            y0=0,
            y1=1,
            yref="paper",
            line=dict(color="grey", dash="dot"),
        )
        fig.add_annotation(
            x=x, y=1, yref="paper", text=name, showarrow=False, yanchor="bottom"
        )
    fig.update_yaxes(type="log", row=1, col=1)
    fig.update_yaxes(tickformat=".0%", range=[0, 1.05], row=2, col=1)
    fig.update_yaxes(tickformat=".0%", row=3, col=1)
    fig.update_layout(
        height=760, hovermode="x unified", legend=dict(orientation="h", y=-0.06)
    )
    return fig


def decade_table(full: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    """Annualised excess Sharpe and CAGR per decade: strategy vs B&H vs SMA200."""
    b = bench.reindex(full.index)
    rows = {}
    for dec, idx in full.groupby((full.index.year // 10) * 10).groups.items():
        if len(idx) < 250:
            continue
        f, bb = full.loc[idx], b.loc[idx]
        yrs = len(idx) / 252
        rows[f"{dec}s"] = {
            "Sharpe": bs.excess_sharpe(f["r_strat"], f["r_cash"]),
            "Sharpe B&H": bs.excess_sharpe(bb["bh"], bb["tbill"]),
            "Sharpe SMA200": bs.excess_sharpe(bb["sma200"], bb["tbill"]),
            "CAGR": (1 + f["r_strat"]).prod() ** (1 / yrs) - 1,
            "CAGR B&H": (1 + bb["bh"]).prod() ** (1 / yrs) - 1,
            "CAGR SMA200": (1 + bb["sma200"]).prod() ** (1 / yrs) - 1,
            "time in market": f["pos"].mean(),
        }
    return pd.DataFrame(rows).T


def evidence_lines(
    res, trunc: TruncResult, peek, placebo: dict, breakeven: float
) -> list[str]:
    """Plain-language evidence summary under the frozen criteria."""
    sh, d, p = res.sharpe, res.d_sma200, res.p_vs_sma200
    lines = [
        "Truncation look-ahead test: "
        + ("PASSED" if trunc.passed else f"FAILED ({trunc.n_mismatch} mismatches)")
        + f" on {trunc.n_cuts} cut dates; peek test gain {peek.peek_gain:+.3f}.",
    ]
    for per in ("dev", "val", "holdout"):
        if per in sh:
            pv = f", p vs SMA200 {p[per]:.3f}" if per in p else ""
            lines.append(
                f"{per}: Sharpe {sh[per]:.3f} (vs SMA200 {d[per]:+.3f}, vs B&H {res.d_bh[per]:+.3f}{pv})"
            )
    if getattr(res, "evidence_version", "legacy") == "matched-v1":
        lines.append(
            f"Deflated Sharpe {res.dsr:.3f} with n_trials={res.n_trials}; "
            "evidence_version=matched-v1, gate sample: dev+val execution returns "
            f"(pre-holdout); descriptive full DSR {res.dsr_full:.3f}."
        )
    else:
        lines.append(f"Deflated Sharpe {res.dsr:.3f} with n_trials={res.n_trials}.")
    lines.append(
        f"Placebo: real {placebo['real']:.3f} vs placebo 95th pct {placebo['placebo_q95']:.3f} "
        f"(p {placebo['p_one_sided']:.3f}); break-even cost vs SMA200 full {breakeven:.1f} bp."
    )
    failed = [k for k, v in res.checks.items() if not v and not k.startswith("holdout")]
    verdict = (
        "PASSES the frozen primary metric"
        if res.passes
        else "FAILS the frozen primary metric"
    )
    lines.append(
        f"Verdict: {verdict}"
        + (f" (failed checks: {', '.join(failed)})" if failed else "")
        + f"; holdout {'confirms' if res.holdout_confirms else 'does not confirm'}."
    )
    return lines


__all__ = [
    "LATE_PERIODS",
    "truncate_inputs",
    "TruncResult",
    "truncation_test",
    "run_protocol",
    "dev_sweep",
    "evaluate",
    "register_final",
    "period_starts",
    "plot_growth",
    "decade_table",
    "evidence_lines",
]
