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
    extract_citations,
    extract_text,
    extract_tool_calls,
    extract_usage,
    is_completion_error,
    get_error_message,
)
from .memory import ScratchMemory
from .roster import RoleSpec
from .schemas import AnalystView, Source
from .tools.base import ToolRegistry

# Max age (days) for a tool result's as_of date before it is flagged stale.
_FRESHNESS_WINDOWS_DAYS = {
    "get_prices": 3,
    "compute_risk_metrics": 3,
    "get_ecb_rate": 45,
    "get_worldbank_indicator": 400,
    "get_company_filing": 400,
    "get_yield_curve": 7,
    "get_options_summary": 3,
    "get_cpi": 90,
}

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
    # Capture only inside the key_risks [...] segment, so risks from other fields
    # (rationale, evidence) never bleed into the list.
    risks_block = re.search(r'"key_risks"\s*:\s*\[(.*?)\]', text, re.S)
    key_risks = re.findall(r'"([^"]+)"', risks_block.group(1)) if risks_block else []
    return {
        "stance": stance.group(1) if stance else "NEUTRAL",
        "conviction": int(conviction.group(1)) if conviction else 3,
        "rationale": rationale.group(1).strip() if rationale else "",
        "key_risks": key_risks,
        "evidence": [],
    }


_STRUCTURAL_FRAGMENT = re.compile(r'^[\s\[\]{}:,"\']*$')


def _clean_str_list(value: object) -> List[str]:
    """Normalise a model-provided list field into a clean ``list[str]``.

    Models sometimes return a stringified JSON array (which naive ``list()``
    iteration would split char-by-char) or nest dicts inside the list.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            value = parsed
        else:
            text = value.strip()
            return [text] if text and not _STRUCTURAL_FRAGMENT.match(text) else []
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and not _STRUCTURAL_FRAGMENT.match(text):
            out.append(text)
    return out


def _staleness_note(name: str, result: dict) -> Optional[str]:
    """Return a 'stale as_of=<date>' note when a tool result is older than allowed."""
    window = _FRESHNESS_WINDOWS_DAYS.get(name)
    as_of = result.get("as_of")
    if window is None or not isinstance(as_of, str):
        return None
    try:
        as_of_date = datetime.date.fromisoformat(as_of[:10])
    except ValueError:
        return None
    if (datetime.date.today() - as_of_date).days > window:
        return f"stale as_of={as_of_date.isoformat()}"
    return None


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
        grounded_calls = 0
        data_gaps: List[str] = []
        citations: List[dict] = []
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
            if is_completion_error(resp):
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
                        tracker.record(
                            self.spec.name, self.spec.model, inp2, out2, elapsed2
                        )
                    if not is_completion_error(resp2):
                        citations.extend(extract_citations(resp2))
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

            citations.extend(extract_citations(resp))

            calls = extract_tool_calls(resp)
            if calls and self.tools is not None:
                # Append the assistant's tool-call turn, then each tool result.
                messages.append(
                    assistant_message(resp) or {"role": "assistant", "content": ""}
                )
                for call in calls:
                    fn = call.get("function", {}) if isinstance(call, dict) else {}
                    name = fn.get("name", "")
                    args = fn.get("arguments", "{}")
                    result = self.tools.dispatch(name, args)
                    note = f"{name}({args}) -> {result[:200]}"
                    try:
                        parsed = json.loads(result)
                    except (ValueError, TypeError):
                        parsed = None
                    is_gap = parsed is None or (
                        isinstance(parsed, dict) and "error" in parsed
                    )
                    if is_gap:
                        err = ""
                        if isinstance(parsed, dict):
                            err = str(parsed.get("error", ""))[:120]
                        data_gaps.append(name)
                        note = f"DATA GAP: {name}: {err or 'unparseable result'}"
                    else:
                        grounded_calls += 1
                        if isinstance(parsed, dict):
                            stale = _staleness_note(name, parsed)
                            if stale:
                                note += f" [{stale}]"
                    self.memory.remember(note)
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
            messages.append(
                {
                    "role": "user",
                    "content": "Stop calling tools. Answer now with ONLY the JSON object.",
                }
            )
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
                tracker.record(
                    self.spec.name, self.spec.model, inp_fin, out_fin, elapsed_fin
                )
            if not is_completion_error(fin_resp):
                citations.extend(extract_citations(fin_resp))
                final_text = extract_text(fin_resp, strict=False)

        view = self._parse(final_text)
        return self._apply_grounding(view, grounded_calls, data_gaps, citations)

    def _apply_grounding(
        self,
        view: AnalystView,
        grounded_calls: int,
        data_gaps: List[str],
        citations: List[dict],
    ) -> AnalystView:
        """Enforce the freshness gate: flag ungrounded views and tool data gaps."""
        seen: set = set()
        sources: List[Source] = []
        for cite in citations:
            url = cite.get("url", "")
            if url and url not in seen:
                seen.add(url)
                sources.append(Source(**cite))
        view.citations = sources
        view.grounded = grounded_calls > 0 or bool(sources)
        extra: List[str] = []
        if not view.grounded:
            extra.append(
                "UNVERIFIED: no live data obtained — figures are training-data estimates"
            )
        for name in data_gaps:
            extra.append(
                f"DATA GAP: {name} failed — dependent figures inferred, not measured"
            )
        for risk in extra[:4]:
            if risk not in view.key_risks:
                view.key_risks.append(risk)
        return view

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
            key_risks=_clean_str_list(data.get("key_risks", [])),
            evidence=_clean_str_list(data.get("evidence", [])),
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
        self.memory.remember(f"unparseable model output: {text[:200]!r}")
        return AnalystView(
            role=self.spec.name,
            model=self.spec.model,
            stance="NEUTRAL",
            conviction=2,
            rationale=_strip_fences(text)[:600] or "(no parseable response)",
            key_risks=["model did not return structured JSON"],
        )
