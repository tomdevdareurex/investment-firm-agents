"""CIO cross-check (M2): an independent second opinion on the final ruling.

After the CIO has synthesized the memo, a *different model family* re-reads the
question, the analyst views and the ruling and answers one narrow question: does
it agree, and if not, what are its top concerns? The cross-check is **advisory**
only — it never changes the recommendation, confidence or summary. It is gated by
the profile flag ``cio_cross_check`` (``firm.yaml``; ``true`` only for ``premium``
by default) and by the run token budget.

The result is a plain dict so it serialises straight into :class:`~core.schemas.Memo`
and the web/report payloads::

    {"status": "ok", "model": "...", "agrees": True, "concerns": [...], "note": "..."}
    {"status": "skipped", "reason": "cio_cross_check disabled for profile 'balanced'"}
    {"status": "error", "model": "...", "reason": "API error: ..."}

Decision-support only: this module reads views and emits text; it never acts.
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from ..llm import client
from ..llm.costs import RunTracker
from ..llm.models import family
from ..llm.utils import (
    extract_text,
    extract_usage,
    get_error_message,
    is_completion_error,
)
from . import events
from .agent import _clean_str_list, _extract_json_block, _strip_fences
from .roster import load_firm, profile_setting, resolve_profile
from .schemas import AnalystView

_log = logging.getLogger(__name__)

TRACKER_LABEL = "cio_cross_check"
MAX_TOKENS = 600
# Rough reservation checked against the run budget before the call is made.
TOKEN_ESTIMATE = 3000
_MAX_CONCERNS = 3
_MAX_VIEW_CHARS = 6000

_SYSTEM_TMPL = (
    "Today is {date}. You are an independent reviewer on an investment committee. "
    "A colleague (the CIO) has issued a final ruling. Your job is NOT to write a new "
    "memo and NOT to change the ruling, but to say whether you agree with it given "
    "the analyst views, and to name at most {n} concrete concerns if you do not "
    "(or if you agree only partly).\n"
    "Be concise, plain-language and decision-support only (never give trade orders).\n"
    "Reply with ONLY a JSON object with exactly these keys:\n"
    '{{"agrees": true|false, "concerns": ["<=3 short strings"], '
    '"note": "<=2 sentences"}}'
)


def _logical_family(model: str) -> str:
    """Family of a model name, tolerant of the ``databricks-`` endpoint prefix."""
    name = (model or "").strip()
    if name.startswith("databricks-"):
        name = name[len("databricks-") :]
    return family(name)


def pick_reviewer_model(
    synth_model: str,
    *,
    profile: Optional[str] = None,
    firm: Optional[dict] = None,
) -> Optional[str]:
    """Return the first AUTHORITY (then SENIOR) model whose family differs.

    Falls back to any model that is not ``synth_model`` itself when every seat
    shares the synth model's family; ``None`` when nothing else is configured.
    """
    firm = firm or load_firm()
    profile_name = resolve_profile(profile, firm)
    profile_cfg = firm["profiles"][profile_name]
    synth_fam = _logical_family(synth_model)
    candidates: List[str] = []
    for tier in ("AUTHORITY", "SENIOR", "HEAD", "WORKER"):
        for model in profile_cfg.get(tier) or []:
            if model not in candidates:
                candidates.append(model)
    for model in candidates:
        if _logical_family(model) != synth_fam:
            return model
    for model in candidates:
        if model != synth_model:
            return model
    return None


def _render_views(views: List[AnalystView]) -> str:
    body = "\n\n".join(v.render() for v in views)
    if len(body) > _MAX_VIEW_CHARS:
        body = body[:_MAX_VIEW_CHARS] + "\n... (views truncated)"
    return body or "(no analyst views)"


def _parse(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_fences(text or "")
    block = _extract_json_block(cleaned) or cleaned
    try:
        data = json.loads(block)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or "agrees" not in data:
        return None
    agrees_raw = data.get("agrees")
    if isinstance(agrees_raw, str):
        agrees = agrees_raw.strip().lower() in {"true", "yes", "agree", "agrees"}
    else:
        agrees = bool(agrees_raw)
    concerns = _clean_str_list(data.get("concerns") or [])[:_MAX_CONCERNS]
    note = str(data.get("note") or "").strip()
    return {"agrees": agrees, "concerns": concerns, "note": note}


def cross_check_synthesis(
    question: str,
    synthesis: Any,
    views: List[AnalystView],
    *,
    model: Optional[str],
    tracker: RunTracker,
    profile: Optional[str] = None,
    on_event: Optional[Callable[[events.StepEvent], None]] = None,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Ask a different model family whether it agrees with the CIO ruling.

    Args:
        question: The (horizon-framed) question the committee answered.
        synthesis: The CIO :class:`~core.orchestrator.Synthesis` (duck-typed: needs
            ``recommendation``, ``summary``, ``confidence``; ``key_reasons`` /
            ``main_risks`` / ``headline`` optional).
        views: Analyst views the CIO ruled on.
        model: Reviewer model (see :func:`pick_reviewer_model`); ``None`` → skipped.
        tracker: Run cost tracker (one record under :data:`TRACKER_LABEL`).
        profile: Profile used to read ``cio_cross_check`` when ``enabled`` is None.
        on_event: Optional event sink; receives one ``CROSS_CHECK_DONE`` event.
        enabled: Override for the profile flag (tests / callers that already know).

    Returns:
        A JSON-safe dict with ``status`` ``ok`` | ``skipped`` | ``error``.
    """
    if enabled is None:
        enabled = bool(profile_setting("cio_cross_check", False, profile=profile))
    result: Dict[str, Any]
    if not enabled:
        label = profile or "active profile"
        result = {
            "status": "skipped",
            "reason": f"cio_cross_check disabled for profile {label!r}",
        }
        return _emit(on_event, result)
    if not model:
        result = {"status": "skipped", "reason": "no reviewer model available"}
        return _emit(on_event, result)
    recommendation = str(getattr(synthesis, "recommendation", "") or "")
    if recommendation == "ERROR" or not recommendation:
        result = {
            "status": "skipped",
            "model": model,
            "reason": "synthesis failed; nothing to cross-check",
        }
        return _emit(on_event, result)
    if tracker.would_exceed(TOKEN_ESTIMATE):
        result = {
            "status": "skipped",
            "model": model,
            "reason": "token budget exhausted before the cross-check",
        }
        return _emit(on_event, result)

    ruling_lines = [
        f"Recommendation: {recommendation}",
        f"Confidence: {getattr(synthesis, 'confidence', 0)}/5",
    ]
    headline = str(getattr(synthesis, "headline", "") or "").strip()
    if headline:
        ruling_lines.append(f"Headline: {headline}")
    ruling_lines.append(f"Summary: {str(getattr(synthesis, 'summary', '')).strip()}")
    for title, attr in (("Key reasons", "key_reasons"), ("Main risks", "main_risks")):
        items = _clean_str_list(getattr(synthesis, attr, None) or [])
        if items:
            ruling_lines.append(f"{title}: " + "; ".join(items))
    user = (
        f"Question: {question}\n\n"
        f"Analyst views:\n{_render_views(views)}\n\n"
        f"CIO ruling:\n" + "\n".join(ruling_lines)
    )
    system = _SYSTEM_TMPL.format(date=datetime.date.today().isoformat(), n=_MAX_CONCERNS)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    start = time.perf_counter()
    resp = client.chat(model, messages, max_tokens=MAX_TOKENS, json_mode=True)
    elapsed = time.perf_counter() - start
    inp, out, _ = extract_usage(resp)
    tracker.record(TRACKER_LABEL, model, inp, out, elapsed)

    if is_completion_error(resp):
        detail = (get_error_message(resp) or "unknown error")[:200]
        result = {"status": "error", "model": model, "reason": f"API error: {detail}"}
        return _emit(on_event, result)

    text = extract_text(resp, strict=False)
    parsed = _parse(text)
    if parsed is None:
        result = {
            "status": "error",
            "model": model,
            "reason": "unparseable JSON" if (text or "").strip() else "empty response",
            "raw": (text or "").strip()[:400],
        }
        return _emit(on_event, result)

    result = {"status": "ok", "model": model, **parsed}
    return _emit(on_event, result)


def _emit(
    on_event: Optional[Callable[[events.StepEvent], None]], result: Dict[str, Any]
) -> Dict[str, Any]:
    if result.get("status") == "ok":
        detail = "agrees" if result.get("agrees") else "disagrees"
    else:
        detail = f"{result.get('status')}: {result.get('reason', '')}"
    events.safe_emit(
        on_event,
        events.CROSS_CHECK_DONE,
        agent="cross_check",
        model=str(result.get("model", "")),
        detail=detail,
        data=dict(result),
    )
    return result


def render_cross_check(result: Dict[str, Any]) -> str:
    """Plain-text rendering for the CLI memo (empty string when nothing to show)."""
    if not isinstance(result, dict) or not result:
        return ""
    status = result.get("status")
    model = result.get("model") or ""
    if status == "ok":
        verdict = "agrees" if result.get("agrees") else "DISAGREES"
        lines = [f"Second opinion ({model}): {verdict} with the ruling — advisory"]
        note = str(result.get("note") or "").strip()
        if note:
            lines.append(f"  {note}")
        for concern in result.get("concerns") or []:
            lines.append(f"  - concern: {concern}")
        return "\n".join(lines)
    if status == "error":
        return f"Second opinion ({model}): unavailable — {result.get('reason', '')}"
    return ""
