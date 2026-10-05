"""Offline tests for the bull/bear debate engine (FakeLLM — no network)."""

from __future__ import annotations

from investment_firm.core import debate as debate_mod
from investment_firm.core.debate import run_debate
from investment_firm.core.roster import RoleSpec
from investment_firm.core.schemas import AnalystView
from investment_firm.llm.costs import RunTracker

from conftest import openai_text


def _spec(name: str) -> RoleSpec:
    return RoleSpec(
        name=name, group="research", tier="SENIOR", model="gpt-4.1", mandate="Debate."
    )


_BULL = _spec("bull_researcher")
_BEAR = _spec("bear_researcher")
_JUDGE = RoleSpec(
    name="cio",
    group="governance",
    tier="HEAD",
    model="claude-4.8-opus",
    mandate="Rule.",
)

_VIEWS = [
    AnalystView(
        role="equity_analyst",
        model="claude-4.5-haiku",
        stance="BULLISH",
        rationale="Cheap vs peers.",
        key_risks=["Margin compression risk"],
    ),
    AnalystView(
        role="market_risk", model="gpt-4.1", stance="BEARISH", rationale="Vol elevated."
    ),
]


def _with_finish(resp: dict, reason: str) -> dict:
    """Stamp an OpenAI-shaped response with a ``finish_reason``."""
    resp["choices"][0]["finish_reason"] = reason
    return resp


def _judge_json(stance: str = "BULLISH", summary: str = "Bull edges it.") -> dict:
    return openai_text(f'{{"stance": "{stance}", "summary": "{summary}"}}')


class TestRunDebate:
    def test_alternates_and_bounds_turns(self, monkeypatch):
        fake_responses = [
            openai_text("Bull point 1"),
            openai_text("Bear point 1"),
            openai_text("Bull point 2"),
            openai_text("Bear point 2"),
            _judge_json(),
        ]
        from conftest import FakeLLM

        fake = FakeLLM(fake_responses)
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)

        tracker = RunTracker(token_budget=0)
        result = run_debate(
            "Is AAPL a buy?",
            "briefing",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=2,
            tracker=tracker,
        )

        assert [t.speaker for t in result.transcript] == [
            "Senior Research Bull",
            "Senior Research Bear",
            "Senior Research Bull",
            "Senior Research Bear",
        ]
        assert result.transcript[0].text == "Bull point 1"
        assert result.stance == "BULLISH"
        assert result.summary == "Bull edges it."
        # 4 debate turns + 1 judge call.
        assert len(fake.calls) == 5
        assert len(tracker.records) == 5

    def test_render_prefixes_speaker(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM([openai_text("up"), openai_text("down"), _judge_json()])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert result.transcript[0].render() == "Senior Research Bull (gpt-4.1): up"
        assert result.transcript[1].render() == "Senior Research Bear (gpt-4.1): down"
        # Each turn carries the model that produced it.
        assert result.transcript[0].model == "gpt-4.1"
        assert result.transcript[1].model == "gpt-4.1"

    def test_zero_rounds_skips_debate_and_judge(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM([])  # no responses should be consumed
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=0,
            tracker=RunTracker(),
        )
        assert result.transcript == []
        assert result.stance == "NEUTRAL"
        assert result.summary == ""
        assert fake.calls == []

    def test_budget_guard_stops_turns(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM([])  # budget exhausted before any call
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        tracker = RunTracker(token_budget=100)  # < _TURN_MAX_TOKENS
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=3,
            tracker=tracker,
        )
        assert result.transcript == []
        assert fake.calls == []  # no LLM spend once the budget can't fit a turn
        # A requested-but-unrun debate is an explicit ERROR, not a quiet NEUTRAL.
        assert result.stance == "ERROR"
        assert "token budget exhausted" in result.summary

    def test_empty_turn_text_is_error_turn(self, monkeypatch):
        from conftest import FakeLLM

        # Empty first reply AND empty retry → error turn (retry consumes 2nd response).
        fake = FakeLLM(
            [
                _with_finish(openai_text(""), "length"),
                _with_finish(openai_text(""), "length"),
                _judge_json("NEUTRAL", "n/a"),
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=2,
            tracker=RunTracker(),
        )
        # Bull's empty reply becomes an error turn and stops the debate.
        assert len(result.transcript) == 1
        turn = result.transcript[0]
        assert turn.error is True
        assert turn.text.startswith("ERROR: Senior Research Bull turn failed")
        assert "empty text" in turn.text
        assert "finish_reason=length" in turn.text
        assert len(fake.calls) == 2

    def test_empty_turn_is_retried_with_four_times_the_cap(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM(
            [
                openai_text(""),  # bull: hidden reasoning ate the budget
                openai_text("Bull recovered"),  # bull retry
                openai_text("Bear point"),
                _judge_json(),
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert [t.text for t in result.transcript] == ["Bull recovered", "Bear point"]
        assert not any(t.error for t in result.transcript)
        assert fake.calls[0][2]["max_tokens"] == debate_mod._TURN_MAX_TOKENS == 1200
        assert fake.calls[1][2]["max_tokens"] == 4800

    def test_truncated_turn_is_retried_and_keeps_longer_text(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM(
            [
                _with_finish(openai_text("Cut off mid-sen"), "length"),
                openai_text("A complete bull argument."),
                openai_text("Bear point"),
                _judge_json(),
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert result.transcript[0].text == "A complete bull argument."

    def test_truncated_turn_kept_when_budget_forbids_retry(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM(
            [
                _with_finish(openai_text("Partial bull argument"), "length"),
                openai_text("Bear point"),
                _judge_json(),
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        # Fits a normal turn (1200 + prompt) but not the 4800-token retry.
        tracker = RunTracker(token_budget=3000)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=tracker,
        )
        assert result.transcript[0].text == "Partial bull argument"
        assert not result.transcript[0].error
        assert (
            fake.calls[1][2]["max_tokens"] == debate_mod._TURN_MAX_TOKENS
        )  # bear turn

    def test_truncated_judge_verdict_is_salvaged(self, monkeypatch):
        from conftest import FakeLLM

        cut = '{"stance": "BEARISH", "summary": "Risks dominate because valuation'
        fake = FakeLLM(
            [
                openai_text("up"),
                openai_text("down"),
                _with_finish(openai_text(cut), "length"),
                _with_finish(openai_text(cut), "length"),  # retry is cut off too
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert result.stance == "BEARISH"
        assert result.summary == "Risks dominate because valuation (truncated)"
        assert fake.calls[2][2]["max_tokens"] == debate_mod._JUDGE_MAX_TOKENS == 800
        assert fake.calls[3][2]["max_tokens"] == 3200

    def test_empty_judge_verdict_is_retried(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM(
            [
                openai_text("up"),
                openai_text("down"),
                _with_finish(openai_text(""), "length"),
                _judge_json("BULLISH", "Recovered verdict."),
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert (result.stance, result.summary) == ("BULLISH", "Recovered verdict.")

    def test_reserve_starves_analysts_not_the_debate(self, monkeypatch):
        """Reserved budget blocks earlier stages but is free for the debate once released."""
        from conftest import FakeLLM
        from investment_firm.core.agent import Agent

        tracker = RunTracker(token_budget=20000)
        tracker.reserve(19000)

        # Analyst stage: the reservation makes a 1200-token call "exceed" → no spend.
        fake = FakeLLM([])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        view = Agent(_spec("equity_analyst"), tools=None).run("q", tracker=tracker)
        assert view.stance == "ERROR"
        assert fake.calls == []

        # Debate stage: reservation released → turns and judge are funded.
        tracker.release(19000)
        assert tracker.reserved == 0
        fake2 = FakeLLM([openai_text("up"), openai_text("down"), _judge_json()])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake2)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=tracker,
        )
        assert len(result.transcript) == 2
        assert result.stance == "BULLISH"

    def test_tracker_reserve_release_remaining(self):
        tracker = RunTracker(token_budget=10000)
        assert tracker.remaining() == 10000
        tracker.reserve(6000)
        assert tracker.would_exceed(5000) is True
        assert tracker.would_exceed(4000) is False
        assert tracker.remaining() == 4000
        tracker.release(2000)
        assert tracker.reserved == 4000
        tracker.release()
        assert tracker.reserved == 0
        assert RunTracker().remaining() is None  # no budget → unbounded

    def test_debate_token_estimate(self):
        assert debate_mod.debate_token_estimate(0, 5000) == 0
        one = debate_mod.debate_token_estimate(1, 5000)
        two = debate_mod.debate_token_estimate(2, 5000)
        assert 0 < one < two

    def test_labels_and_prompt_carry_analyst_reasoning(self, monkeypatch):
        """Obj 1 acceptance: named Senior Research Bull/Bear whose prompts provably
        include the analysts' full rationale + key risks."""
        from conftest import FakeLLM

        fake = FakeLLM([openai_text("up"), openai_text("down"), _judge_json()])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert [t.speaker for t in result.transcript] == [
            debate_mod.BULL_LABEL,
            debate_mod.BEAR_LABEL,
        ]
        assert debate_mod.BULL_LABEL == "Senior Research Bull"
        assert debate_mod.BEAR_LABEL == "Senior Research Bear"

        bull_system = fake.calls[0][1][0]["content"]
        bull_user = fake.calls[0][1][1]["content"]
        # System prompt names the role and tells the debater to cite colleagues by role.
        assert "Senior Research Bull" in bull_system
        assert "[equity_analyst]" in bull_system
        # The turn prompt carries the analysts' real reasoning, not a one-liner.
        assert "Cheap vs peers." in bull_user
        assert "Margin compression risk" in bull_user
        assert "equity_analyst" in bull_user

    def test_unparseable_judge_yields_error_stance(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM(
            [openai_text("up"), openai_text("down"), openai_text("not json")]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        result = run_debate(
            "q",
            "b",
            _VIEWS,
            bull_spec=_BULL,
            bear_spec=_BEAR,
            judge_spec=_JUDGE,
            max_rounds=1,
            tracker=RunTracker(),
        )
        assert result.stance == "ERROR"
        assert result.summary.startswith("ERROR: debate judge failed")
        assert "not json" in result.summary
