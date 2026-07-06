"""Offline tests for the step-event bus (FakeLLM — no network).

Verifies that a simple committee run emits an ordered stream of coarse step
events, and that a consumer which raises never interrupts the run.
"""

from __future__ import annotations

from investment_firm.core import events
from investment_firm.core.orchestrator import run_committee

from conftest import openai_text

_VIEW = (
    '{"stance":"BULLISH","conviction":4,"rationale":"Strong",'
    '"key_risks":["risk"],"evidence":["src: data"]}'
)
_SYNTH = '{"recommendation":"BUY","summary":"The committee recommends BUY."}'


def _simple_responses():
    return [
        openai_text(_VIEW),  # equity_analyst
        openai_text(_VIEW),  # credit_analyst
        openai_text(_VIEW),  # rates_analyst
        openai_text(_SYNTH),  # cio synthesis
    ]


class TestStepEvents:
    def test_simple_run_emits_ordered_events(self, fake_llm, monkeypatch):
        fake_llm(_simple_responses())
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")

        collected = []
        run_committee(
            "Should we buy AAPL?",
            profile="budget",
            simple=True,
            on_event=collected.append,
        )

        kinds = [e.kind for e in collected]
        # Lifecycle brackets are present and correctly ordered.
        assert kinds[0] == events.RUN_STARTED
        assert kinds[-1] == events.RUN_DONE
        assert events.PLAN_DONE in kinds
        assert kinds.count(events.ANALYST_STARTED) == 3
        assert kinds.count(events.ANALYST_DONE) == 3
        assert events.SYNTHESIS_STARTED in kinds
        assert events.SYNTHESIS_DONE in kinds
        # simple mode skips the librarian briefing and the debate.
        assert events.BRIEFING_STARTED not in kinds
        assert events.DEBATE_TURN not in kinds
        # analyst_started always precedes its matching analyst_done.
        assert kinds.index(events.ANALYST_STARTED) < kinds.index(events.ANALYST_DONE)
        # synthesis happens after the last analyst finishes.
        last_done = max(i for i, k in enumerate(kinds) if k == events.ANALYST_DONE)
        assert kinds.index(events.SYNTHESIS_STARTED) > last_done

    def test_analyst_done_carries_stance(self, fake_llm, monkeypatch):
        fake_llm(_simple_responses())
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")

        collected = []
        run_committee("Q?", profile="budget", simple=True, on_event=collected.append)

        done = [e for e in collected if e.kind == events.ANALYST_DONE]
        assert done and all("stance" in e.data for e in done)
        assert done[0].data["stance"] == "BULLISH"

    def test_raising_consumer_does_not_break_run(self, fake_llm, monkeypatch):
        fake_llm(_simple_responses())
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")

        def boom(_event):
            raise RuntimeError("consumer exploded")

        # A broken consumer must never propagate into the pipeline.
        memo, _ = run_committee("Q?", profile="budget", simple=True, on_event=boom)
        assert memo.recommendation == "BUY"
        assert len(memo.views) == 3


class TestSafeEmit:
    def test_none_sink_is_noop(self):
        # Must not raise when there is no consumer.
        events.safe_emit(None, events.RUN_STARTED, detail="x")

    def test_to_dict_shape(self):
        ev = events.StepEvent(kind=events.TOOL_CALLED, agent="a", model="m", seq=7)
        d = events.to_dict(ev)
        assert d["kind"] == events.TOOL_CALLED
        assert d["agent"] == "a"
        assert d["seq"] == 7
        assert "data" in d and isinstance(d["data"], dict)
