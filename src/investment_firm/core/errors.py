"""Shared error classifier for the committee pipeline.

Any analyst, debate, or synthesis step that fails must produce an explicit,
labelled ERROR outcome stating exactly what failed — never a bland NEUTRAL that
reads like real analysis. This module is the single place that mints those
outcomes so all three layers stay consistent.

Invariants preserved (see AGENTS.md):
- raw API error text goes into ``key_risks`` as ``"API error: <msg>"``, never
  into ``rationale``;
- ERROR views are ``grounded=False`` with ``conviction=0``;
- the literal ``"model did not return structured JSON"`` risk string is kept so
  existing warning scans keep firing.
"""

from __future__ import annotations

from typing import List, Optional

from .schemas import AnalystView

PARSE_FAILURE_RISK = "model did not return structured JSON"

_RAW_TEXT_LIMIT = 400


def error_summary(stage: str, detail: str) -> str:
    """One-line, unmistakable description of a failed pipeline stage."""
    return f"ERROR: {stage} failed — {detail}".strip()


def api_error_view(role: str, model: str, detail: str) -> AnalystView:
    """Explicit ERROR view for a completion/API failure.

    The raw provider message stays in key_risks; the rationale never carries it.
    """
    return AnalystView(
        role=role,
        model=model,
        stance="ERROR",
        conviction=0,
        grounded=False,
        error=f"API/completion failure: {detail}",
        rationale="ERROR: completion failed — no analysis produced (see key risks)",
        key_risks=[f"API error: {detail}"],
    )


def parse_error_view(
    role: str,
    model: str,
    raw_text: str,
    *,
    detail: str = "model did not return the required JSON analyst view",
    extra_risks: Optional[List[str]] = None,
) -> AnalystView:
    """Explicit ERROR view for an unparseable (prose/refusal/truncated) response.

    Carries the truncated raw model text so the operator can see exactly what
    came back, clearly marked as an error rather than analysis.
    """
    raw = (raw_text or "").strip()
    if len(raw) > _RAW_TEXT_LIMIT:
        raw = raw[:_RAW_TEXT_LIMIT] + "…"
    rationale = (
        "ERROR: model did not return structured JSON. "
        f"Raw output (truncated): {raw or '(empty response)'}"
    )
    risks = [PARSE_FAILURE_RISK]
    for risk in extra_risks or []:
        if risk not in risks:
            risks.append(risk)
    return AnalystView(
        role=role,
        model=model,
        stance="ERROR",
        conviction=0,
        grounded=False,
        error=detail,
        rationale=rationale,
        key_risks=risks,
    )
