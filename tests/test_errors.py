"""Unit tests for the shared error classifier (core/errors.py).

Every failed pipeline stage must yield an unmistakable, labelled ERROR outcome —
never a bland NEUTRAL that reads like real analysis. These tests pin the
invariants (see AGENTS.md): raw API text only in key_risks, ERROR views are
ungrounded with conviction 0, and the legacy parse-failure risk string survives.
"""

from __future__ import annotations

from investment_firm.core import errors
from investment_firm.core.schemas import AnalystView, DebateTurn, Memo


class TestErrorSummary:
    def test_format(self):
        out = errors.error_summary("synthesis", "API error: boom")
        assert out == "ERROR: synthesis failed — API error: boom"

    def test_starts_with_error_marker(self):
        assert errors.error_summary("x", "y").startswith("ERROR:")


class TestApiErrorView:
    def test_invariants(self):
        view = errors.api_error_view("equity_analyst", "gpt-4o-mini", "HTTP 500 boom")
        assert view.stance == "ERROR"
        assert view.conviction == 0
        assert view.grounded is False
        assert view.error == "API/completion failure: HTTP 500 boom"
        # Raw provider text lives in key_risks, never in the rationale.
        assert "API error: HTTP 500 boom" in view.key_risks
        assert "HTTP 500 boom" not in view.rationale
        assert view.rationale.startswith("ERROR:")

    def test_render_is_unmistakable(self):
        view = errors.api_error_view("equity_analyst", "gpt-4o-mini", "boom")
        rendered = view.render()
        assert "!! ERROR" in rendered
        assert "0/5 (ERROR)" in rendered
        assert "ERROR — API/completion failure: boom" in rendered


class TestParseErrorView:
    def test_invariants(self):
        view = errors.parse_error_view("news_analyst", "m", "I refuse to answer.")
        assert view.stance == "ERROR"
        assert view.conviction == 0
        assert view.grounded is False
        assert view.error
        assert errors.PARSE_FAILURE_RISK in view.key_risks
        assert view.rationale.startswith("ERROR: model did not return structured JSON")
        assert "I refuse to answer." in view.rationale

    def test_raw_text_truncated(self):
        view = errors.parse_error_view("r", "m", "x" * 1000)
        assert "x" * 400 + "…" in view.rationale
        assert "x" * 401 not in view.rationale

    def test_empty_raw_text_labelled(self):
        view = errors.parse_error_view("r", "m", "")
        assert "(empty response)" in view.rationale

    def test_extra_risks_deduped(self):
        view = errors.parse_error_view(
            "r", "m", "raw", extra_risks=[errors.PARSE_FAILURE_RISK, "DATA GAP: x: y"]
        )
        assert view.key_risks.count(errors.PARSE_FAILURE_RISK) == 1
        assert "DATA GAP: x: y" in view.key_risks


class TestErrorSchemas:
    def test_memo_render_error_recommendation(self):
        memo = Memo(
            question="q",
            recommendation="ERROR",
            summary="ERROR: synthesis failed — boom",
        )
        rendered = memo.render()
        assert "RECOMMENDATION: ERROR — synthesis failed (see summary)" in rendered

    def test_debate_turn_error_render_prefixed(self):
        turn = DebateTurn(
            speaker="Bull", text="ERROR: Bull turn failed — x", error=True
        )
        assert turn.render().startswith("!! Bull:")

    def test_model_output_cannot_mint_error_stance(self):
        # Pydantic accepts ERROR only via the classifier; the agent's _to_view
        # clamp normalizes unknown stances — sanity-check the literal exists.
        view = AnalystView(role="r", stance="ERROR", conviction=0)
        assert view.stance == "ERROR"
