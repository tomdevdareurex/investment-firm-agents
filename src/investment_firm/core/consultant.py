"""Read-only quant-consultant chat agent (fable-5 Objective 5).

A senior-quant-consultant the operator can talk to *about a completed run*: the
analysts' reasoning, what a specific indicator means, or a read-only backtest.
It reads a per-run context (the memo + step events) and may call only a small,
read-only subset of the data tools. It has no write capability by construction
and must refuse anything resembling an order or a repo/state mutation.

Hard boundaries (enforced structurally + in the system prompt):
- read-only tool subset (:data:`CONSULTANT_TOOL_NAMES`) — no write tools exist
  in its registry, so it cannot mutate files, config, or state;
- decision-support only — never place, size, or recommend a trade;
- answers are prose, grounded in the run context, never a fresh committee memo.

Streaming: the final answer streams token-by-token via ``client.stream_chat``
when the backend/model supports it (``client.supports_streaming_for``); otherwise
it falls back to a single blocking ``client.chat`` call. Provider/format logic
stays in ``llm/`` — this module never branches on model family.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from ..llm import client
from ..llm.costs import RunTracker
from ..llm.utils import (
    assistant_message,
    extract_text,
    extract_tool_calls,
    extract_usage,
    get_error_message,
    is_completion_error,
)
from . import events
from .schemas import Memo
from .tools import ToolRegistry, default_data_tools

# Default high-reasoning model; override with IFA_CONSULTANT_MODEL.
DEFAULT_CONSULTANT_MODEL = "claude-4.8-opus"

# The only tools the consultant may use — all read-only historical compute.
CONSULTANT_TOOL_NAMES = frozenset(
    {"get_prices", "get_indicators", "compute_risk_metrics", "run_backtest"}
)

_MAX_STEPS = 4
_MAX_TOKENS = 1200
_CONTEXT_MAX_CHARS = 12000

_SYSTEM = (
    "You are a senior quantitative research consultant at a buy-side firm. You are "
    "discussing ONE already-completed committee run with the analyst. Decision-support "
    "only.\n\n"
    "HARD RULES (never break):\n"
    "- You are strictly READ-ONLY. You cannot modify any file, config, or state, and "
    "you have no tools that could. If asked to change, save, write, delete, or execute "
    "anything, refuse and explain you are analysis-only.\n"
    "- Never place, size, or recommend a trade, and never give a buy/sell/hold "
    "instruction. You explain analysis; you do not direct capital.\n"
    "- Ground every answer in the provided run context (the memo, the analysts' "
    "reasoning, the debate, the step events) and your read-only tools. If the context "
    "does not contain something, say so rather than inventing it.\n"
    "- A 'backtest' here is a read-only historical computation only.\n\n"
    "You may call these read-only tools when useful: get_prices, get_indicators, "
    "compute_risk_metrics, run_backtest. Answer in clear prose (not JSON)."
)


def consultant_registry() -> ToolRegistry:
    """Build the consultant's read-only tool registry by filtering the catalog."""
    tools = [t for t in default_data_tools() if t.name in CONSULTANT_TOOL_NAMES]
    return ToolRegistry(tools)


def default_model() -> str:
    """Resolve the consultant model (env override wins)."""
    return (
        os.environ.get("IFA_CONSULTANT_MODEL", "").strip() or DEFAULT_CONSULTANT_MODEL
    )


class RunContext:
    """Read-only, session-scoped view of a completed run for the consultant."""

    def __init__(self, memo: Memo, events_log: Optional[List[dict]] = None):
        self.memo = memo
        self.events = events_log or []

    def render(self, max_chars: int = _CONTEXT_MAX_CHARS) -> str:
        """Render the memo plus a compact tool-call digest from the step events."""
        parts = [self.memo.render()]
        digest = self._tool_digest()
        if digest:
            parts.append("Tool activity during the run:\n" + digest)
        text = "\n\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(context truncated)"
        return text

    def _tool_digest(self) -> str:
        lines = []
        for ev in self.events:
            if ev.get("kind") in (
                events.TOOL_CALLED,
                events.TOOL_RESULT,
                events.TOOL_ERROR,
            ):
                agent = ev.get("agent", "")
                detail = ev.get("detail", "")
                lines.append(f"- {ev.get('kind')}: {agent} {detail}".rstrip())
        return "\n".join(lines[:60])


class Consultant:
    """A read-only quant consultant scoped to a single completed run."""

    def __init__(
        self,
        context: RunContext,
        *,
        model: Optional[str] = None,
        tools: Optional[ToolRegistry] = None,
    ):
        self.context = context
        self.model = model or default_model()
        self.tools = tools or consultant_registry()

    def _messages(self, question: str, history: Optional[List[dict]]) -> List[dict]:
        system = f"{_SYSTEM}\n\n--- RUN CONTEXT ---\n{self.context.render()}"
        messages: List[dict] = [{"role": "system", "content": system}]
        for turn in history or []:
            role = turn.get("role")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})
        return messages

    def ask(
        self,
        question: str,
        *,
        history: Optional[List[dict]] = None,
        tracker: Optional[RunTracker] = None,
        on_event: Optional[events.EventSink] = None,
        stream: bool = False,
    ) -> str:
        """Answer ``question`` from the run context, optionally streaming tokens."""
        messages = self._messages(question, history)
        tool_schemas = self.tools.schemas() if len(self.tools) else None

        # Bounded tool loop: gather any read-only evidence the model asks for.
        for _ in range(_MAX_STEPS):
            if tracker is not None and tracker.would_exceed(_MAX_TOKENS):
                break
            resp = client.chat(
                self.model,
                messages,
                max_tokens=_MAX_TOKENS,
                tools=tool_schemas,
                tool_choice="auto" if tool_schemas else None,
            )
            if tracker is not None:
                inp, out, _ = extract_usage(resp)
                tracker.record("consultant", self.model, inp, out, 0.0)
            if is_completion_error(resp):
                detail = get_error_message(resp) or "unknown error"
                answer = f"ERROR: consultant call failed — {detail}"
                events.safe_emit(
                    on_event, events.CHAT_DONE, agent="consultant", detail=answer
                )
                return answer

            calls = extract_tool_calls(resp)
            if calls and tool_schemas:
                messages.append(
                    assistant_message(resp) or {"role": "assistant", "content": ""}
                )
                for call in calls:
                    fn = call.get("function", {}) if isinstance(call, dict) else {}
                    name = fn.get("name", "")
                    args = fn.get("arguments", "{}")
                    events.safe_emit(
                        on_event,
                        events.TOOL_CALLED,
                        agent="consultant",
                        detail=name,
                        data={"arguments": str(args)[:200]},
                    )
                    result = self.tools.dispatch(name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", name),
                            "content": result,
                        }
                    )
                continue

            # Model produced a final prose answer.
            answer = extract_text(resp, strict=False).strip()
            return self._finalize(messages, answer, tracker, on_event, stream)

        # max_steps exhausted without a final answer — force a plain answer.
        return self._finalize(messages, "", tracker, on_event, stream)

    def _finalize(
        self,
        messages: List[dict],
        answer: str,
        tracker: Optional[RunTracker],
        on_event: Optional[events.EventSink],
        stream: bool,
    ) -> str:
        """Emit the answer. Never re-generate an answer the loop already billed.

        If the tool loop already produced ``answer``, return it as-is — when
        ``stream`` is set we chunk that existing text into ``chat_token`` events
        for a live feel, spending zero extra tokens. Only when the loop produced
        no answer (max_steps exhausted) do we make one more completion, streaming
        it directly when the backend supports token streaming.
        """
        if answer:
            if stream:
                for piece in _chunk_text(answer):
                    events.safe_emit(
                        on_event, events.CHAT_TOKEN, agent="consultant", detail=piece
                    )
            events.safe_emit(
                on_event, events.CHAT_DONE, agent="consultant", detail=answer
            )
            return answer

        # No answer yet — one final completion (this is the only generation).
        if stream and client.supports_streaming_for(self.model):

            def _on_chunk(piece: str) -> None:
                events.safe_emit(
                    on_event, events.CHAT_TOKEN, agent="consultant", detail=piece
                )

            text = client.stream_chat(
                self.model, messages, max_tokens=_MAX_TOKENS, on_chunk=_on_chunk
            )
            if tracker is not None:
                # Streamed responses carry no usage block; approximate from length
                # (~4 chars/token) so the run budget is not blind to the spend.
                tracker.record("consultant", self.model, 0, len(text) // 4, 0.0)
            events.safe_emit(
                on_event, events.CHAT_DONE, agent="consultant", detail=text
            )
            return text

        # No streaming and no answer yet: one blocking completion.
        resp = client.chat(self.model, messages, max_tokens=_MAX_TOKENS)
        if tracker is not None:
            inp, out, _ = extract_usage(resp)
            tracker.record("consultant", self.model, inp, out, 0.0)
        text = extract_text(resp, strict=False).strip()
        events.safe_emit(on_event, events.CHAT_DONE, agent="consultant", detail=text)
        return text


def _chunk_text(text: str, size: int = 24) -> List[str]:
    """Split text into small pieces for token-like streaming (no LLM spend)."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]
