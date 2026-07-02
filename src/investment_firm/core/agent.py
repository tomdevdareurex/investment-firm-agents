"""Agentic analyst (M1.5): a tool-using, looping, stateful agent.

Unlike the M1 single-shot caller, an :class:`Agent` here runs an **observe → think →
act** loop: the model may call tools (which the agent executes and feeds back) over
several turns before emitting its final structured view. The loop is bounded by
``max_steps`` and the shared :class:`RunTracker` token budget, and the agent keeps a
:class:`ScratchMemory` of what it observed. When no tools are provided (or the model
returns no tool calls), it behaves like a normal single answer.
"""
from __future__ import annotations

import datetime
import json
import re
import time
from typing import List, Optional

from ..llm import client
from ..llm.costs import RunTracker
from ..llm.utils import (
    assistant_message,
    extract_text,
    extract_tool_calls,
    extract_usage,
    is_error,
    get_error_message,
)
from .memory import ScratchMemory
from .roster import RoleSpec
from .schemas import AnalystView
from .tools.base import ToolRegistry

_SYSTEM_TEMPLATE = (
    "You are the {role} at a buy-side investment firm. Your mandate: {mandate}\n"
    "This is decision-support only — never advise executing orders.\n"
    "Today's date is {date}. Your training data may be outdated — prefer tool results, "
    "web search, and the briefing packet; if current data is unavailable, state the gap "
    "explicitly instead of guessing. Label any figure you could not verify via tools, "
    "web search, or the briefing as 'unverified (training data)'.\n\n"
    "You may call the provided tools to gather evidence before answering. Call a tool "
    "when a real, current data point would strengthen your view; do not invent numbers.\n"
    "When tools are available, support market views with quantitative evidence — price "
    "levels, annualized volatility, and VaR/Expected Shortfall from the risk tool — and "
    "cite those numbers in the evidence field.\n"
    "When you are ready, answer the question from your role's perspective and respond "
    "with ONLY a JSON object (no prose, no code fences) of the form:\n"
    '{{"stance": "BULLISH|BEARISH|NEUTRAL", "conviction": 1-5, '
    '"rationale": "2-4 sentences citing any evidence you gathered", '
    '"key_risks": ["risk", "risk"], "evidence": ["source: datapoint"]}}'
)


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` code fences some models add despite instructions."""
    return re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()


def _extract_json_block(text: str) -> Optional[str]:
    """Return the first balanced ``{...}`` substring, or ``None``."""
    text = _strip_fences(text)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _salvage_fields(text: str) -> Optional[dict]:
    """Best-effort field extraction from truncated/unbalanced JSON.

    Models occasionally get cut off mid-object (token cap) so the braces never balance.
    Rather than discard the whole answer, pull the scalar fields we care about by regex.
    """
    text = _strip_fences(text)
    stance = re.search(r'"stance"\s*:\s*"([^"]+)"', text)
    conviction = re.search(r'"conviction"\s*:\s*(\d+)', text)
    rationale = re.search(r'"rationale"\s*:\s*"([^"]*)', text)  # may be truncated
    if not (stance or rationale):
        return None
    return {
        "stance": stance.group(1) if stance else "NEUTRAL",
        "conviction": int(conviction.group(1)) if conviction else 3,
        "rationale": rationale.group(1).strip() if rationale else "",
        "key_risks": re.findall(r'"([^"]+)"', text[text.find("key_risks"):]) if "key_risks" in text else [],
        "evidence": [],
    }


class Agent:
    """A single role-playing analyst that can use tools over a bounded loop."""

    def __init__(
        self,
        spec: RoleSpec,
        *,
        tools: Optional[ToolRegistry] = None,
        max_steps: int = 4,
        max_tokens: int = 1200,
        web_search: bool = False,
        web_search_max_uses: int = 3,
    ):
        self.spec = spec
        self.tools = tools
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.web_search = web_search
        self.web_search_max_uses = web_search_max_uses
        self.memory = ScratchMemory()

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_TEMPLATE.format(
            role=self.spec.name,
            mandate=self.spec.mandate,
            date=datetime.date.today().isoformat(),
        )

    def run(
        self,
        question: str,
        *,
        context: str = "",
        tracker: Optional[RunTracker] = None,
    ) -> AnalystView:
        """Run the agent loop and return a parsed :class:`AnalystView`."""
        user = question if not context else f"{context}\n\nQuestion: {question}"
        messages: List[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user},
        ]
        tool_schemas = self.tools.schemas() if self.tools and len(self.tools) else None

        final_text = ""
        for _ in range(self.max_steps):
            # Budget guard: stop spending if the run budget would be exceeded.
            if tracker is not None and tracker.would_exceed(self.max_tokens):
                self.memory.remember("stopped early: run token budget reached")
                break

            start = time.perf_counter()
            resp = client.chat(
                self.spec.model,
                messages,
                max_tokens=self.max_tokens,
                tools=tool_schemas,
                tool_choice="auto" if tool_schemas else None,
                web_search=self.web_search,
                max_uses=self.web_search_max_uses,
                json_mode=True,
            )
            elapsed = time.perf_counter() - start
            if tracker is not None:
                inp, out, _ = extract_usage(resp)
                tracker.record(self.spec.name, self.spec.model, inp, out, elapsed)

            # Resilience: handle error responses
            if is_error(resp):
                err_msg = get_error_message(resp) or "unknown error"
                self.memory.remember(f"API error: {err_msg}")
                if tool_schemas:
                    # Retry once without tools (degraded call)
                    start2 = time.perf_counter()
                    resp2 = client.chat(
                        self.spec.model,
                        messages,
                        max_tokens=self.max_tokens,
                        web_search=self.web_search,
                        max_uses=self.web_search_max_uses,
                        json_mode=True,
                    )
                    elapsed2 = time.perf_counter() - start2
                    if tracker is not None:
                        inp2, out2, _ = extract_usage(resp2)
                        tracker.record(self.spec.name, self.spec.model, inp2, out2, elapsed2)
                    if not is_error(resp2):
                        final_text = extract_text(resp2, strict=False)
                        break
                    err_msg = get_error_message(resp2) or err_msg
                # Both error (or no tools) — return fallback view
                return AnalystView(
                    role=self.spec.name,
                    model=self.spec.model,
                    stance="NEUTRAL",
                    conviction=2,
                    rationale="(no parseable response)",
                    key_risks=[f"API error: {err_msg}"],
                )

            calls = extract_tool_calls(resp)
            if calls and self.tools is not None:
                # Append the assistant's tool-call turn, then each tool result.
                messages.append(assistant_message(resp) or {"role": "assistant", "content": ""})
                for call in calls:
                    fn = call.get("function", {}) if isinstance(call, dict) else {}
                    name = fn.get("name", "")
                    args = fn.get("arguments", "{}")
                    result = self.tools.dispatch(name, args)
                    self.memory.remember(f"{name}({args}) -> {result[:200]}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", name),
                            "content": result,
                        }
                    )
                continue  # observe results, loop again

            final_text = extract_text(resp, strict=False)
            break

        # Finalization: if max_steps exhausted with model still tool-calling (empty text)
        if not final_text and tool_schemas:
            messages.append({
                "role": "user",
                "content": "Stop calling tools. Answer now with ONLY the JSON object.",
            })
            start_fin = time.perf_counter()
            fin_resp = client.chat(
                self.spec.model,
                messages,
                max_tokens=self.max_tokens,
                web_search=self.web_search,
                max_uses=self.web_search_max_uses,
                json_mode=True,
            )
            elapsed_fin = time.perf_counter() - start_fin
            if tracker is not None:
                inp_fin, out_fin, _ = extract_usage(fin_resp)
                tracker.record(self.spec.name, self.spec.model, inp_fin, out_fin, elapsed_fin)
            if not is_error(fin_resp):
                final_text = extract_text(fin_resp, strict=False)

        return self._parse(final_text)

    def _to_view(self, data: dict) -> AnalystView:
        stance = str(data.get("stance", "NEUTRAL")).upper()
        if stance not in {"BULLISH", "BEARISH", "NEUTRAL"}:
            stance = "NEUTRAL"
        try:
            conviction = int(data.get("conviction", 3))
        except (ValueError, TypeError):
            conviction = 3
        conviction = min(5, max(1, conviction))
        return AnalystView(
            role=self.spec.name,
            model=self.spec.model,
            stance=stance,
            conviction=conviction,
            rationale=str(data.get("rationale", "")).strip(),
            key_risks=[str(r) for r in data.get("key_risks", []) or []],
            evidence=[str(e) for e in data.get("evidence", []) or []],
        )

    def _parse(self, text: str) -> AnalystView:
        # 1) Clean, balanced JSON.
        block = _extract_json_block(text)
        if block is not None:
            try:
                return self._to_view(json.loads(block))
            except (ValueError, TypeError):
                pass
        # 2) Truncated/unbalanced JSON — salvage the fields we can.
        salvaged = _salvage_fields(text)
        if salvaged is not None:
            return self._to_view(salvaged)
        # 3) Total fallback: keep the run alive with the raw text as rationale.
        return AnalystView(
            role=self.spec.name,
            model=self.spec.model,
            stance="NEUTRAL",
            conviction=2,
            rationale=_strip_fences(text)[:600] or "(no parseable response)",
            key_risks=["model did not return structured JSON"],
        )
