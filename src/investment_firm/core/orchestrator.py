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

import dataclasses
import datetime
import json
import logging
import time
from typing import List, Optional, Tuple

from .. import DISCLAIMER
from ..llm import client, config
from ..llm.costs import RunTracker
from ..llm.utils import extract_text, extract_usage
from .agent import Agent, _extract_json_block
from .debate import run_debate
from .memory import RunMemory
from .planner import plan_roles
from .roster import RoleSpec, load_firm, profile_setting, resolve_profile, resolve_roles
from .schemas import AnalystView, Memo, Source

_log = logging.getLogger(__name__)
from .tools import ToolRegistry, default_data_tools, default_openbb_tools

# Candidate analysts the planner may choose from (all defined in firm.yaml).
CANDIDATE_ANALYSTS = [
    "equity_analyst",
    "credit_analyst",
    "rates_analyst",
    "technical_analyst",
    "sentiment_analyst",
    "news_analyst",
    "economist_short",
    "economist_medium",
    "economist_long",
    "strategist",
    "market_risk",
]
LIBRARIAN_ROLE = "research_librarian"
PLANNER_ROLE = "cio"
SYNTH_ROLE = "cio"

_SYNTH_SYSTEM_TMPL = (
    "You are the CIO of a buy-side investment firm. Decision-support only — never advise "
    "executing orders. You are given a question, a sourced briefing packet, and your "
    "analysts' structured views. Issue a single ruling that weighs the evidence and the "
    "balance of views. Today's date is {date}. Your training data may be outdated — "
    "prefer tool results, web search, and the briefing packet; if current data is "
    "unavailable, state the gap explicitly instead of guessing. Label any figure you "
    "could not verify via tools, web search, or the briefing as 'unverified (training "
    "data)'. "
    "Respond with ONLY a JSON object (no prose, no code fences):\n"
    '{{"recommendation": "BUY|SELL|HOLD|AVOID", "summary": "3-5 sentences"}}'
)

_LIBRARIAN_TASK_TMPL = (
    "Build a concise briefing packet for the question below. Use the data tools to fetch "
    "real, current datapoints relevant to it (prices, rates, macro indicators, filings as "
    "appropriate). Tag every datapoint with its source. Do not invent numbers; if a tool "
    "fails, note the gap. Summarise the findings in a few bullet points. "
    "Today's date is {date}. Your training data may be outdated — prefer tool results, "
    "web search, and the briefing packet; if current data is unavailable, state the gap "
    "explicitly instead of guessing. Label any figure you could not verify via tools, "
    "web search, or the briefing as 'unverified (training data)'."
)


def _dedup_sources(sources: List[Source]) -> List[Source]:
    seen: set = set()
    out: List[Source] = []
    for src in sources:
        if src.url not in seen:
            seen.add(src.url)
            out.append(src)
    return out


def _pace() -> None:
    """Pause between LLM calls to respect tokens-per-minute limits (IFA_CALL_PAUSE)."""
    pause = config.call_pause()
    if pause > 0:
        time.sleep(pause)


def _resolve(role: str, profile_name: str) -> RoleSpec:
    return resolve_roles([role], profile=profile_name)[role]


def _web_capable_worker_model(profile_name: str) -> Optional[str]:
    """Return the first web-search-capable model in the profile's WORKER pool, if any."""
    profile_cfg = (load_firm().get("profiles") or {}).get(profile_name) or {}
    for model in profile_cfg.get("WORKER") or []:
        if client.supports_web_search_for(model):
            return model
    return None


def _build_briefing(
    question: str, profile_name: str, tracker: RunTracker
) -> Tuple[str, List[str], List[Source]]:
    """Run the librarian agent; return ``(briefing_text, sources, citations)``."""
    spec = _resolve(LIBRARIAN_ROLE, profile_name)
    if not client.supports_web_search_for(spec.model):
        # The librarian prefers web search; fall back to a capable model, or
        # degrade gracefully to data-tools-only grounding (e.g. Databricks).
        replacement = _web_capable_worker_model(profile_name)
        if replacement:
            _log.warning(
                "librarian resolved to %s (no web search) — overriding to %s",
                spec.model,
                replacement,
            )
            spec = dataclasses.replace(spec, model=replacement)
        else:
            _log.warning(
                "librarian resolved to %s (no web search) and no web-capable "
                "WORKER available — proceeding without web search",
                spec.model,
            )
    max_uses = int(profile_setting("web_search_max_uses", 3, profile=profile_name) or 3)
    enable_ws = client.supports_web_search_for(spec.model) and max_uses > 0
    registry = ToolRegistry(default_data_tools() + default_openbb_tools())
    librarian = Agent(
        spec,
        tools=registry,
        max_steps=max(2, max_uses + 1),
        web_search=enable_ws,
        web_search_max_uses=max_uses,
    )
    date_str = datetime.date.today().isoformat()
    librarian_task = _LIBRARIAN_TASK_TMPL.format(date=date_str)
    view = librarian.run(f"{librarian_task}\n\nQuestion: {question}", tracker=tracker)
    # The librarian's notes capture which tools ran and with what result.
    sources = [n for n in librarian.memory.notes]
    return view.rationale, sources, list(view.citations)


def _synthesize(
    question: str,
    briefing: str,
    views: List[AnalystView],
    synth_spec: RoleSpec,
    tracker: RunTracker,
    debate_summary: str = "",
) -> Tuple[str, str]:
    body = "\n\n".join(v.render() for v in views)
    user = (
        f"Question: {question}\n\n"
        f"Briefing packet:\n{briefing or '(none)'}\n\nAnalyst views:\n{body}"
    )
    if debate_summary:
        user += f"\n\nBull/bear debate verdict:\n{debate_summary}"
    date_str = datetime.date.today().isoformat()
    messages = [
        {"role": "system", "content": _SYNTH_SYSTEM_TMPL.format(date=date_str)},
        {"role": "user", "content": user},
    ]
    start = time.perf_counter()
    resp = client.chat(synth_spec.model, messages, max_tokens=700)
    elapsed = time.perf_counter() - start
    inp, out, _ = extract_usage(resp)
    tracker.record(
        f"{synth_spec.name} (synthesis)", synth_spec.model, inp, out, elapsed
    )

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
    web_sources: List[Source] = []

    if not simple:
        briefing, sources, librarian_citations = _build_briefing(
            question, profile_name, tracker
        )
        web_sources.extend(librarian_citations)
        memory.set_briefing(briefing)
        _pace()

    # --- choose analysts -------------------------------------------------
    candidate_specs = list(
        resolve_roles(CANDIDATE_ANALYSTS, profile=profile_name).values()
    )
    if simple:
        chosen = ["equity_analyst", "credit_analyst", "rates_analyst"]
    else:
        planner_spec = _resolve(PLANNER_ROLE, profile_name)
        chosen = plan_roles(question, candidate_specs, planner_spec, tracker=tracker)
        _pace()

    specs = resolve_roles(chosen, profile=profile_name)

    # --- run analysts ----------------------------------------------------
    tools = (
        None if simple else ToolRegistry(default_data_tools() + default_openbb_tools())
    )
    ws_max_uses = int(
        profile_setting("web_search_max_uses", 3, profile=profile_name) or 3
    )
    views: List[AnalystView] = []
    for name in chosen:
        spec = specs[name]
        enable_ws = (
            not simple
            and client.supports_web_search_for(spec.model)
            and ws_max_uses > 0
        )
        agent = Agent(
            spec,
            tools=tools,
            max_steps=1 if simple else 3,
            web_search=enable_ws,
            web_search_max_uses=ws_max_uses,
        )
        view = agent.run(question, context=memory.context_for(name), tracker=tracker)
        views.append(view)
        web_sources.extend(view.citations)
        memory.record_finding(
            name, f"{view.stance} ({view.conviction}/5) {view.rationale}"
        )
        _pace()

    # --- debate (bull vs bear) ------------------------------------------
    synth_spec = _resolve(SYNTH_ROLE, profile_name)
    debate_turns = []
    debate_summary = ""
    max_debate_rounds = int(
        profile_setting("max_debate_rounds", 0, profile=profile_name) or 0
    )
    if not simple and max_debate_rounds > 0 and views:
        bull_spec = _resolve("bull_researcher", profile_name)
        bear_spec = _resolve("bear_researcher", profile_name)
        result = run_debate(
            question,
            memory.briefing,
            views,
            bull_spec=bull_spec,
            bear_spec=bear_spec,
            judge_spec=synth_spec,
            max_rounds=max_debate_rounds,
            tracker=tracker,
        )
        debate_turns = result.transcript
        debate_summary = result.summary
        if debate_summary:
            memory.record_finding("debate", f"{result.stance}: {debate_summary}")
        _pace()

    # --- synthesize ------------------------------------------------------
    recommendation, summary = _synthesize(
        question, memory.briefing, views, synth_spec, tracker, debate_summary
    )

    memo = Memo(
        question=question,
        profile=profile_name,
        recommendation=recommendation,
        summary=summary,
        views=views,
        briefing=memory.briefing,
        debate=debate_turns,
        debate_summary=debate_summary,
        sources=sources,
        web_sources=_dedup_sources(web_sources),
        disclaimer=DISCLAIMER,
    )
    return memo, tracker
