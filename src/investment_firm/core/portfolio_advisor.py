"""Portfolio advisor: one CIO-style LLM call over a computed analytics digest.

Decision-support only — describes options and trade-offs, never instructs a
trade. Uses only the numbers in the digest and the (optional) committee memo.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from typing import Any, Dict, List, Optional

from ..llm import client
from ..llm.costs import RunTracker
from ..llm.utils import (
    extract_text,
    extract_usage,
    get_error_message,
    is_completion_error,
)
from .agent import _clean_str_list, _extract_json_block
from .horizon import resolve_horizon
from .orchestrator import PLAIN_LANGUAGE_RULES
from .schemas import Memo

DEFAULT_ADVISOR_MODEL = "claude-5.5-opus"
ADVISOR_MAX_TOKENS = 1500
_LIST_CAP = 6
_MEMO_CHARS = 6000
IDEA_TYPES = ("rebalance", "diversify", "hedge", "reduce_risk", "watch")

_SYSTEM_TMPL = (
    "You are the CIO of a buy-side firm reviewing a client's portfolio. "
    "Decision-support only: never instruct anyone to buy, sell or execute anything — "
    "describe options, trade-offs and what each would change. Today's date is {date}. "
    + PLAIN_LANGUAGE_RULES
    + "Refer to the investment horizon explicitly. Use ONLY numbers present in the "
    "portfolio analytics digest and the market context; if something is missing, say "
    "so. If a market context (committee memo) is provided, relate your observations "
    "to it; otherwise say the view is based on the portfolio's own history only. "
    "Keep each list to at most 4 items. "
    "Respond with ONLY a JSON object (no prose, no code fences):\n"
    '{{"assessment": "3-5 plain sentences", "strengths": ["..."], '
    '"weaknesses": ["..."], "ideas": [{{"idea": "...", "why": "...", '
    '"type": "rebalance|diversify|hedge|reduce_risk|watch"}}], "caveats": ["..."]}}'
)


def default_model() -> str:
    """Advisor model: ``IFA_ADVISOR_MODEL`` (read at call time) or the default."""
    return os.environ.get("IFA_ADVISOR_MODEL", "").strip() or DEFAULT_ADVISOR_MODEL


def _ideas(value: object) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            idea = str(item.get("idea") or "").strip()
            if not idea:
                continue
            kind = str(item.get("type") or "").strip().lower()
            out.append(
                {
                    "idea": idea,
                    "why": str(item.get("why") or "").strip(),
                    "type": kind if kind in IDEA_TYPES else "watch",
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"idea": item.strip(), "why": "", "type": "watch"})
    return out[:_LIST_CAP]


def _parse(text: str) -> Optional[Dict[str, Any]]:
    block = _extract_json_block(text)
    if block is None:
        return None
    try:
        data = json.loads(block)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not str(data.get("assessment") or "").strip():
        return None
    return {
        "assessment": str(data["assessment"]).strip(),
        "strengths": _clean_str_list(data.get("strengths"))[:_LIST_CAP],
        "weaknesses": _clean_str_list(data.get("weaknesses"))[:_LIST_CAP],
        "ideas": _ideas(data.get("ideas")),
        "caveats": _clean_str_list(data.get("caveats"))[:_LIST_CAP],
    }


def suggest(
    digest: Dict[str, Any],
    *,
    market_context: Optional[Memo] = None,
    horizon: str = "short",
    model: Optional[str] = None,
    tracker: Optional[RunTracker] = None,
) -> Dict[str, Any]:
    """Ask the advisor for an assessment of ``digest``; never fabricates on failure."""
    model = model or default_model()
    hz = resolve_horizon(horizon)
    context = (
        market_context.render()[:_MEMO_CHARS]
        if market_context is not None
        else "(none — no committee run selected)"
    )
    user = (
        f"Investment horizon: {hz.label}\n\n"
        f"Portfolio analytics digest (JSON):\n{json.dumps(digest, default=str)}\n\n"
        f"Market context:\n{context}"
    )
    messages = [
        {
            "role": "system",
            "content": _SYSTEM_TMPL.format(date=datetime.date.today().isoformat()),
        },
        {"role": "user", "content": user},
    ]
    start = time.perf_counter()
    resp = client.chat(model, messages, max_tokens=ADVISOR_MAX_TOKENS, json_mode=True)
    elapsed = time.perf_counter() - start
    if tracker is not None:
        inp, out, _ = extract_usage(resp)
        tracker.record("portfolio_advisor", model, inp, out, elapsed)
    if is_completion_error(resp):
        return {
            "status": "error",
            "model": model,
            "error": f"API error: {get_error_message(resp) or 'unknown error'}",
            "raw": "",
        }
    text = extract_text(resp, strict=False)
    parsed = _parse(text)
    if parsed is None:
        return {
            "status": "error",
            "model": model,
            "error": "no parseable JSON",
            "raw": text.strip()[:400],
        }
    return {"status": "ok", "model": model, **parsed}
