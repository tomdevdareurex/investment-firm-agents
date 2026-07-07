"""OpenAI message-history sanitizer for strict chat backends (Databricks).

Databricks serving endpoints reject histories where an assistant ``tool_calls``
turn is not immediately followed by matching ``role:"tool"`` results, and reject
any tool exchange at all when the request carries no ``tools``. Both shapes are
produced legitimately by the agent resilience ladder (retry-without-tools and
the finalization call resend histories containing earlier tool exchanges with
no ``tools`` kwarg), so the adapter must repair rather than crash.

Rules applied, in order:

1. Every assistant ``tool_calls`` id must have a matching ``role:"tool"`` result
   in the immediately following block — missing ones are synthesized as an
   explicit error stub (the assistant turn is preserved, never dropped).
2. Orphan ``role:"tool"`` messages with no preceding matching tool_call are
   dropped.
3. When the request has no ``tools``, tool exchanges are flattened to plain
   text: the assistant turn keeps its text plus a ``[called tools: ...]`` note,
   and each tool result becomes a user message. This is semantically lossy by
   design — a text digest beats a 400.

The Playground backend does its own Anthropic conversion and never uses this.
"""

from __future__ import annotations

import json
import logging
from typing import List, Sequence

_log = logging.getLogger(__name__)

_MISSING_RESULT_STUB = json.dumps(
    {"error": "tool result unavailable (history sanitized)"}
)


def _call_ids(message: dict) -> List[str]:
    return [
        str(call.get("id", ""))
        for call in message.get("tool_calls") or []
        if call.get("id")
    ]


def _call_names(message: dict) -> List[str]:
    names = []
    for call in message.get("tool_calls") or []:
        name = (call.get("function") or {}).get("name") or call.get("name")
        if name:
            names.append(str(name))
    return names


def _balance(messages: Sequence[dict]) -> List[dict]:
    """Repair dangling tool_calls and drop orphan tool results."""
    out: List[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")
        if role == "tool":
            # Orphan: no preceding assistant tool_calls claimed this result.
            _log.warning(
                "sanitize: dropping orphan tool result (tool_call_id=%r)",
                msg.get("tool_call_id", ""),
            )
            i += 1
            continue
        out.append(msg)
        i += 1
        ids = _call_ids(msg) if role == "assistant" else []
        if not ids:
            continue
        pending = list(ids)
        while i < len(messages) and messages[i].get("role") == "tool":
            tool_msg = messages[i]
            call_id = str(tool_msg.get("tool_call_id", ""))
            if call_id in pending:
                pending.remove(call_id)
                out.append(tool_msg)
            else:
                # Orphan result for an unknown id — drop it (but observably).
                _log.warning(
                    "sanitize: dropping tool result with unknown id %r", call_id
                )
            i += 1
        for missing in pending:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": missing,
                    "content": _MISSING_RESULT_STUB,
                }
            )
    return out


def _flatten(messages: Sequence[dict]) -> List[dict]:
    """Rewrite tool exchanges as plain text for tool-free requests."""
    out: List[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            text = str(msg.get("content") or "").strip()
            names = ", ".join(_call_names(msg)) or "unknown"
            note = f"[called tools: {names}]"
            flat = dict(msg)
            flat.pop("tool_calls", None)
            flat["content"] = f"{text}\n{note}".strip()
            out.append(flat)
        elif role == "tool":
            call_id = str(msg.get("tool_call_id", ""))
            content = str(msg.get("content") or "")
            out.append(
                {"role": "user", "content": f"Tool result ({call_id}): {content}"}
            )
        else:
            out.append(msg)
    return out


# Request-message keys the strict Databricks endpoint accepts. A response's
# ``model_dump()`` echoes many empty extras (``audio``, ``refusal``,
# ``function_call``, ``annotations``, ``reasoning_content`` ...) that a re-sent
# history must NOT carry, or the endpoint 400s with
# ``"messages.N.audio: Extra inputs are not permitted"``.
_ALLOWED_MESSAGE_KEYS = frozenset(
    {"role", "content", "name", "tool_calls", "tool_call_id"}
)
_ALLOWED_TOOL_CALL_KEYS = frozenset({"id", "type", "function"})
_ALLOWED_FUNCTION_KEYS = frozenset({"name", "arguments"})


def _strip_tool_call(call: dict) -> dict:
    cleaned = {k: v for k, v in call.items() if k in _ALLOWED_TOOL_CALL_KEYS}
    fn = cleaned.get("function")
    if isinstance(fn, dict):
        cleaned["function"] = {
            k: v for k, v in fn.items() if k in _ALLOWED_FUNCTION_KEYS
        }
    return cleaned


def _strip_message(message: dict) -> dict:
    """Whitelist request-message keys, dropping response-echoed extras.

    Drops ``None``-valued extras like ``audio``/``refusal`` (original key order
    preserved). ``content: null`` is kept when the turn carries ``tool_calls``
    (valid OpenAI shape) and coerced to ``""`` otherwise.
    """
    cleaned = {
        k: v
        for k, v in message.items()
        if k in _ALLOWED_MESSAGE_KEYS and not (v is None and k != "content")
    }
    if "role" not in cleaned:
        cleaned["role"] = message.get("role", "user")
    calls = cleaned.get("tool_calls")
    if isinstance(calls, list):
        cleaned["tool_calls"] = [
            _strip_tool_call(c) if isinstance(c, dict) else c for c in calls
        ]
    if cleaned.get("content") is None and not cleaned.get("tool_calls"):
        cleaned["content"] = ""
    return cleaned


def sanitize_openai_messages(
    messages: Sequence[dict], *, tools_present: bool
) -> List[dict]:
    """Return a history safe to send to a strict OpenAI-compatible backend."""
    balanced = _balance(list(messages))
    repaired = balanced if tools_present else _flatten(balanced)
    # Final pass: strip response-echoed extras (audio/refusal/...) from every turn
    # so a re-sent assistant message never trips "Extra inputs are not permitted".
    return [_strip_message(m) for m in repaired]
