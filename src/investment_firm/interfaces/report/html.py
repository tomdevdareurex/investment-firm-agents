"""Self-contained HTML report for a finished committee run (no scripts, no remote assets)."""

from __future__ import annotations

from typing import Any, Dict, List

from investment_firm.core.horizon import HORIZONS

from ._html import (
    _NA,
    _badge,
    _disclaimer_footer,
    _dots,
    _esc,
    _glossary_from_dicts,
    _glossary_section,
    _int,
    _link,
    _list,
    _methodology_section,
    _num,
    _page,
    _section,
    _table,
    _usd,
)

_REC_KIND = {"BUY": "pos", "SELL": "neg", "AVOID": "neg", "HOLD": "neu", "ERROR": "neg"}
_STANCE_KIND = {"BULLISH": "pos", "BEARISH": "neg", "NEUTRAL": "neu", "ERROR": "neg"}

COST_NOTE = (
    "USD figures come from config/costs.yaml and are backend-aware: a Databricks run "
    "is costed from the Databricks rate card, a Playground run from vendor list "
    "prices. Output tokens bill at 4-6x the input rate, so USD in and USD out are "
    "tracked separately. Long-context tiers are not modelled, so a long-context run "
    "costs more than shown. cost~ is a unit-less weight used for budget guards."
)


def _horizon_label(result: Dict[str, Any]) -> str:
    if result.get("horizon_label"):
        return str(result["horizon_label"])
    hz = HORIZONS.get(str(result.get("horizon") or ""))
    return hz.label if hz else _NA


def _cover(result: Dict[str, Any]) -> str:
    rec = str(result.get("recommendation") or "ERROR")
    synth = result.get("synth_role") or "CIO"
    model = f" ({result['synth_model']})" if result.get("synth_model") else ""
    meta = "".join(
        f"<span><strong>{_esc(k)}:</strong> {_esc(v)}</span>"
        for k, v in (
            ("Horizon", _horizon_label(result)),
            ("Profile", result.get("profile") or _NA),
            ("Generated", result.get("generated_at") or _NA),
        )
    )
    return (
        '<section id="cover">\n<h1>Investment Committee Report</h1>\n'
        f'<p class="meta">{meta}</p>\n'
        f'<div class="card"><p><strong>Question:</strong> '
        f"{_esc(result.get('question') or _NA)}</p>"
        f"<p>{_badge(rec, _REC_KIND.get(rec, 'neu'))} "
        f"{_esc(result.get('recommendation_plain') or '')}</p>"
        f"<p><strong>Confidence:</strong> {_dots(result.get('confidence', 0))}</p>"
        f'<p class="note">Final ruling by {_esc(str(synth).upper())}{_esc(model)}</p>'
        "</div>\n</section>"
    )


def _plain(result: Dict[str, Any]) -> str:
    headline = result.get("headline") or ""
    inner = f'<p class="lead">{_esc(headline)}</p>' if headline else ""
    inner += f"<p>{_esc(result.get('summary') or _NA)}</p>"
    return _section("plain", "In plain words", inner)


def _view_card(view: Dict[str, Any], stance_plain: Dict[str, str]) -> str:
    stance = str(view.get("stance") or "NEUTRAL")
    parts = [
        f"<h3>{_esc(view.get('role'))} "
        f"{_badge(stance, _STANCE_KIND.get(stance, 'neu'))}</h3>",
        f'<p class="note">{_esc(stance_plain.get(stance, ""))} · model '
        f"{_esc(view.get('model') or _NA)} · confidence "
        f"{_esc(view.get('conviction', 0))}/5</p>",
    ]
    if stance == "ERROR":
        parts.append(
            f'<div class="error">ERROR — '
            f"{_esc(view.get('error') or 'analysis step failed')}</div>"
        )
    parts.append(f"<p>{_esc(view.get('rationale') or '(none)')}</p>")
    if view.get("key_risks"):
        parts.append("<h3>Key risks</h3>" + _list(view["key_risks"]))
    if view.get("evidence"):
        parts.append("<h3>Evidence</h3>" + _list(view["evidence"], linkify=True))
    cites = [c for c in view.get("citations") or [] if isinstance(c, dict)]
    if cites:
        parts.append(
            "<h3>Web sources</h3><ul>"
            + "".join(
                f"<li>{_link(c.get('url'), c.get('title') or c.get('url'))}</li>"
                for c in cites
            )
            + "</ul>"
        )
    return '<div class="card">' + "".join(parts) + "</div>"


def _specialists(result: Dict[str, Any]) -> str:
    views = [v for v in result.get("views") or [] if isinstance(v, dict)]
    if not views:
        return _section(
            "specialists", "How each specialist saw it", f'<p class="note">{_NA}</p>'
        )
    stance_plain = result.get("stance_plain") or {}
    rows = [
        [
            str(v.get("role", "")),
            stance_plain.get(v.get("stance"), str(v.get("stance", ""))),
            f"{v.get('conviction', 0)}/5",
            "Yes" if v.get("grounded") else "No",
        ]
        for v in views
    ]
    table = _table(["Role", "View", "Confidence", "Backed by live data?"], rows)
    cards = "".join(_view_card(v, stance_plain) for v in views)
    return _section("specialists", "How each specialist saw it", table + cards)


def _debate(result: Dict[str, Any]) -> str:
    turns = [t for t in result.get("debate") or [] if isinstance(t, dict)]
    if not turns:
        inner = (
            '<p class="note">No debate was run (simple mode or debate disabled).</p>'
        )
        return _section("debate", "Bull vs Bear debate", inner)
    cards = "".join(
        f'<div class="card"><h3>{i}. {_esc(t.get("speaker"))}</h3>'
        f'<p class="note">{_esc(t.get("model") or "")}</p>'
        + (
            f'<div class="error">{_esc(t.get("text"))}</div>'
            if t.get("error")
            else f"<p>{_esc(t.get('text'))}</p>"
        )
        + "</div>"
        for i, t in enumerate(turns, start=1)
    )
    if result.get("debate_summary"):
        judge = str(result.get("debate_judge_role") or "").upper()
        model = result.get("debate_judge_model") or ""
        who = f" — {judge} as referee ({model})" if judge else ""
        cards += (
            f"<h3>Verdict{_esc(who)}</h3>"
            f"<p>{_esc(result.get('debate_summary'))}</p>"
        )
    return _section("debate", "Bull vs Bear debate", cards)


def _briefing(result: Dict[str, Any]) -> str:
    text = result.get("briefing") or ""
    if not text:
        return _section(
            "briefing",
            "Research briefing",
            '<p class="note">No briefing (simple mode skips the librarian).</p>',
        )
    role = str(result.get("briefing_role") or "").upper()
    model = result.get("briefing_model") or ""
    who = f'<p class="note">{_esc(role)} ({_esc(model)})</p>' if role else ""
    return _section(
        "briefing", "Research briefing", f'{who}<pre class="wrap">{_esc(text)}</pre>'
    )


def _sources(result: Dict[str, Any]) -> str:
    web = [s for s in result.get("web_sources") or [] if isinstance(s, dict)]
    other = result.get("sources") or []
    inner = ""
    if web:
        inner += "<h3>Web sources</h3><ul>" + "".join(
            f"<li>{_link(s.get('url'), s.get('title') or s.get('url'))}</li>"
            for s in web
        )
        inner += "</ul>"
    inner += "<h3>Other sources</h3>" + _list(other, linkify=True)
    return _section("sources", "Sources", inner)


def _costs(result: Dict[str, Any]) -> str:
    budget = result.get("token_budget") or 0
    tokens = _int(result.get("total_tokens"))
    if budget:
        tokens += f" / {_int(budget)}"
    calls = [c for c in result.get("call_records") or [] if isinstance(c, dict)]
    head = (
        f"<p><strong>Estimated cost:</strong> {_usd(result.get('cost_usd_estimate'))} "
        f"(in {_usd(result.get('cost_usd_input_estimate'))}, out "
        f"{_usd(result.get('cost_usd_output_estimate'))}) · <strong>Tokens:</strong> "
        f"{_esc(tokens)} · <strong>LLM calls:</strong> {len(calls)}</p>"
    )
    by_model = [m for m in result.get("cost_by_model") or [] if isinstance(m, dict)]
    model_rows = [
        [
            str(m.get("model", "")),
            _int(m.get("calls")),
            _int(m.get("input_tokens")),
            _int(m.get("output_tokens")),
            _num(m.get("cost_units")),
            _usd(m.get("cost_usd_input")),
            _usd(m.get("cost_usd_output")),
            _usd(m.get("cost_usd")),
            str(m.get("price_source", "")),
            f"{m.get('price_basis', '')} {m.get('price_confidence', '')}".strip(),
        ]
        for m in by_model
    ]
    call_rows = [
        [
            str(c.get("agent", "")),
            str(c.get("model", "")),
            _int(c.get("input_tokens")),
            _int(c.get("output_tokens")),
            _usd(c.get("cost_usd")),
            f"{_num(c.get('latency_s'), 1)}s",
        ]
        for c in calls
    ]
    inner = head
    if model_rows:
        inner += "<h3>By model</h3>" + _table(
            [
                "Model",
                "Calls",
                "Tok in",
                "Tok out",
                "cost~",
                "USD in",
                "USD out",
                "USD tot",
                "Pricing",
                "Rate",
            ],
            model_rows,
            num_cols=(1, 2, 3, 4, 5, 6, 7),
        )
    if call_rows:
        inner += "<h3>Per call</h3>" + _table(
            ["Agent", "Model", "Tok in", "Tok out", "USD", "Latency"],
            call_rows,
            num_cols=(2, 3, 4, 5),
        )
    inner += f'<p class="note">{_esc(COST_NOTE)}</p>'
    return _section("costs", "Cost of this analysis", inner)


def _warnings(result: Dict[str, Any]) -> str:
    items: List[str] = list(result.get("warnings") or [])
    if not items:
        return _section(
            "warnings", "Warnings and data gaps", '<p class="note">None.</p>'
        )
    return _section(
        "warnings", "Warnings and data gaps", f'<div class="warn">{_list(items)}</div>'
    )


def render_committee_report(result: Dict[str, Any]) -> str:
    """Render ``result`` (from :func:`build_run_result`) as one static HTML page."""
    result = result or {}
    body = "\n".join(
        [
            _cover(result),
            _plain(result),
            _section(
                "why", "Why the committee thinks so", _list(result.get("key_reasons"))
            ),
            _section("risks", "What could go wrong", _list(result.get("main_risks"))),
            _section("watch", "What to watch", _list(result.get("what_to_watch"))),
            _specialists(result),
            _debate(result),
            _briefing(result),
            _sources(result),
            _warnings(result),
            _costs(result),
            _glossary_section(_glossary_from_dicts(result.get("glossary") or [])),
            _methodology_section(),
            _disclaimer_footer(),
        ]
    )
    return _page("Investment Committee Report", body)
