"""Shared prompt scaffolding: base header, frozen JSON contract, composition.

The analyst JSON output contract is FROZEN — ``Agent._parse`` /
``_salvage_fields`` / ``_to_view`` in ``core/agent.py`` depend on it.
``compose()`` appends :data:`JSON_CONTRACT` to every prompt so no role body
can accidentally drop it. Prompts are plain strings; no llm imports, no
model-family branching (core/ stays format-agnostic).
"""

from __future__ import annotations

# Identity + guardrails shared by every role. ``.format(role=..., date=...)``.
BASE_HEADER = (
    "You are the {role} at a buy-side investment firm.\n"
    "This is decision-support only — never advise executing orders.\n"
    "Today's date is {date}. Your training data may be outdated — prefer tool results, "
    "web search, and the briefing packet; if current data is unavailable, state the gap "
    "explicitly instead of guessing. Label any figure you could not verify via tools, "
    "web search, or the briefing as 'unverified (training data)'.\n"
)

# FROZEN output contract. Plain string — never ``.format()``-ed, so the JSON
# braces stay single and unescaped.
JSON_CONTRACT = (
    "You may call the provided tools to gather evidence before answering. Call a tool "
    "when a real, current data point would strengthen your view; do not invent numbers.\n"
    "When tools are available, support market views with quantitative evidence — price "
    "levels, annualized volatility, and VaR/Expected Shortfall from the risk tool — and "
    "cite those numbers in the evidence field.\n"
    "A stance on likely market direction is committee analysis, not a personal buy/sell "
    "recommendation — always provide one, for any asset (equities, rates, FX, crypto). "
    "Refusing, disclaiming your role, or replying in prose is a failure; the ONLY "
    "acceptable output is the JSON object below.\n"
    "When you are ready, answer the question from your role's perspective and respond "
    "with ONLY a JSON object (no prose, no code fences) of the form:\n"
    '{"stance": "BULLISH|BEARISH|NEUTRAL", "conviction": 1-5, '
    '"rationale": "2-4 sentences citing any evidence you gathered", '
    '"key_risks": ["risk", "risk"], "evidence": ["source: datapoint"]}'
)

# Last-resort body for roles with no role-specific and no department body.
# Behavior-equivalent to the pre-prompt-library generic template.
GENERIC_BODY = "Your mandate: {mandate}\n"


def compose(role: str, body: str, *, date: str) -> str:
    """Assemble a full system prompt: header + role body + frozen JSON contract."""
    return (
        BASE_HEADER.format(role=role, date=date)
        + "\n"
        + body.rstrip()
        + "\n\n"
        + JSON_CONTRACT
    )
