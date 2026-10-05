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
import re
import time
from typing import List, Optional, Tuple

from .. import DISCLAIMER
from ..llm import client, config
from ..llm.costs import RunTracker
from ..llm.utils import (
    extract_text,
    extract_usage,
    get_error_message,
    is_completion_error,
)
from . import errors, events
from .agent import Agent, _clean_str_list, _extract_json_block, _strip_fences
from .debate import debate_token_estimate, run_debate
from .horizon import frame_question, resolve_horizon
from .memory import RunMemory
from .planner import plan_roles
from .roster import RoleSpec, load_firm, profile_setting, resolve_profile, resolve_roles
from .schemas import AnalystView, Memo, Source

_log = logging.getLogger(__name__)
from .tools import ToolRegistry, default_data_tools, default_openbb_tools

# Core candidate analysts the planner may choose from (all defined in firm.yaml).
CANDIDATE_ANALYSTS = [
    "equity_analyst",
    "credit_analyst",
    "rates_analyst",
    "technical_analyst",
    "sentiment_analyst",
    "news_analyst",
    "economist_medium",
    "strategist",
    "market_risk",
]
# Optional specialists (optional: true in firm.yaml) — offered to the planner
# annotated as optional, excluded from the parse-failure fallback.
OPTIONAL_ANALYSTS = [
    "economist_short",
    "economist_long",
    "fx_strategist",
    "quant",
    "credit_risk",
    "liquidity_risk",
]
_SYNTH_MAX_TOKENS = 2000  # CIO ruling cap (was 700 — cut the JSON mid-summary)
# Rough sizes for the pre-analyst budget reservation (tokens, ~4 chars each).
_EST_VIEW_TOKENS = 400  # one rendered AnalystView fed to debate/synthesis
_EST_QUESTION_TOKENS = 300  # question + prompt scaffolding
_SYNTH_RETRY_NUDGE = (
    "\n\nYour previous reply was cut off or malformed. Reply again with ONLY the JSON "
    "object and keep the summary to at most 5 sentences."
)
_LIBRARIAN_MAX_TOKENS = 2500  # the briefing packet is longer than an analyst view
_BRIEFING_MAX_CHARS = 6000  # cap on prose briefings used when the librarian skips JSON
LIBRARIAN_ROLE = "research_librarian"
PLANNER_ROLE = "cio"
SYNTH_ROLE = "cio"
_SYNTH_LIST_CAP = 6

PLAIN_LANGUAGE_RULES = (
    "Write for an intelligent reader who is not a finance professional. Avoid trader "
    "jargon (e.g. long/short, bps, carry, duration, risk-on, overweight, spread "
    "widening); if a technical term is unavoidable, explain it in plain words in "
    "parentheses. Say what could go wrong in everyday money terms (e.g. 'a fall of "
    "around 20% would not be unusual'). "
)

_SYNTH_SYSTEM_TMPL = (
    "You are the CIO of a buy-side investment firm. Decision-support only — never advise "
    "executing orders. You are given a question, a sourced briefing packet, and your "
    "analysts' structured views. Issue a single ruling that weighs the evidence and the "
    "balance of views. Today's date is {date}. Your training data may be outdated — "
    "prefer tool results, web search, and the briefing packet; if current data is "
    "unavailable, state the gap explicitly instead of guessing. Label any figure you "
    "could not verify via tools, web search, or the briefing as 'unverified (training "
    "data)'. "
    + PLAIN_LANGUAGE_RULES
    + "Mention the investment horizon given in the question explicitly. Base every "
    "number on the briefing or the analyst views — do not invent figures. Keep each "
    "list to at most 4 items of one short sentence each. "
    "Respond with ONLY a JSON object (no prose, no code fences), keys in this order:\n"
    '{{"recommendation": "BUY|SELL|HOLD|AVOID", "headline": "one plain-English '
    'sentence", "summary": "3-5 plain-English sentences", "confidence": 1-5, '
    '"key_reasons": ["reason", "..."], "main_risks": ["risk in plain words", "..."], '
    '"what_to_watch": ["signal or event to monitor", "..."]}}'
)


@dataclasses.dataclass
class Synthesis:
    recommendation: str
    summary: str
    headline: str = ""
    key_reasons: List[str] = dataclasses.field(default_factory=list)
    main_risks: List[str] = dataclasses.field(default_factory=list)
    what_to_watch: List[str] = dataclasses.field(default_factory=list)
    confidence: int = 0  # 1..5; 0 = unknown / error / salvaged


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
) -> Tuple[str, List[str], List[Source], str]:
    """Run the librarian agent; return ``(briefing_text, sources, citations, model)``."""
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
        max_tokens=_LIBRARIAN_MAX_TOKENS,
        web_search=enable_ws,
        web_search_max_uses=max_uses,
        # The briefing is prose by design; a JSON "repair" would squeeze it into a
        # 2-4 sentence rationale, so keep the raw text instead (see below).
        repair=False,
    )
    date_str = datetime.date.today().isoformat()
    librarian_task = _LIBRARIAN_TASK_TMPL.format(date=date_str)
    view = librarian.run(f"{librarian_task}\n\nQuestion: {question}", tracker=tracker)
    # The librarian's notes capture which tools ran and with what result.
    sources = [n for n in librarian.memory.notes]
    briefing = view.rationale
    if view.stance == "ERROR" and librarian.last_text.strip():
        prose = _strip_fences(librarian.last_text).strip()
        if prose:
            _log.warning(
                "librarian did not return JSON — using its prose as the briefing"
            )
            briefing = prose[:_BRIEFING_MAX_CHARS]
    return briefing, sources, list(view.citations), spec.model


def _synthesize(
    question: str,
    briefing: str,
    views: List[AnalystView],
    synth_spec: RoleSpec,
    tracker: RunTracker,
    debate_summary: str = "",
) -> Synthesis:
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
    input_estimate = sum(len(m["content"]) for m in messages) // 4
    if tracker.would_exceed(_SYNTH_MAX_TOKENS + input_estimate):
        return Synthesis(
            "ERROR",
            errors.error_summary(
                "synthesis", "token budget exhausted before the CIO could rule"
            ),
        )

    def _call(msgs: List[dict], cap: int) -> Optional[dict]:
        start = time.perf_counter()
        resp = client.chat(synth_spec.model, msgs, max_tokens=cap)
        elapsed = time.perf_counter() - start
        inp, out, _ = extract_usage(resp)
        tracker.record(
            f"{synth_spec.name} (synthesis)", synth_spec.model, inp, out, elapsed
        )
        return resp

    resp = _call(messages, _SYNTH_MAX_TOKENS)
    if is_completion_error(resp):
        detail = get_error_message(resp) or "unknown error"
        return Synthesis(
            "ERROR", errors.error_summary("synthesis", f"API error: {detail}")
        )

    text = extract_text(resp, strict=False)
    parsed = _parse_synthesis(text)
    if parsed is not None:
        return parsed

    # Cut off (or otherwise unbalanced/unparseable): retry once with double the cap
    # and a nudge towards a shorter summary, budget permitting.
    retry_cap = _SYNTH_MAX_TOKENS * 2
    retry_messages = messages[:-1] + [
        {"role": "user", "content": messages[-1]["content"] + _SYNTH_RETRY_NUDGE}
    ]
    retry_text = ""
    if not tracker.would_exceed(retry_cap + input_estimate):
        retry_resp = _call(retry_messages, retry_cap)
        if not is_completion_error(retry_resp):
            retry_text = extract_text(retry_resp, strict=False)
            parsed = _parse_synthesis(retry_text)
            if parsed is not None:
                return parsed

    # Last resort: pull recommendation + a partial summary out of cut-off JSON.
    for candidate in (retry_text, text):
        salvaged = _salvage_synthesis(candidate)
        if salvaged is not None:
            return salvaged
    raw = (retry_text or text).strip()
    return Synthesis(
        "ERROR",
        errors.error_summary("synthesis", "no parseable JSON")
        + f" Raw output (truncated): {raw[:400]}",
    )


_VALID_RECOMMENDATIONS = {"BUY", "SELL", "HOLD", "AVOID"}


def _confidence(value: object) -> int:
    try:
        return max(1, min(5, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _parse_synthesis(text: str) -> Optional[Synthesis]:
    """Parse a complete CIO synthesis JSON object, else ``None``."""
    block = _extract_json_block(text)
    if block is None:
        return None
    try:
        data = json.loads(block)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    rec = str(data.get("recommendation", "HOLD")).upper()
    summary = str(data.get("summary", "")).strip()
    if rec not in _VALID_RECOMMENDATIONS:
        rec = "HOLD"
    return Synthesis(
        recommendation=rec,
        summary=summary or text.strip()[:600],
        headline=str(data.get("headline", "") or "").strip(),
        key_reasons=_clean_str_list(data.get("key_reasons"))[:_SYNTH_LIST_CAP],
        main_risks=_clean_str_list(data.get("main_risks"))[:_SYNTH_LIST_CAP],
        what_to_watch=_clean_str_list(data.get("what_to_watch"))[:_SYNTH_LIST_CAP],
        confidence=_confidence(data.get("confidence")),
    )


def _salvage_synthesis(text: str) -> Optional[Synthesis]:
    """Regex-extract the recommendation (required) and a partial summary.

    Only a recommendation that is literally one of BUY/SELL/HOLD/AVOID is accepted —
    nothing is guessed. The summary is marked ``(truncated)`` since it was cut off.
    """
    text = _strip_fences(text)
    rec_match = re.search(
        r'"recommendation"\s*:\s*"\s*(BUY|SELL|HOLD|AVOID)\s*"', text, re.IGNORECASE
    )
    if not rec_match:
        return None
    summary_match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.DOTALL)
    partial = (
        summary_match.group(1).replace('\\"', '"').replace("\\n", " ").strip()
        if summary_match
        else ""
    )
    summary = f"{partial} (truncated)" if partial else "(summary truncated)"
    headline_match = re.search(r'"headline"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    headline = (
        headline_match.group(1).replace('\\"', '"').strip() if headline_match else ""
    )
    return Synthesis(rec_match.group(1).upper(), summary, headline=headline)


def run_committee(
    question: str,
    *,
    profile: Optional[str] = None,
    simple: bool = False,
    tracker: Optional[RunTracker] = None,
    on_event: Optional[events.EventSink] = None,
    horizon: str = "short",
) -> Tuple[Memo, RunTracker]:
    """Run the committee and return ``(Memo, RunTracker)``.

    Args:
        question: The decision question.
        profile: Profile override (default: ``IFA_PROFILE`` / firm default).
        simple: If ``True``, run the M1-style fixed analyst sequence with no tools or
            planner (cheaper dry run). Default ``False`` (full agentic flow).
        tracker: Existing tracker to record into (default: a fresh one bounded by the
            profile's ``run_token_budget``).
        horizon: ``short`` | ``medium`` | ``long``; appended to the question every
            agent sees (``Memo.question`` stays the raw question).
    """
    hz = resolve_horizon(horizon)
    framed = frame_question(question, hz.key)
    profile_name = resolve_profile(profile)
    if tracker is None:
        budget = int(profile_setting("run_token_budget", 0, profile=profile_name) or 0)
        tracker = RunTracker(token_budget=budget)

    memory = RunMemory()
    sources: List[str] = []
    web_sources: List[Source] = []
    briefing_model = ""

    events.safe_emit(
        on_event,
        events.RUN_STARTED,
        detail=question,
        data={"profile": profile_name, "horizon": hz.key},
    )

    if not simple:
        events.safe_emit(on_event, events.BRIEFING_STARTED)
        briefing, sources, librarian_citations, briefing_model = _build_briefing(
            framed, profile_name, tracker
        )
        web_sources.extend(librarian_citations)
        memory.set_briefing(briefing)
        events.safe_emit(on_event, events.BRIEFING_DONE)
        _pace()

    # --- choose analysts -------------------------------------------------
    candidate_specs = list(
        resolve_roles(
            CANDIDATE_ANALYSTS + OPTIONAL_ANALYSTS, profile=profile_name
        ).values()
    )
    if simple:
        chosen = ["equity_analyst", "credit_analyst", "rates_analyst"]
    else:
        planner_spec = _resolve(PLANNER_ROLE, profile_name)
        chosen = plan_roles(framed, candidate_specs, planner_spec, tracker=tracker)
        _pace()

    specs = resolve_roles(chosen, profile=profile_name)
    events.safe_emit(on_event, events.PLAN_DONE, data={"analysts": list(chosen)})

    # --- run analysts ----------------------------------------------------
    tools = (
        None if simple else ToolRegistry(default_data_tools() + default_openbb_tools())
    )
    ws_max_uses = int(
        profile_setting("web_search_max_uses", 3, profile=profile_name) or 3
    )
    views: List[AnalystView] = []
    synth_spec = _resolve(SYNTH_ROLE, profile_name)
    debate_turns = []
    debate_summary = ""
    debate_ran = False
    max_debate_rounds = int(
        profile_setting("max_debate_rounds", 0, profile=profile_name) or 0
    )
    will_debate = not simple and max_debate_rounds > 0

    # Hold back budget for the stages that run AFTER the analysts (debate + judge +
    # synthesis), so analysts stop early rather than starving them.
    input_est = (
        len(memory.briefing) // 4
        + len(chosen) * _EST_VIEW_TOKENS
        + _EST_QUESTION_TOKENS
    )
    debate_est = (
        debate_token_estimate(max_debate_rounds, input_est) if will_debate else 0
    )
    synth_est = _SYNTH_MAX_TOKENS + input_est
    held = debate_est + synth_est
    tracker.reserve(held)
    try:
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
            view = agent.run(
                framed,
                context=memory.context_for(name),
                tracker=tracker,
                on_event=on_event,
            )
            views.append(view)
            web_sources.extend(view.citations)
            memory.record_finding(
                name, f"{view.stance} ({view.conviction}/5) {view.rationale}"
            )
            _pace()

        # --- debate (bull vs bear) --------------------------------------
        # Analysts are done: free the debate's share (synthesis stays held).
        tracker.release(debate_est)
        held -= debate_est
        if will_debate and views:
            debate_ran = True
            bull_spec = _resolve("bull_researcher", profile_name)
            bear_spec = _resolve("bear_researcher", profile_name)
            result = run_debate(
                framed,
                memory.briefing,
                views,
                bull_spec=bull_spec,
                bear_spec=bear_spec,
                judge_spec=synth_spec,
                max_rounds=max_debate_rounds,
                tracker=tracker,
                on_event=on_event,
            )
            debate_turns = result.transcript
            debate_summary = result.summary
            if debate_summary:
                memory.record_finding("debate", f"{result.stance}: {debate_summary}")
            _pace()
    finally:
        # Synthesis may now spend what is left of its own reservation.
        tracker.release(held)

    # --- synthesize ------------------------------------------------------
    events.safe_emit(
        on_event,
        events.SYNTHESIS_STARTED,
        agent=synth_spec.name,
        model=synth_spec.model,
    )
    synth = _synthesize(
        framed, memory.briefing, views, synth_spec, tracker, debate_summary
    )
    events.safe_emit(
        on_event,
        events.SYNTHESIS_DONE,
        agent=synth_spec.name,
        model=synth_spec.model,
        detail=synth.recommendation,
    )

    memo = Memo(
        question=question,
        profile=profile_name,
        horizon=hz.key,
        recommendation=synth.recommendation,
        summary=synth.summary,
        headline=synth.headline,
        key_reasons=synth.key_reasons,
        main_risks=synth.main_risks,
        what_to_watch=synth.what_to_watch,
        confidence=synth.confidence,
        views=views,
        briefing=memory.briefing,
        briefing_role=LIBRARIAN_ROLE if not simple else "",
        briefing_model=briefing_model,
        debate=debate_turns,
        debate_summary=debate_summary,
        synth_role=synth_spec.name,
        synth_model=synth_spec.model,
        debate_judge_role=synth_spec.name if debate_ran else "",
        debate_judge_model=synth_spec.model if debate_ran else "",
        sources=sources,
        web_sources=_dedup_sources(web_sources),
        disclaimer=DISCLAIMER,
    )
    events.safe_emit(on_event, events.RUN_DONE, detail=synth.recommendation)
    return memo, tracker
