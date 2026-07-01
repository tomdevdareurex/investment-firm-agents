"""Orchestrator (M1.5): briefing → plan → agentic analysts → synthesized memo.

The flow upgrades the M1 fixed pipeline into a planned, data-backed run:

1. **Briefing** — the ``research_librarian`` agent uses the data tools to assemble a
   provenance-tagged briefing packet (stored in shared :class:`RunMemory`).
2. **Plan** — a planner picks which analysts are relevant and their order.
3. **Analysts** — each selected analyst runs as a tool-using :class:`Agent`, seeing the
   shared context (briefing + colleagues' findings) and recording its finding back.
4. **Synthesis** — the CIO folds the views into a single recommendation + SOURCES.

Pass ``simple=True`` for the M1-style fixed sequence with no tools/planner (cheap dry
runs). Everything is bounded by the profile's ``run_token_budget`` via :class:`RunTracker`.
"""
from __future__ import annotations

import json
import time
from typing import List, Optional, Tuple

from .. import DISCLAIMER
from ..llm import client, config
from ..llm.costs import RunTracker
from ..llm.utils import extract_text, extract_usage
from .agent import Agent, _extract_json_block
from .memory import RunMemory
from .planner import plan_roles
from .roster import RoleSpec, profile_setting, resolve_profile, resolve_roles
from .schemas import AnalystView, Memo
from .tools import ToolRegistry, default_data_tools

# Candidate analysts the planner may choose from (all defined in firm.yaml).
CANDIDATE_ANALYSTS = [
    "equity_analyst",
    "credit_analyst",
    "rates_analyst",
    "economist_short",
    "economist_medium",
    "economist_long",
    "strategist",
    "market_risk",
]
LIBRARIAN_ROLE = "research_librarian"
PLANNER_ROLE = "cio"
SYNTH_ROLE = "cio"

_SYNTH_SYSTEM = (
    "You are the CIO of a buy-side investment firm. Decision-support only — never advise "
    "executing orders. You are given a question, a sourced briefing packet, and your "
    "analysts' structured views. Issue a single ruling that weighs the evidence and the "
    "balance of views. Respond with ONLY a JSON object (no prose, no code fences):\n"
    '{"recommendation": "BUY|SELL|HOLD|AVOID", "summary": "3-5 sentences"}'
)

_LIBRARIAN_TASK = (
    "Build a concise briefing packet for the question below. Use the data tools to fetch "
    "real, current datapoints relevant to it (prices, rates, macro indicators, filings as "
    "appropriate). Tag every datapoint with its source. Do not invent numbers; if a tool "
    "fails, note the gap. Summarise the findings in a few bullet points."
)


def _pace() -> None:
    """Pause between LLM calls to respect tokens-per-minute limits (IFA_CALL_PAUSE)."""
    pause = config.call_pause()
    if pause > 0:
        time.sleep(pause)


def _resolve(role: str, profile_name: str) -> RoleSpec:
    return resolve_roles([role], profile=profile_name)[role]


def _build_briefing(
    question: str, profile_name: str, tracker: RunTracker
) -> Tuple[str, List[str]]:
    """Run the librarian agent with data tools; return ``(briefing_text, sources)``."""
    spec = _resolve(LIBRARIAN_ROLE, profile_name)
    max_uses = int(profile_setting("web_search_max_uses", 3, profile=profile_name) or 3)
    registry = ToolRegistry(default_data_tools())
    librarian = Agent(spec, tools=registry, max_steps=max(2, max_uses + 1))
    view = librarian.run(f"{_LIBRARIAN_TASK}\n\nQuestion: {question}", tracker=tracker)
    # The librarian's notes capture which tools ran and with what result.
    sources = [n for n in librarian.memory.notes]
    return view.rationale, sources


def _synthesize(
    question: str,
    briefing: str,
    views: List[AnalystView],
    synth_spec: RoleSpec,
    tracker: RunTracker,
) -> Tuple[str, str]:
    body = "\n\n".join(v.render() for v in views)
    user = (
        f"Question: {question}\n\n"
        f"Briefing packet:\n{briefing or '(none)'}\n\nAnalyst views:\n{body}"
    )
    messages = [
        {"role": "system", "content": _SYNTH_SYSTEM},
        {"role": "user", "content": user},
    ]
    start = time.perf_counter()
    resp = client.chat(synth_spec.model, messages, max_tokens=700)
    elapsed = time.perf_counter() - start
    inp, out, _ = extract_usage(resp)
    tracker.record(f"{synth_spec.name} (synthesis)", synth_spec.model, inp, out, elapsed)

    text = extract_text(resp, strict=False)
    block = _extract_json_block(text)
    if block is not None:
        try:
            data = json.loads(block)
            rec = str(data.get("recommendation", "HOLD")).upper()
            summary = str(data.get("summary", "")).strip()
            if rec not in {"BUY", "SELL", "HOLD", "AVOID"}:
                rec = "HOLD"
            return rec, summary or text.strip()[:600]
        except (ValueError, TypeError):
            pass
    return "HOLD", text.strip()[:600] or "(no parseable synthesis)"


def run_committee(
    question: str,
    *,
    profile: Optional[str] = None,
    simple: bool = False,
    tracker: Optional[RunTracker] = None,
) -> Tuple[Memo, RunTracker]:
    """Run the committee and return ``(Memo, RunTracker)``.

    Args:
        question: The decision question.
        profile: Profile override (default: ``IFA_PROFILE`` / firm default).
        simple: If ``True``, run the M1-style fixed analyst sequence with no tools or
            planner (cheaper dry run). Default ``False`` (full agentic flow).
        tracker: Existing tracker to record into (default: a fresh one bounded by the
            profile's ``run_token_budget``).
    """
    profile_name = resolve_profile(profile)
    if tracker is None:
        budget = int(profile_setting("run_token_budget", 0, profile=profile_name) or 0)
        tracker = RunTracker(token_budget=budget)

    memory = RunMemory()
    sources: List[str] = []

    if not simple:
        briefing, sources = _build_briefing(question, profile_name, tracker)
        memory.set_briefing(briefing)
        _pace()

    # --- choose analysts -------------------------------------------------
    candidate_specs = list(resolve_roles(CANDIDATE_ANALYSTS, profile=profile_name).values())
    if simple:
        chosen = ["equity_analyst", "credit_analyst", "rates_analyst"]
    else:
        planner_spec = _resolve(PLANNER_ROLE, profile_name)
        chosen = plan_roles(question, candidate_specs, planner_spec, tracker=tracker)
        _pace()

    specs = resolve_roles(chosen, profile=profile_name)

    # --- run analysts ----------------------------------------------------
    tools = None if simple else ToolRegistry(default_data_tools())
    views: List[AnalystView] = []
    for name in chosen:
        agent = Agent(specs[name], tools=tools, max_steps=1 if simple else 3)
        view = agent.run(question, context=memory.context_for(name), tracker=tracker)
        views.append(view)
        memory.record_finding(name, f"{view.stance} ({view.conviction}/5) {view.rationale}")
        _pace()

    # --- synthesize ------------------------------------------------------
    synth_spec = _resolve(SYNTH_ROLE, profile_name)
    recommendation, summary = _synthesize(
        question, memory.briefing, views, synth_spec, tracker
    )

    memo = Memo(
        question=question,
        profile=profile_name,
        recommendation=recommendation,
        summary=summary,
        views=views,
        briefing=memory.briefing,
        sources=sources,
        disclaimer=DISCLAIMER,
    )
    return memo, tracker
