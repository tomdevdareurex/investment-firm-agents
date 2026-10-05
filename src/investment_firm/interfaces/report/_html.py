"""Shared HTML building blocks for the self-contained, script-free reports.

Every dynamic value goes through :func:`_esc`. Links are only emitted for
http(s) URLs (checked via ``urlsplit``); everything else renders as text.
"""

from __future__ import annotations

import html
import math
import re
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import investment_firm
from investment_firm.core.glossary import METHODOLOGY, GlossaryEntry

_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)

_CSS = """
:root { --ink:#1d2433; --muted:#5b6475; --line:#d9dee7; --bg:#f6f7fa; --card:#fff;
  --pos:#1b7f5a; --neg:#b3261e; --neu:#6b7280; --acc:#2f5bd3; }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.55 Georgia, 'Times New Roman', serif; color:var(--ink);
  background:var(--bg); }
main { max-width:960px; margin:0 auto; padding:32px 24px 64px; }
h1,h2,h3 { font-family:'Segoe UI', Helvetica, Arial, sans-serif; line-height:1.25; }
h1 { font-size:30px; margin:0 0 8px; }
h2 { font-size:21px; margin:36px 0 12px; padding-bottom:6px;
  border-bottom:2px solid var(--line); }
h3 { font-size:16px; margin:18px 0 6px; }
section { margin-bottom:8px; }
.meta { color:var(--muted); font:13px 'Segoe UI', Helvetica, Arial, sans-serif; }
.meta span { margin-right:18px; display:inline-block; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:14px 18px; margin:12px 0; }
.lead { font-size:18px; font-weight:bold; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; color:#fff;
  font:600 12px 'Segoe UI', Helvetica, Arial, sans-serif; letter-spacing:.03em;
  vertical-align:middle; }
.badge--pos { background:var(--pos); } .badge--neg { background:var(--neg); }
.badge--neu { background:var(--neu); } .badge--acc { background:var(--acc); }
.dots { letter-spacing:2px; color:var(--acc); }
table { border-collapse:collapse; width:100%; margin:8px 0 14px;
  font:13px 'Segoe UI', Helvetica, Arial, sans-serif; }
th,td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left;
  vertical-align:top; }
th { background:#eef1f6; font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
pre.wrap { white-space:pre-wrap; word-wrap:break-word; background:var(--card);
  border:1px solid var(--line); border-radius:8px; padding:12px;
  font:13px/1.5 Consolas, 'Courier New', monospace; }
.error { border-left:4px solid var(--neg); background:#fdeceb; padding:10px 14px;
  border-radius:6px; margin:8px 0; }
.warn { border-left:4px solid #b7791f; background:#fdf6e7; padding:10px 14px;
  border-radius:6px; }
.note { color:var(--muted); font-size:13px; }
svg { width:100%; height:auto; background:var(--card); border:1px solid var(--line);
  border-radius:8px; }
footer { margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--muted); font-size:13px; }
dl dt { font-weight:bold; margin-top:10px; } dl dd { margin:2px 0 0 0; }
@media print { body { background:#fff; } .card, table, svg { page-break-inside:avoid; }
  h2 { page-break-after:avoid; } }
"""

_NA = "(not available)"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _is_web_url(url: object) -> bool:
    try:
        return urlsplit(str(url)).scheme.lower() in {"http", "https"}
    except ValueError:
        return False


def _link(url: object, label: object = None) -> str:
    text = _esc(label if label else url)
    if _is_web_url(url):
        return f'<a href="{_esc(url)}" rel="noopener noreferrer">{text}</a>'
    return text


def _linkify(text: object) -> str:
    """Escape ``text`` and turn the first embedded http(s) URL into a safe link."""
    raw = "" if text is None else str(text)
    match = _URL_IN_TEXT.search(raw)
    if not match:
        return _esc(raw)
    url = match.group(0)
    return _esc(raw[: match.start()]) + _link(url, url) + _esc(raw[match.end() :])


def _page(title: str, body_html: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f"<main>\n{body_html}\n</main>\n</body>\n</html>\n"
    )


def _section(sid: str, title: str, inner: str) -> str:
    return f'<section id="{_esc(sid)}">\n<h2>{_esc(title)}</h2>\n{inner}\n</section>'


def _list(items: Iterable[object], *, linkify: bool = False) -> str:
    rows = [i for i in (items or []) if str(i).strip()]
    if not rows:
        return f'<p class="note">{_NA}</p>'
    fmt = _linkify if linkify else _esc
    return "<ul>" + "".join(f"<li>{fmt(i)}</li>" for i in rows) + "</ul>"


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    num_cols: Sequence[int] = (),
    *,
    raw_cols: Sequence[int] = (),
    row_styles: Optional[Sequence[Sequence[str]]] = None,
) -> str:
    """Build a table. Cells are escaped unless their column is in ``raw_cols``.

    ``raw_cols`` cells must already be safe HTML built by these helpers.
    ``row_styles`` gives optional per-cell inline styles computed from numbers.
    """
    head = "".join(
        f'<th class="num">{_esc(h)}</th>' if i in num_cols else f"<th>{_esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = []
    for r_i, row in enumerate(rows):
        cells = []
        for i, cell in enumerate(row):
            content = cell if i in raw_cols else _esc(cell)
            cls = ' class="num"' if i in num_cols else ""
            style = ""
            if row_styles and row_styles[r_i][i]:
                style = f' style="{_esc(row_styles[r_i][i])}"'
            cells.append(f"<td{cls}{style}>{content}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _badge(text: object, kind: str = "neu") -> str:
    return f'<span class="badge badge--{_esc(kind)}">{_esc(text)}</span>'


def _dots(n: object, out_of: int = 5) -> str:
    try:
        k = max(0, min(out_of, int(n)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        k = 0
    return f'<span class="dots">{"●" * k}{"○" * (out_of - k)}</span> {k} / {out_of}'


def _finite(x: object) -> Optional[float]:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _pct(x: object, dp: int = 2) -> str:
    v = _finite(x)
    return _NA if v is None else f"{v * 100:.{dp}f}%"


def _num(x: object, dp: int = 2) -> str:
    v = _finite(x)
    return _NA if v is None else f"{v:,.{dp}f}"


def _usd(x: object) -> str:
    v = _finite(x)
    return _NA if v is None else f"${v:,.4f}"


def _int(x: object) -> str:
    v = _finite(x)
    return _NA if v is None else f"{int(v):,}"


def _polyline(
    values: List[float], lo: float, hi: float, width: int, height: int, pad: int
) -> str:
    span = (hi - lo) or 1.0
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (width - 2 * pad) * (i / max(n - 1, 1))
        y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _svg_multi_line(
    series: Sequence[Tuple[str, Sequence[Tuple[str, float]], str]],
    *,
    width: int = 760,
    height: int = 220,
    baseline: Optional[float] = None,
    label: str = "",
    fmt=_num,
) -> str:
    """Inline SVG with one polyline per ``(name, [(date, value)], colour)``."""
    clean = []
    for name, points, color in series:
        pts = [(str(d), _finite(v)) for d, v in (points or [])]
        pts = [(d, v) for d, v in pts if v is not None]
        if len(pts) >= 2:
            clean.append((name, pts, color))
    if not clean:
        return f'<p class="note">{_esc(label)} (no data)</p>'
    values = [v for _, pts, _ in clean for _, v in pts]
    lo, hi = min(values), max(values)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    pad = 28
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(label)}">'
    ]
    if baseline is not None:
        y = pad + (height - 2 * pad) * (1 - (baseline - lo) / ((hi - lo) or 1.0))
        parts.append(
            f'<line x1="{pad}" x2="{width - pad}" y1="{y:.1f}" y2="{y:.1f}" '
            'stroke="#9aa4b2" stroke-dasharray="4 4" />'
        )
    for _, pts, color in clean:
        poly = _polyline([v for _, v in pts], lo, hi, width, height, pad)
        parts.append(
            f'<polyline fill="none" stroke="{_esc(color)}" stroke-width="1.6" '
            f'points="{poly}" />'
        )
    first, last = clean[0][1][0][0], clean[0][1][-1][0]
    text_style = 'font-family="Segoe UI, Arial" font-size="11" fill="#5b6475"'
    parts.append(f'<text x="{pad}" y="16" {text_style}>max {_esc(fmt(hi))}</text>')
    parts.append(
        f'<text x="{pad}" y="{height - 8}" {text_style}>min {_esc(fmt(lo))}</text>'
    )
    parts.append(
        f'<text x="{width // 2}" y="{height - 8}" text-anchor="middle" {text_style}>'
        f"{_esc(first)} → {_esc(last)}</text>"
    )
    legend_x = width - pad
    for i, (name, _, color) in enumerate(clean):
        parts.append(
            f'<text x="{legend_x}" y="{16 + 14 * i}" text-anchor="end" '
            f'font-family="Segoe UI, Arial" font-size="11" fill="{_esc(color)}">'
            f"{_esc(name)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_line(
    series: Sequence[Tuple[str, float]],
    *,
    color: str = "#2f5bd3",
    baseline: Optional[float] = None,
    label: str = "",
    fmt=_num,
    width: int = 760,
    height: int = 220,
) -> str:
    return _svg_multi_line(
        [(label, series, color)],
        width=width,
        height=height,
        baseline=baseline,
        label=label,
        fmt=fmt,
    )


def _glossary_section(entries: Sequence[GlossaryEntry], sid: str = "glossary") -> str:
    if not entries:
        return _section(sid, "Glossary", f'<p class="note">{_NA}</p>')
    body = "<dl>" + "".join(
        f"<dt>{_esc(e.term)}</dt><dd>{_esc(e.plain)}<br>"
        f'<span class="note">How it is calculated: {_esc(e.how_calculated)}</span></dd>'
        for e in entries
    )
    return _section(sid, "Glossary", body + "</dl>")


def _glossary_from_dicts(items: Sequence[dict]) -> List[GlossaryEntry]:
    out = []
    for item in items or []:
        if isinstance(item, dict) and item.get("term"):
            out.append(
                GlossaryEntry(
                    str(item.get("term")),
                    (),
                    str(item.get("plain", "")),
                    str(item.get("how_calculated", "")),
                )
            )
    return out


def _methodology_section() -> str:
    body = "<dl>" + "".join(
        f"<dt>{_esc(title)}</dt><dd>{_esc(text)}</dd>" for title, text in METHODOLOGY
    )
    return _section("methodology", "How the numbers are calculated", body + "</dl>")


def _disclaimer_footer() -> str:
    return f"<footer><p>{_esc(investment_firm.DISCLAIMER)}</p></footer>"
