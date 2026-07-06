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
        assert result.transcript[0].render() == "Senior Research Bull: up"
        assert result.transcript[1].render() == "Senior Research Bear: down"

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

        fake = FakeLLM([openai_text(""), _judge_json("NEUTRAL", "n/a")])
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
