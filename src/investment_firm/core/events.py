"""Step-event bus for live run visibility (Phase 5 / fable-5 Objective 2).

A tiny, dependency-free pub/sub layer. The committee pipeline optionally emits
coarse :class:`StepEvent` objects — an analyst started, a tool was called, a
debate turn happened, synthesis finished — so CLI and GUI can watch a run
progress live instead of blocking on the final memo.

Design rules:
- Opt-in. Every pipeline entry point takes ``on_event=None``; when it is ``None``
  nothing is emitted and behaviour is byte-for-byte identical to before.
- Emission is synchronous on the pipeline's own thread. The *consumer* owns any
  thread-safety / buffering (the web layer appends under a lock; the CLI prints).
- A broken consumer must never kill a run: :func:`safe_emit` swallows and logs
  any exception the callback raises.
- Coarse only. This never streams model tokens for committee calls (locked
  decision); token-level streaming is reserved for the consultant surface.

Decision-support only: events describe analysis progress, never orders.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger(__name__)

# --- event kinds -----------------------------------------------------------
RUN_STARTED = "run_started"
BRIEFING_STARTED = "briefing_started"
BRIEFING_DONE = "briefing_done"
PLAN_DONE = "plan_done"
ANALYST_STARTED = "analyst_started"
TOOL_CALLED = "tool_called"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
ANALYST_DONE = "analyst_done"
DEBATE_TURN = "debate_turn"
DEBATE_VERDICT = "debate_verdict"
SYNTHESIS_STARTED = "synthesis_started"
SYNTHESIS_DONE = "synthesis_done"
RUN_DONE = "run_done"
RUN_ERROR = "run_error"
# Consultant surface (Objective 5) — token-level streaming lives here.
CHAT_TOKEN = "chat_token"
CHAT_DONE = "chat_done"

# A consumer callback. Receives one StepEvent; returns nothing.
EventSink = Callable[["StepEvent"], None]


@dataclasses.dataclass
class StepEvent:
    """One coarse progress event in a committee run."""

    kind: str
    agent: str = ""
    model: str = ""
    detail: str = ""
    data: Dict[str, Any] = dataclasses.field(default_factory=dict)
    ts: float = 0.0
    seq: int = 0


def to_dict(event: StepEvent) -> Dict[str, Any]:
    """Serialize a StepEvent to a JSON-safe dict for SSE / logging."""
    return {
        "kind": event.kind,
        "agent": event.agent,
        "model": event.model,
        "detail": event.detail,
        "data": event.data or {},
        "ts": event.ts,
        "seq": event.seq,
    }


def safe_emit(
    on_event: Optional[EventSink],
    kind: str,
    *,
    agent: str = "",
    model: str = "",
    detail: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit one event to ``on_event``; a no-op when ``on_event`` is ``None``.

    Any exception raised by the consumer is logged and swallowed — a broken
    listener never interrupts the run.
    """
    if on_event is None:
        return
    event = StepEvent(
        kind=kind,
        agent=agent,
        model=model,
        detail=detail,
        data=dict(data or {}),
        ts=time.time(),
    )
    try:
        on_event(event)
    except Exception:  # noqa: BLE001 — a broken consumer must not kill the run
        _log.warning("step-event consumer raised on kind=%s", kind, exc_info=True)
