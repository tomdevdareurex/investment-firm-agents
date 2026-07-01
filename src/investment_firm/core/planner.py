"""Planner (M1.5): decide which roles to involve, instead of a hard-coded list.

Given the question and the available analyst roles, a HEAD/AUTHORITY-tier model returns
an ordered subset of roles to run. This gives the run *dynamic control flow* (planning)
rather than the fixed M1 sequence. If the model's plan can't be parsed, we fall back to
all candidate roles so a run never stalls.
"""
from __future__ import annotations

import json
import time
from typing import List, Optional

from ..llm import client
from ..llm.costs import RunTracker
from ..llm.utils import extract_text, extract_usage
from .agent import _extract_json_block
from .roster import RoleSpec

_PLANNER_SYSTEM = (
    "You are the planning lead at a buy-side investment firm (decision-support only). "
    "Given a question and the available analyst roles with their mandates, choose which "
    "roles are RELEVANT and the order to consult them. Prefer a focused subset over "
    "everyone. Respond with ONLY a JSON object (no prose, no code fences):\n"
    '{"plan": ["role_name", "role_name"], "reasoning": "one sentence"}'
)


def plan_roles(
    question: str,
    candidates: List[RoleSpec],
    planner_spec: RoleSpec,
    *,
    tracker: Optional[RunTracker] = None,
) -> List[str]:
    """Return an ordered list of role names to run, chosen by the planner model."""
    catalogue = "\n".join(f"- {c.name}: {c.mandate}" for c in candidates)
    valid = {c.name for c in candidates}
    user = f"Question: {question}\n\nAvailable roles:\n{catalogue}"
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": user},
    ]
    start = time.perf_counter()
    resp = client.chat(planner_spec.model, messages, max_tokens=400)
    elapsed = time.perf_counter() - start
    if tracker is not None:
        inp, out, _ = extract_usage(resp)
        tracker.record(f"{planner_spec.name} (planner)", planner_spec.model, inp, out, elapsed)

    text = extract_text(resp, strict=False)
    block = _extract_json_block(text)
    if block is not None:
        try:
            data = json.loads(block)
            chosen = [r for r in data.get("plan", []) if r in valid]
            if chosen:
                return chosen
        except (ValueError, TypeError):
            pass
    # Fallback: keep every candidate (never stall the run).
    return [c.name for c in candidates]
