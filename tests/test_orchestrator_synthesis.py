"""Offline tests for CIO synthesis hardening, the librarian prose fallback and the
budget reservation in ``run_committee`` (FakeLLM — no network, no tokens)."""

from __future__ import annotations

from investment_firm.core import orchestrator
from investment_firm.core.orchestrator import (
    _build_briefing,
    _parse_synthesis,
    _salvage_synthesis,
    _synthesize,
    run_committee,
)
from investment_firm.core.roster import RoleSpec
from investment_firm.core.schemas import AnalystView
from investment_firm.llm.costs import RunTracker

from conftest import FakeLLM, openai_text

_CIO = RoleSpec(
    name="cio",
    group="governance",
    tier="HEAD",
    model="claude-4.8-opus",
    mandate="Rule.",
)
_VIEWS = [
    AnalystView(role="equity_analyst", model="m", stance="BULLISH", rationale="Good.")
]
_OK = '{"recommendation": "BUY", "summary": "Moderate-conviction BUY."}'
_CUT = '{"recommendation": "BUY", "summary": "For a long-term investor, the balance'


def _with_finish(resp: dict, reason: str) -> dict:
    resp["choices"][0]["finish_reason"] = reason
    return resp


def _run_synth(tracker=None):
    s = _synthesize(
        "Should I buy SPY?", "briefing", _VIEWS, _CIO, tracker or RunTracker()
    )
    return s.recommendation, s.summary


class TestSynthesize:
    def test_clean_json_single_call_with_2000_cap(self, fake_llm):
        llm = fake_llm([openai_text(_OK)])
        assert _run_synth() == ("BUY", "Moderate-conviction BUY.")
        llm.assert_call_count(1)
        assert llm.calls[0][2]["max_tokens"] == 2000

    def test_truncated_json_retried_with_double_cap_and_nudge(self, fake_llm):
        llm = fake_llm([_with_finish(openai_text(_CUT), "length"), openai_text(_OK)])
        assert _run_synth() == ("BUY", "Moderate-conviction BUY.")
        llm.assert_call_count(2)
        assert llm.calls[1][2]["max_tokens"] == 4000
        retry_user = llm.calls[1][1][-1]["content"]
        assert "at most 5 sentences" in retry_user
        assert "Should I buy SPY?" in retry_user  # original prompt preserved

    def test_salvage_after_failed_retry_marks_truncated(self, fake_llm):
        llm = fake_llm(
            [
                _with_finish(openai_text(_CUT), "length"),
                _with_finish(openai_text(_CUT), "length"),
            ]
        )
        rec, summary = _run_synth()
        assert rec == "BUY"
        assert summary == "For a long-term investor, the balance (truncated)"
        llm.assert_call_count(2)

    def test_prose_only_is_still_an_explicit_error(self, fake_llm):
        fake_llm([openai_text("I would buy."), openai_text("Still prose.")])
        rec, summary = _run_synth()
        assert rec == "ERROR"
        assert summary.startswith("ERROR: synthesis failed")
        assert "no parseable JSON" in summary
        assert "Still prose." in summary

    def test_api_error_is_explicit_error_without_retry(self, fake_llm):
        llm = fake_llm([{"error": {"message": "boom"}}])
        rec, summary = _run_synth()
        assert rec == "ERROR" and "API error: boom" in summary
        llm.assert_call_count(1)

    def test_budget_precheck_blocks_call(self, monkeypatch):
        fake = FakeLLM([])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        rec, summary = _run_synth(RunTracker(token_budget=500))
        assert rec == "ERROR"
        assert "token budget exhausted" in summary
        assert fake.calls == []

    def test_retry_skipped_when_budget_cannot_fit_it(self, monkeypatch):
        fake = FakeLLM([_with_finish(openai_text(_CUT), "length")])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        # Fits one 2000-token call plus the prompt, but not the 4000-token retry.
        rec, summary = _run_synth(RunTracker(token_budget=3500))
        assert len(fake.calls) == 1
        assert rec == "BUY" and summary.endswith("(truncated)")

    def test_reserved_tokens_count_against_synthesis_precheck(self, monkeypatch):
        fake = FakeLLM([])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        tracker = RunTracker(token_budget=10000)
        tracker.reserve(9000)
        rec, _ = _run_synth(tracker)
        assert rec == "ERROR" and fake.calls == []


class TestSalvageSynthesis:
    def test_requires_a_literal_recommendation(self):
        assert _salvage_synthesis('{"summary": "no rec here') is None
        assert _salvage_synthesis('{"recommendation": "MAYBE", "summary": "x') is None

    def test_recommendation_without_summary(self):
        out = _salvage_synthesis('{"recommendation": "hold", "summ')
        assert (out.recommendation, out.summary) == ("HOLD", "(summary truncated)")

    def test_fenced_input(self):
        out = _salvage_synthesis('```json\n{"recommendation": "SELL", "summary": "Weak')
        assert (out.recommendation, out.summary) == ("SELL", "Weak (truncated)")
        assert out.confidence == 0 and out.key_reasons == []

    def test_headline_is_salvaged_when_complete(self):
        out = _salvage_synthesis(
            '{"recommendation": "BUY", "headline": "Steady buying looks sensible.", '
            '"summary": "Cut'
        )
        assert out.headline == "Steady buying looks sensible."


class TestParseSynthesis:
    def test_rich_contract_fields(self):
        text = (
            '{"recommendation": "buy", "headline": "H.", "summary": "S.", '
            '"confidence": 9, "key_reasons": ["a", "b"], "main_risks": ["r"], '
            '"what_to_watch": ["w1", "w2", "w3", "w4", "w5", "w6", "w7"]}'
        )
        s = _parse_synthesis(text)
        assert s.recommendation == "BUY" and s.headline == "H."
        assert s.confidence == 5
        assert s.key_reasons == ["a", "b"] and s.main_risks == ["r"]
        assert len(s.what_to_watch) == 6

    def test_bad_confidence_is_zero(self):
        s = _parse_synthesis(
            '{"recommendation": "HOLD", "summary": "x", "confidence": "high"}'
        )
        assert s.confidence == 0

    def test_system_prompt_has_plain_language_rules(self):
        from investment_firm.core.orchestrator import _SYNTH_SYSTEM_TMPL

        prompt = _SYNTH_SYSTEM_TMPL.format(date="2026-10-03")
        assert "not a finance professional" in prompt
        assert '"headline"' in prompt and '"what_to_watch"' in prompt
        assert "never advise executing orders" in prompt


class TestLibrarianProseFallback:
    def _patch(self, monkeypatch):
        spec = RoleSpec(
            name="research_librarian",
            group="research",
            tier="WORKER",
            model="claude-4.5-haiku",
            mandate="Brief.",
        )
        monkeypatch.setattr(orchestrator, "_resolve", lambda role, prof: spec)

    def test_prose_briefing_is_kept_instead_of_error(self, fake_llm, monkeypatch):
        self._patch(monkeypatch)
        prose = "## BRIEFING\n- SPY last close $763.99 (Yahoo Finance, 2026-10-02)"
        llm = fake_llm([openai_text(prose)])
        briefing, notes, cites, model = _build_briefing("Q?", "balanced", RunTracker())

        assert "SPY last close $763.99" in briefing
        assert not briefing.startswith("ERROR")
        assert model == "claude-4.5-haiku"
        llm.assert_call_count(1)  # no JSON repair for the librarian
        assert llm.calls[0][2]["max_tokens"] == 2500

    def test_fences_stripped_and_text_capped(self, fake_llm, monkeypatch):
        self._patch(monkeypatch)
        fake_llm([openai_text("```\n" + "§" * 9000 + "\n```")])
        briefing, *_ = _build_briefing("Q?", "balanced", RunTracker())
        assert "```" not in briefing
        assert len(briefing) == 6000

    def test_valid_json_briefing_still_uses_rationale(self, fake_llm, monkeypatch):
        self._patch(monkeypatch)
        fake_llm(
            [
                openai_text(
                    '{"stance":"NEUTRAL","conviction":3,"rationale":"Packet text.",'
                    '"key_risks":[],"evidence":[]}'
                )
            ]
        )
        briefing, *_ = _build_briefing("Q?", "balanced", RunTracker())
        assert briefing == "Packet text."

    def test_api_error_does_not_invent_a_briefing(self, fake_llm, monkeypatch):
        self._patch(monkeypatch)
        fake_llm([{"error": {"message": "boom"}}, {"error": {"message": "boom"}}])
        briefing, *_ = _build_briefing("Q?", "balanced", RunTracker())
        assert briefing.startswith("ERROR")


class TestBudgetReservation:
    _VIEW = (
        '{"stance":"BULLISH","conviction":4,"rationale":"Strong",'
        '"key_risks":["risk"],"evidence":["src: data"]}'
    )

    def test_reserved_during_analysts_released_before_synthesis(self, monkeypatch):
        tracker = RunTracker(token_budget=100000)
        responses = [openai_text(self._VIEW)] * 3 + [openai_text(_OK)]
        seen = []

        def fake(model, messages, **kwargs):
            seen.append(tracker.reserved)
            return responses.pop(0)

        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        memo, _ = run_committee("Q?", profile="budget", simple=True, tracker=tracker)

        assert memo.recommendation == "BUY"
        assert len(seen) == 4
        assert all(r > 0 for r in seen[:3])  # analysts run with synthesis held back
        assert seen[3] == 0  # released before the CIO call
        assert tracker.reserved == 0

    def test_reservation_released_even_if_an_analyst_raises(self, monkeypatch):
        tracker = RunTracker(token_budget=100000)

        def boom(model, messages, **kwargs):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr("investment_firm.llm.client.chat", boom)
        try:
            run_committee("Q?", profile="budget", simple=True, tracker=tracker)
        except RuntimeError:
            pass
        assert tracker.reserved == 0
