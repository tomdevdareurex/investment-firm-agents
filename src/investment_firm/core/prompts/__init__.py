"""Department-organized system-prompt library for the firm's agents.

Public API: :func:`system_prompt_for` assembles the full system prompt for a
resolved :class:`~investment_firm.core.roster.RoleSpec` (base header + body
via the role → department → generic fallback chain + frozen JSON contract).
Debate prompts are re-exported for ``core/debate.py``.
"""

from __future__ import annotations

import datetime

from ..roster import RoleSpec
from .base import BASE_HEADER, GENERIC_BODY, JSON_CONTRACT, compose
from .debate import BEAR_LABEL, BEAR_SYSTEM, BULL_LABEL, BULL_SYSTEM, JUDGE_SYSTEM
from .registry import DEPARTMENT_BODIES, ROLE_BODIES, body_for

__all__ = [
    "BASE_HEADER",
    "BEAR_LABEL",
    "BEAR_SYSTEM",
    "BULL_LABEL",
    "BULL_SYSTEM",
    "DEPARTMENT_BODIES",
    "GENERIC_BODY",
    "JSON_CONTRACT",
    "JUDGE_SYSTEM",
    "ROLE_BODIES",
    "body_for",
    "compose",
    "system_prompt_for",
]


def system_prompt_for(spec: RoleSpec) -> str:
    """Build the full system prompt for ``spec``, with today's date injected."""
    return compose(
        spec.name,
        body_for(spec),
        date=datetime.date.today().isoformat(),
    )
