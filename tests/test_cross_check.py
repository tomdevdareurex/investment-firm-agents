"""Offline tests for the CIO cross-check (second opinion) module."""

from __future__ import annotations

from investment_firm.core import events
from investment_firm.core.cross_check import (
    MAX_TOKENS,
    TRACKER_LABEL,
    cross_check_synthesis,
    pick_reviewer_model,
    render_cross_check,
)
from investment_firm.core.orchestrator import Synthesis
from investment_firm.core.schemas import AnalystView, Memo
from investment_firm.llm.costs import RunTracker

from conftest import openai_text

_VIEWS = [
    AnalystView(role="equity_analyst", model="m", stance="BULLISH", rationale="Good."),
    AnalystView(role="risk_officer", model="m", stance="BEARISH", rationale="Costly."),
]
_SYNTH = Synthesis(
    recommendation="BUY",
    summary="Moderate-conviction BUY.",
    headline="Steady buying looks reasonable.",
    key_reasons=["Earnings grow."],
    main_risks=["Valuation."],
    confidence=3,
)
_FIRM = {
    "default_profile": "premium",
    "profiles": {
        "premium": {
            "WORKER": ["claude-4.5-haiku"],
            "SENIOR": ["gemini-3.1-pro"],
            "AUTHORITY": ["claude-5.5-opus", "gpt-5.6-terra"],
            "HEAD": ["claude-5.5-opus"],
        },
        "mono": {
            "WORKER": ["claude-4.5-haiku"],
            "SENIOR": ["claude-5.5-sonnet"],
            "AUTHORITY": ["claude-5.5-opus"],
            "HEAD": ["claude-5.5-opus"],
        },
        "solo": {"HEAD": ["claude-5.5-opus"]},
    },
}


def _collect():
    seen = []
    return seen, seen.append


class TestPickReviewerModel:
    def test_prefers_authority_with_other_family(self):
        assert (
            pick_reviewer_model("claude-5.5-opus", profile="premium", firm=_FIRM)
            == "gpt-5.6-terra"
        )

    def test_databricks_prefix_is_stripped_for_family(self):
        assert (
            pick_reviewer_model(
                "databricks-claude-opus-5-5", profile="premium", firm=_FIRM
            )
            == "gpt-5.6-terra"
        )

    def test_falls_back_to_senior_when_authority_shares_family(self):
        # gpt synth: AUTHORITY has claude-5.5-opus (different family) first.
        assert (
            pick_reviewer_model("gpt-5.6-terra", profile="premium", firm=_FIRM)
            == "claude-5.5-opus"
        )

    def test_same_family_everywhere_picks_any_other_model(self):
        assert (
            pick_reviewer_model("claude-5.5-opus", profile="mono", firm=_FIRM)
            == "claude-5.5-sonnet"
        )

    def test_none_when_nothing_else_configured(self):
        assert pick_reviewer_model("claude-5.5-opus", profile="solo", firm=_FIRM) is None


class TestCrossCheckSynthesis:
    def test_agrees(self, fake_llm):
        llm = fake_llm(
            [openai_text('{"agrees": true, "concerns": [], "note": "Sound ruling."}')]
        )
        tracker = RunTracker()
        seen, sink = _collect()
        result = cross_check_synthesis(
            "Q?",
            _SYNTH,
            _VIEWS,
            model="gpt-5.6-terra",
            tracker=tracker,
            on_event=sink,
            enabled=True,
        )
        assert result == {
            "status": "ok",
            "model": "gpt-5.6-terra",
            "agrees": True,
            "concerns": [],
            "note": "Sound ruling.",
        }
        llm.assert_call_count(1)
        model, messages, kwargs = llm.calls[0]
        assert model == "gpt-5.6-terra"
        assert kwargs["max_tokens"] == MAX_TOKENS
        assert kwargs["json_mode"] is True
        user = messages[-1]["content"]
        assert "Recommendation: BUY" in user
        assert "equity_analyst" in user and "risk_officer" in user
        assert [r.agent for r in tracker.records] == [TRACKER_LABEL]
        assert [e.kind for e in seen] == [events.CROSS_CHECK_DONE]
        assert seen[0].data["status"] == "ok"

    def test_disagrees_caps_concerns_at_three(self, fake_llm):
        fake_llm(
            [
                openai_text(
                    '{"agrees": false, "concerns": ["a", "b", "c", "d"], '
                    '"note": "Bear case under-weighted."}'
                )
            ]
        )
        result = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="gpt-5.6-terra", tracker=RunTracker(), enabled=True
        )
        assert result["status"] == "ok"
        assert result["agrees"] is False
        assert result["concerns"] == ["a", "b", "c"]

    def test_fenced_json_is_accepted(self, fake_llm):
        fake_llm([openai_text('```json\n{"agrees": "yes", "concerns": []}\n```')])
        result = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="m", tracker=RunTracker(), enabled=True
        )
        assert result["status"] == "ok" and result["agrees"] is True

    def test_skipped_when_profile_disables_it(self, fake_llm):
        llm = fake_llm([])
        seen, sink = _collect()
        result = cross_check_synthesis(
            "Q?",
            _SYNTH,
            _VIEWS,
            model="m",
            tracker=RunTracker(),
            profile="balanced",
            on_event=sink,
        )
        assert result["status"] == "skipped"
        assert "disabled for profile 'balanced'" in result["reason"]
        llm.assert_call_count(0)
        assert [e.kind for e in seen] == [events.CROSS_CHECK_DONE]

    def test_skipped_without_reviewer_model(self, fake_llm):
        llm = fake_llm([])
        result = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model=None, tracker=RunTracker(), enabled=True
        )
        assert result == {"status": "skipped", "reason": "no reviewer model available"}
        llm.assert_call_count(0)

    def test_skipped_when_synthesis_failed(self, fake_llm):
        llm = fake_llm([])
        bad = Synthesis(recommendation="ERROR", summary="API error: boom")
        result = cross_check_synthesis(
            "Q?", bad, _VIEWS, model="m", tracker=RunTracker(), enabled=True
        )
        assert result["status"] == "skipped"
        assert "nothing to cross-check" in result["reason"]
        llm.assert_call_count(0)

    def test_skipped_when_budget_exhausted(self, fake_llm):
        llm = fake_llm([])
        tracker = RunTracker(token_budget=500)
        result = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="m", tracker=tracker, enabled=True
        )
        assert result["status"] == "skipped"
        assert "budget" in result["reason"]
        llm.assert_call_count(0)
        assert tracker.records == []

    def test_api_error_is_explicit(self, fake_llm):
        fake_llm([{"error": {"message": "boom"}}])
        tracker = RunTracker()
        result = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="m", tracker=tracker, enabled=True
        )
        assert result["status"] == "error"
        assert result["reason"] == "API error: boom"
        assert result["model"] == "m"
        assert "agrees" not in result
        assert [r.agent for r in tracker.records] == [TRACKER_LABEL]

    def test_unparseable_and_empty(self, fake_llm):
        fake_llm([openai_text("I think it is fine."), openai_text("")])
        unparseable = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="m", tracker=RunTracker(), enabled=True
        )
        assert unparseable["status"] == "error"
        assert unparseable["reason"] == "unparseable JSON"
        assert unparseable["raw"] == "I think it is fine."
        empty = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="m", tracker=RunTracker(), enabled=True
        )
        assert empty["status"] == "error" and empty["reason"] == "empty response"

    def test_missing_agrees_key_is_unparseable(self, fake_llm):
        fake_llm([openai_text('{"concerns": ["x"]}')])
        result = cross_check_synthesis(
            "Q?", _SYNTH, _VIEWS, model="m", tracker=RunTracker(), enabled=True
        )
        assert result["status"] == "error" and result["reason"] == "unparseable JSON"


class TestRendering:
    def test_render_ok_disagrees(self):
        text = render_cross_check(
            {
                "status": "ok",
                "model": "gpt-5.6-terra",
                "agrees": False,
                "concerns": ["Valuation stretched."],
                "note": "Bear case under-weighted.",
            }
        )
        assert "Second opinion (gpt-5.6-terra): DISAGREES" in text
        assert "advisory" in text
        assert "Bear case under-weighted." in text
        assert "- concern: Valuation stretched." in text

    def test_render_error_and_skipped(self):
        err = render_cross_check({"status": "error", "model": "m", "reason": "API error: x"})
        assert "unavailable" in err and "API error: x" in err
        assert render_cross_check({"status": "skipped", "reason": "budget"}) == ""
        assert render_cross_check({}) == ""

    def test_memo_render_includes_second_opinion(self):
        memo = Memo(
            question="Q?",
            recommendation="BUY",
            summary="Fine.",
            views=_VIEWS,
            cross_check={
                "status": "ok",
                "model": "gpt-5.6-terra",
                "agrees": True,
                "concerns": [],
                "note": "Sound.",
            },
        )
        rendered = memo.render()
        assert "Second opinion (gpt-5.6-terra): agrees with the ruling" in rendered
        assert "Sound." in rendered
        plain = Memo(question="Q?", recommendation="BUY", summary="Fine.", views=_VIEWS)
        assert "Second opinion" not in plain.render()
        assert plain.cross_check == {}
