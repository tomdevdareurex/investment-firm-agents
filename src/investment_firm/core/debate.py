"""Bull vs bear investment debate (Phase 4).

A small state machine layered on the existing LLM client. The bull and bear
researchers argue over the assembled analyst views + briefing for a bounded
number of rounds, then a judge distils the debate into a stance + summary that
the final CIO synthesis weighs.

No LangGraph: this is a plain alternating loop mirroring TradingAgents'
``investment_debate_state`` (stop at ``count >= 2 * max_rounds``) but built on
IFA's format-agnostic ``client.chat`` so it works across every backend. Each
turn is a single, tool-free completion — the debaters reason over the evidence
the analysts already gathered, they do not fetch new data.

Decision-support only: the debate produces analysis, never an order.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import time
from typing import List, Optional

from ..llm import client, config
from ..llm.costs import RunTracker
from ..llm.utils import (
    extract_text,
    extract_usage,
    get_error_message,
    is_completion_error,
)
from . import errors, events
from .agent import _extract_json_block
from .roster import RoleSpec
from .schemas import AnalystView, DebateTurn

# Rough output cap per debate turn; also used for the budget pre-check.
_TURN_MAX_TOKENS = 500
_JUDGE_MAX_TOKENS = 400

# Canonical speaker titles — used in prompts, transcripts, and every UI surface.
BULL_LABEL = "Senior Research Bull"
BEAR_LABEL = "Senior Research Bear"

_BULL_SYSTEM = (
    "You are the Senior Research Bull at a buy-side investment firm. Decision-support "
    "only — never advise executing orders. Build the strongest evidence-based "
    "BULLISH case for the question using the analyst views and briefing. The "
    "analyst views are labelled by role (e.g. [equity_analyst]) — reference "
    "colleagues by role when you use their evidence or reasoning. Engage "
    "directly with the bear's last argument and rebut it — argue, don't just list "
    "data. Today's date is {date}. Prefer the provided evidence and tool results; "
    "label anything you could not verify as 'unverified (training data)'. Keep it "
    "to 2-4 tight paragraphs."
)

_BEAR_SYSTEM = (
    "You are the Senior Research Bear at a buy-side investment firm. Decision-support "
    "only — never advise executing orders. Build the strongest evidence-based "
    "BEARISH case against the question using the analyst views and briefing. The "
    "analyst views are labelled by role (e.g. [equity_analyst]) — reference "
    "colleagues by role when you use their evidence or reasoning. Engage "
    "directly with the bull's last argument and rebut it — argue, don't just list "
    "data. Today's date is {date}. Prefer the provided evidence and tool results; "
    "label anything you could not verify as 'unverified (training data)'. Keep it "
    "to 2-4 tight paragraphs."
)

_JUDGE_SYSTEM = (
    "You are the Research Manager and debate judge at a buy-side investment firm. "
    "Decision-support only. Read the bull/bear debate and the analyst views, then "
    "deliver a balanced verdict on which side is better supported. Today's date is "
    "{date}. Respond with ONLY a JSON object (no prose, no code fences):\n"
    '{{"stance": "BULLISH|BEARISH|NEUTRAL", "summary": "3-5 sentences on which '
    'side won and why"}}'
)


@dataclasses.dataclass
class DebateResult:
    """Outcome of a bull/bear debate."""

    transcript: List[DebateTurn]
    summary: str
    stance: str


def _pace() -> None:
    pause = config.call_pause()
    if pause > 0:
        time.sleep(pause)


def _views_block(views: List[AnalystView]) -> str:
    return "\n\n".join(v.render() for v in views) if views else "(no analyst views)"


def _estimate_tokens(*parts: str) -> int:
    """Rough token estimate (~4 chars/token) for budget pre-reservation."""
    return sum(len(p or "") for p in parts) // 4


def _turn(
    spec: RoleSpec,
    system: str,
    user: str,
    label: str,
    tracker: RunTracker,
) -> Optional[DebateTurn]:
    """Run one debate turn; return the turn, or ``None`` if the budget is spent."""
    # Reserve the (larger) input prompt plus the output cap so the guard caps at
    # the real boundary rather than under-counting by the input size.
    reserve = _TURN_MAX_TOKENS + _estimate_tokens(system, user)
    if tracker.would_exceed(reserve):
        return None
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    start = time.perf_counter()
    resp = client.chat(spec.model, messages, max_tokens=_TURN_MAX_TOKENS)
    elapsed = time.perf_counter() - start
    inp, out, _ = extract_usage(resp)
    tracker.record(label, spec.model, inp, out, elapsed)
    if is_completion_error(resp):
        detail = get_error_message(resp) or "unknown error"
        return DebateTurn(
            speaker=label,
            text=errors.error_summary(f"{label} turn", f"API error: {detail}"),
            error=True,
        )
    text = extract_text(resp, strict=False).strip()
    if not text:
        # A successful call with empty text is a failure, not a budget skip.
        return DebateTurn(
            speaker=label,
            text=errors.error_summary(f"{label} turn", "model returned empty text"),
            error=True,
        )
    return DebateTurn(speaker=label, text=text)


def run_debate(
    question: str,
    briefing: str,
    views: List[AnalystView],
    *,
    bull_spec: RoleSpec,
    bear_spec: RoleSpec,
    judge_spec: RoleSpec,
    max_rounds: int,
    tracker: RunTracker,
    on_event: Optional[events.EventSink] = None,
) -> DebateResult:
    """Run a bounded bull/bear debate and return the transcript + judged verdict.

    The debate alternates Bull → Bear until ``count >= 2 * max_rounds`` (each round
    is one bull turn plus one bear turn), then the judge issues a stance + summary.
    Every turn is recorded against ``tracker``; once the run token budget is near,
    remaining turns are skipped rather than overrunning the budget.
    """
    date_str = datetime.date.today().isoformat()
    views_text = _views_block(views)
    transcript: List[DebateTurn] = []
    history = ""
    last_opposing = "(no opening argument yet)"
    total_turns = max(0, 2 * int(max_rounds))

    for count in range(total_turns):
        is_bull = count % 2 == 0
        spec = bull_spec if is_bull else bear_spec
        system = (_BULL_SYSTEM if is_bull else _BEAR_SYSTEM).format(date=date_str)
        label = BULL_LABEL if is_bull else BEAR_LABEL
        opponent = "bear" if is_bull else "bull"
        user = (
            f"Question: {question}\n\n"
            f"Briefing packet:\n{briefing or '(none)'}\n\n"
            f"Analyst views:\n{views_text}\n\n"
            f"Debate so far:\n{history or '(none)'}\n\n"
            f"Last {opponent} argument:\n{last_opposing}"
        )
        turn = _turn(spec, system, user, label, tracker)
        if turn is None:
            break
        transcript.append(turn)
        events.safe_emit(
            on_event,
            events.DEBATE_TURN,
            agent=label,
            model=spec.model,
            detail=turn.text,
            data={"error": turn.error},
        )
        if turn.error:
            # One side failed — stop the debate rather than arguing with an error.
            break
        history += f"\n{turn.render()}"
        last_opposing = turn.text
        _pace()

    if total_turns > 0 and not transcript:
        # The debate was requested but the budget was spent before turn one.
        return DebateResult(
            transcript=[],
            summary=errors.error_summary(
                "debate", "token budget exhausted before any debate turn"
            ),
            stance="ERROR",
        )
    summary, stance = _judge(question, views_text, history, judge_spec, tracker)
    events.safe_emit(
        on_event,
        events.DEBATE_VERDICT,
        agent=judge_spec.name,
        model=judge_spec.model,
        detail=stance,
        data={"stance": stance},
    )
    return DebateResult(transcript=transcript, summary=summary, stance=stance)


def _judge(
    question: str,
    views_text: str,
    history: str,
    judge_spec: RoleSpec,
    tracker: RunTracker,
) -> tuple[str, str]:
    """Distil the debate into ``(summary, stance)``."""
    if not history.strip():
        return "", "NEUTRAL"
    date_str = datetime.date.today().isoformat()
    system = _JUDGE_SYSTEM.format(date=date_str)
    user = (
        f"Question: {question}\n\n"
        f"Analyst views:\n{views_text}\n\n"
        f"Debate transcript:\n{history}"
    )
    reserve = _JUDGE_MAX_TOKENS + _estimate_tokens(system, user)
    if tracker.would_exceed(reserve):
        return (
            errors.error_summary(
                "debate judge", "token budget exhausted before verdict"
            ),
            "ERROR",
        )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    start = time.perf_counter()
    resp = client.chat(judge_spec.model, messages, max_tokens=_JUDGE_MAX_TOKENS)
    elapsed = time.perf_counter() - start
    inp, out, _ = extract_usage(resp)
    tracker.record("debate judge", judge_spec.model, inp, out, elapsed)

    if is_completion_error(resp):
        detail = get_error_message(resp) or "unknown error"
        return (
            errors.error_summary("debate judge", f"API error: {detail}"),
            "ERROR",
        )

    text = extract_text(resp, strict=False)
    block = _extract_json_block(text)
    if block is not None:
        try:
            data = json.loads(block)
            stance = str(data.get("stance", "NEUTRAL")).upper()
            summary = str(data.get("summary", "")).strip()
            if stance not in {"BULLISH", "BEARISH", "NEUTRAL"}:
                stance = "NEUTRAL"
            return summary or text.strip()[:600], stance
        except (ValueError, TypeError):
            pass
    return (
        errors.error_summary("debate judge", "unparseable verdict JSON")
        + f" Raw output (truncated): {text.strip()[:400]}",
        "ERROR",
    )
