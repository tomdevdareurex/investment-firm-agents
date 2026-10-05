"""Self-contained HTML report for a portfolio analysis (no scripts, no remote assets)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from investment_firm.core.glossary import entries, find_terms
from investment_firm.core.horizon import HORIZONS

from ._html import (
    _NA,
    _badge,
    _disclaimer_footer,
    _esc,
    _finite,
    _glossary_section,
    _list,
    _methodology_section,
    _num,
    _page,
    _pct,
    _section,
    _svg_line,
    _svg_multi_line,
    _table,
    _usd,
)

_ALWAYS_EXPLAIN = [
    "VaR",
    "Expected Shortfall",
    "max drawdown",
    "Sharpe ratio",
    "Sortino ratio",
    "Calmar ratio",
    "CAGR",
    "beta",
    "tracking error",
    "rebalancing",
]

# (key, label, kind) — kind "pct" | "num" | "text"
_STAT_ROWS = [
    ("total_return", "Total return", "pct"),
    ("cagr", "Average yearly growth (CAGR)", "pct"),
    ("ann_vol", "Annualised volatility", "pct"),
    ("sharpe", "Sharpe ratio", "num"),
    ("sortino", "Sortino ratio", "num"),
    ("calmar", "Calmar ratio", "num"),
    ("downside_dev", "Downside deviation (annualised)", "pct"),
    ("max_drawdown", "Maximum drawdown", "pct"),
    ("peak_date", "Drawdown peak date", "text"),
    ("trough_date", "Drawdown trough date", "text"),
    ("recovery_date", "Recovery date", "text"),
    ("duration_days", "Drawdown duration (calendar days)", "text"),
    ("hist_var_1d", "1-day historical VaR", "pct"),
    ("param_var_1d", "1-day parametric VaR", "pct"),
    ("es_1d", "1-day Expected Shortfall", "pct"),
    ("var_10d_sqrt_scaled", "10-day VaR (√10 approximation)", "pct"),
    ("best_day", "Best day", "pct"),
    ("worst_day", "Worst day", "pct"),
    ("pct_positive_days", "Share of up days", "pct"),
    ("skew", "Skew", "num"),
    ("excess_kurtosis", "Excess kurtosis", "num"),
    ("beta", "Beta vs benchmark", "num"),
    ("correlation", "Correlation with benchmark", "num"),
    ("tracking_error", "Tracking error", "pct"),
    ("information_ratio", "Information ratio", "num"),
    ("benchmark_cagr", "Benchmark yearly growth", "pct"),
    ("excess_cagr", "Yearly growth vs benchmark", "pct"),
    ("n_obs", "Daily observations", "text"),
    ("level", "VaR confidence level", "pct"),
    ("rf_annual", "Risk-free rate used", "pct"),
]


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return _NA
    if kind == "pct":
        return _pct(value)
    if kind == "num":
        return _num(value)
    return str(value)


def _cover(entry: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    params = analysis.get("params") or {}
    window = analysis.get("window") or {}
    hz = HORIZONS.get(str(params.get("horizon") or ""))
    meta = "".join(
        f"<span><strong>{_esc(k)}:</strong> {_esc(v)}</span>"
        for k, v in (
            ("Window", f"{window.get('start', _NA)} → {window.get('end', _NA)}"),
            ("Observations", window.get("n_obs", _NA)),
            ("Benchmark", params.get("benchmark") or _NA),
            ("Horizon", hz.label if hz else _NA),
            ("Rebalancing", params.get("rebalance") or _NA),
            ("Data as of", analysis.get("as_of") or _NA),
            (
                "Generated",
                entry.get("generated_at")
                or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            ),
        )
    )
    rows = [
        [str(p.get("ticker", "")), _pct(p.get("weight"))]
        for p in analysis.get("positions") or []
    ]
    return (
        '<section id="cover">\n<h1>Portfolio Analytics Report</h1>\n'
        f'<p class="meta">{meta}</p>\n'
        + _table(["Ticker", "Weight"], rows, num_cols=(1,))
        + "</section>"
    )


def _plain_sentences(analysis: Dict[str, Any]) -> List[str]:
    s = analysis.get("stats") or {}
    params = analysis.get("params") or {}
    out = [
        f"Over the period the portfolio grew by {_pct(s.get('total_return'))} "
        f"({_pct(s.get('cagr'))} per year on average)."
    ]
    if s.get("peak_date"):
        recovered = (
            f"recovered on {s['recovery_date']}"
            if s.get("recovery_date")
            else "not yet recovered"
        )
        out.append(
            f"The worst fall from a peak was {_pct(s.get('max_drawdown'))} (from "
            f"{s['peak_date']} to {s.get('trough_date')}; {recovered})."
        )
    else:
        out.append("The portfolio never fell below a previous high in this window.")
    level = _finite(s.get("level")) or 0.99
    tail = round((1 - level) * 100, 2)
    out.append(
        f"On a typical bad day (1 in {round(100 / tail) if tail else 100} at "
        f"{level * 100:.0f}% confidence) you could lose about "
        f"{_pct(s.get('hist_var_1d'))} or more (VaR); on the worst {tail:g}% of days "
        f"the average loss was {_pct(s.get('es_1d'))} (Expected Shortfall)."
    )
    out.append(f"Return per unit of risk (Sharpe) was {_num(s.get('sharpe'))}.")
    if s.get("benchmark_cagr") is not None:
        diff = _finite(s.get("excess_cagr")) or 0.0
        word = "ahead of" if diff >= 0 else "behind"
        out.append(
            f"Compared with {params.get('benchmark', 'the benchmark')} "
            f"({_pct(s.get('benchmark_cagr'))} per year), the portfolio was "
            f"{_pct(abs(diff))} per year {word} it, with a beta of "
            f"{_num(s.get('beta'))}."
        )
    return out


def _corr_style(v: Optional[float]) -> str:
    x = _finite(v)
    if x is None:
        return ""
    alpha = min(abs(x), 1.0) * 0.55
    rgb = "47, 91, 211" if x >= 0 else "179, 38, 30"
    return f"background: rgba({rgb}, {alpha:.2f})"


def _positions(analysis: Dict[str, Any]) -> str:
    rows = [
        [
            str(p.get("ticker", "")),
            _pct(p.get("weight")),
            _pct(p.get("total_return")),
            _pct(p.get("cagr")),
            _pct(p.get("ann_vol")),
            _pct(p.get("max_drawdown")),
            _pct(p.get("contribution_to_return")),
        ]
        for p in analysis.get("position_stats") or []
    ]
    table = _table(
        [
            "Ticker",
            "Weight",
            "Total return",
            "Yearly growth",
            "Volatility",
            "Max drawdown",
            "Contribution*",
        ],
        rows,
        num_cols=(1, 2, 3, 4, 5, 6),
    )
    note = (
        '<p class="note">* Contribution = weight × the holding\'s own return '
        "(a buy-and-hold approximation).</p>"
    )
    return _section("positions", "Positions", table + note)


def _diversification(analysis: Dict[str, Any]) -> str:
    div = analysis.get("diversification") or {}
    summary = _table(
        ["Measure", "Value"],
        [
            ["Concentration (HHI, 1 = single holding)", _num(div.get("hhi"), 3)],
            ["Effective number of holdings", _num(div.get("effective_n"))],
            ["Largest weight", _pct(div.get("largest_weight"))],
            ["Average pairwise correlation", _num(div.get("avg_pairwise_corr"))],
        ],
        num_cols=(1,),
    )
    matrix = div.get("correlation_matrix") or {}
    tickers = [str(t) for t in matrix.get("tickers") or []]
    values = matrix.get("values") or []
    corr = ""
    if tickers and values:
        rows = [[t] + [_num(v) for v in values[i]] for i, t in enumerate(tickers)]
        styles = [
            [""] + [_corr_style(v) for v in values[i]] for i in range(len(tickers))
        ]
        corr = "<h3>Correlation of daily returns</h3>" + _table(
            [""] + tickers,
            rows,
            num_cols=tuple(range(1, len(tickers) + 1)),
            row_styles=styles,
        )
    return _section("diversification", "Diversification", summary + corr)


def _rebalancing(analysis: Dict[str, Any]) -> str:
    labels = {
        "none": "Buy-and-hold (no rebalancing)",
        "monthly": "Rebalanced monthly",
        "daily": "Rebalanced daily (constant mix)",
        "benchmark": "Benchmark",
    }
    rows = []
    for key, label in labels.items():
        s = (analysis.get("rebalance_comparison") or {}).get(key)
        if not s:
            rows.append([label, _NA, _NA, _NA, _NA, _NA])
            continue
        rows.append(
            [
                label,
                _pct(s.get("total_return")),
                _pct(s.get("cagr")),
                _pct(s.get("ann_vol")),
                _num(s.get("sharpe")),
                _pct(s.get("max_drawdown")),
            ]
        )
    table = _table(
        ["Approach", "Total return", "Yearly growth", "Volatility", "Sharpe", "Max DD"],
        rows,
        num_cols=(1, 2, 3, 4, 5),
    )
    return _section("rebalancing", "Rebalancing comparison", table)


def _strategies(analysis: Dict[str, Any]) -> str:
    overlays = analysis.get("strategy_overlays") or []
    note = (
        '<p class="note">Historical simulation only — rules are applied with a '
        "one-day delay to avoid look-ahead; past results do not predict future "
        "returns.</p>"
    )
    if not overlays:
        return _section(
            "strategies",
            "Strategy backtests",
            f'<p class="note">No strategy backtests were run.</p>{note}',
        )
    rows = []
    for o in overlays:
        s = o.get("stats") or {}
        trades = sum(int(t.get("n_trades") or 0) for t in o.get("per_ticker") or [])
        rows.append(
            [
                str(o.get("strategy", "")),
                str(o.get("rule", "")),
                _pct(s.get("cagr")),
                _pct(s.get("ann_vol")),
                _pct(s.get("max_drawdown")),
                _num(s.get("sharpe")),
                str(trades),
            ]
        )
    table = _table(
        [
            "Strategy",
            "Rule",
            "Yearly growth",
            "Volatility",
            "Max DD",
            "Sharpe",
            "Trades",
        ],
        rows,
        num_cols=(2, 3, 4, 5, 6),
    )
    return _section("strategies", "Strategy backtests", table + note)


def _suggestion(entry: Dict[str, Any]) -> str:
    sug = entry.get("suggestion")
    if not sug:
        return ""
    if sug.get("status") != "ok":
        inner = (
            f'<div class="error">The advisor did not return a usable answer: '
            f"{_esc(sug.get('error') or 'unknown error')}</div>"
        )
    else:
        ideas = "".join(
            f'<div class="card"><p><strong>{_esc(i.get("idea"))}</strong> '
            f'{_badge(i.get("type", "watch"), "acc")}</p>'
            f"<p>{_esc(i.get('why') or '')}</p></div>"
            for i in sug.get("ideas") or []
        )
        inner = (
            f"<p>{_esc(sug.get('assessment'))}</p>"
            f"<h3>Strengths</h3>{_list(sug.get('strengths'))}"
            f"<h3>Weaknesses</h3>{_list(sug.get('weaknesses'))}"
            f"<h3>Options to consider</h3>{ideas or _list([])}"
            f"<h3>Caveats</h3>{_list(sug.get('caveats'))}"
        )
    cost = entry.get("suggestion_cost") or {}
    inner += (
        f'<p class="note">Model: {_esc(sug.get("model") or _NA)}. This section cost '
        f"about {_usd(cost.get('cost_usd'))} ({_esc(cost.get('total_tokens', 0))} "
        "tokens).</p>"
    )
    return _section("suggestions", "Suggestions", inner)


def _glossary(entry: Dict[str, Any]) -> List[Any]:
    sug = entry.get("suggestion") or {}
    texts = [label for _, label, _ in _STAT_ROWS]
    texts += [str(sug.get("assessment") or "")]
    texts += [
        str(x) for k in ("strengths", "weaknesses", "caveats") for x in sug.get(k) or []
    ]
    texts += [f"{i.get('idea')} {i.get('why')}" for i in sug.get("ideas") or []]
    found = find_terms(*texts)
    names = {e.term for e in found}
    return found + [e for e in entries(_ALWAYS_EXPLAIN) if e.term not in names]


def render_portfolio_report(entry: Dict[str, Any]) -> str:
    """Render a stored portfolio analysis (``analysis`` + optional ``suggestion``)."""
    analysis = (entry or {}).get("analysis") or {}
    series = analysis.get("series") or {}
    stats = analysis.get("stats") or {}
    params = analysis.get("params") or {}
    plain = "".join(f"<p>{_esc(s)}</p>" for s in _plain_sentences(analysis))
    stat_rows = [[label, _fmt(stats.get(k), kind)] for k, label, kind in _STAT_ROWS]
    body = "\n".join(
        [
            _cover(entry or {}, analysis),
            _section("plain", "Key numbers in plain words", plain),
            _section(
                "growth",
                "Growth of 1 unit vs benchmark",
                _svg_multi_line(
                    [
                        ("Portfolio", series.get("equity") or [], "#2f5bd3"),
                        (
                            str(params.get("benchmark") or "Benchmark"),
                            series.get("benchmark_equity") or [],
                            "#9aa4b2",
                        ),
                    ],
                    baseline=1.0,
                    label="Growth of 1 unit",
                ),
            ),
            _section(
                "drawdowns",
                "Drawdowns",
                _svg_line(
                    series.get("drawdown") or [],
                    color="#b3261e",
                    baseline=0.0,
                    label="Drawdown",
                    fmt=_pct,
                ),
            ),
            _section(
                "rolling-vol",
                "Rolling volatility (3 months)",
                _svg_line(
                    series.get("rolling_vol") or [],
                    color="#b7791f",
                    label="Rolling volatility",
                    fmt=_pct,
                ),
            ),
            _section(
                "stats",
                "Full statistics",
                _table(["Statistic", "Value"], stat_rows, num_cols=(1,)),
            ),
            _positions(analysis),
            _diversification(analysis),
            _rebalancing(analysis),
            _strategies(analysis),
            _suggestion(entry or {}),
            _section(
                "warnings",
                "Warnings",
                (
                    f'<div class="warn">{_list(analysis.get("warnings"))}</div>'
                    if analysis.get("warnings")
                    else '<p class="note">None.</p>'
                ),
            ),
            _glossary_section(_glossary(entry or {})),
            _methodology_section(),
            _disclaimer_footer(),
        ]
    )
    return _page("Portfolio Analytics Report", body)
