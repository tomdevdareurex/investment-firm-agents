"""Offline tests for the read-only quant consultant (FakeLLM — no network)."""

from __future__ import annotations

import json

from unittest.mock import MagicMock

from investment_firm.core import risk
from investment_firm.core.consultant import (
    CONSULTANT_TOOL_NAMES,
    Consultant,
    RunContext,
    consultant_registry,
)
from investment_firm.core.schemas import AnalystView, Memo

from conftest import openai_text, openai_tool_call


def _memo() -> Memo:
    return Memo(
        question="Should we buy AAPL?",
        profile="balanced",
        recommendation="HOLD",
        summary="Balanced risk/reward; wait for a better entry.",
        views=[
            AnalystView(
                role="equity_analyst",
                model="gpt-4.1",
                stance="BULLISH",
                conviction=4,
                rationale="Strong franchise, rich multiple.",
            )
        ],
        synth_role="cio",
        synth_model="claude-4.8-opus",
    )


def _ctx() -> RunContext:
    return RunContext(_memo(), events_log=[])


class TestConsultantAnswers:
    def test_answers_from_run_memory(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM([openai_text("The committee landed on HOLD because …")])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)

        consultant = Consultant(_ctx(), model="gpt-4.1")
        answer = consultant.ask("Why HOLD?", stream=False)

        assert "HOLD" in answer
        # The system message carries the run context, incl. the recommendation.
        system_msg = fake.calls[0][1][0]["content"]
        assert "HOLD" in system_msg
        assert "Should we buy AAPL?" in system_msg

    def test_error_response_is_explicit(self, monkeypatch):
        from conftest import FakeLLM

        fake = FakeLLM([{"error": {"message": "gateway exploded"}}])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)

        consultant = Consultant(_ctx(), model="gpt-4.1")
        answer = consultant.ask("Explain.", stream=False)
        assert answer.startswith("ERROR: consultant call failed")
        assert "gateway exploded" in answer

    def test_stream_does_not_regenerate_answer(self, monkeypatch):
        """stream=True must reuse the already-billed answer (no 2nd generation)."""
        from conftest import FakeLLM
        from investment_firm.core import events as ev

        fake = FakeLLM([openai_text("Streamed answer body.")])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)
        # Guard: if stream_chat is ever called here it means a double-generation.
        called = {"stream_chat": 0}

        def _boom(*a, **k):
            called["stream_chat"] += 1
            return ""

        monkeypatch.setattr("investment_firm.llm.client.stream_chat", _boom)

        collected = []
        consultant = Consultant(_ctx(), model="gpt-4.1")
        answer = consultant.ask("Q?", stream=True, on_event=collected.append)

        assert answer == "Streamed answer body."
        assert called["stream_chat"] == 0  # never re-generated
        assert len(fake.calls) == 1  # only the loop's single billed call
        # The existing answer was chunked into chat_token events for a live feel.
        assert any(e.kind == ev.CHAT_TOKEN for e in collected)
        assert any(e.kind == ev.CHAT_DONE for e in collected)


class TestConsultantReadOnly:
    def test_registry_is_exactly_the_readonly_subset(self):
        reg = consultant_registry()
        names = set(reg.names())
        assert names == set(CONSULTANT_TOOL_NAMES)

    def test_no_write_or_order_tools(self):
        reg = consultant_registry()
        names = set(reg.names())
        # Nothing resembling a write/execute/order capability.
        for forbidden in ("place_order", "execute", "write", "trade", "buy", "sell"):
            assert not any(forbidden in n for n in names)

    def test_system_prompt_forbids_writes_and_trades(self):
        consultant = Consultant(_ctx(), model="gpt-4.1")
        system = consultant._messages("q", None)[0]["content"]
        assert "READ-ONLY" in system
        assert "never place, size, or recommend a trade" in system.lower() or (
            "do not direct capital" in system.lower()
        )


class TestConsultantBacktest:
    _PRICES = [100.0, 120.0, 90.0, 110.0, 95.0, 130.0, 105.0]
    _DATES = [f"2025-02-{i+1:02d}" for i in range(len(_PRICES))]

    def _patch_yf(self, monkeypatch):
        import pandas as pd

        idx = pd.DatetimeIndex(self._DATES)
        hist = pd.DataFrame({"Close": self._PRICES}, index=idx)
        ticker = MagicMock()
        ticker.history.return_value = hist
        fake_yf = MagicMock()
        fake_yf.Ticker.return_value = ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    def test_backtest_tool_computes_max_drawdown(self, monkeypatch):
        self._patch_yf(monkeypatch)
        reg = consultant_registry()
        out = json.loads(reg.dispatch("run_backtest", '{"ticker": "AAPL"}'))
        expected_dd = round(risk.max_drawdown(self._PRICES) * 100, 2)
        assert out["max_drawdown_pct"] == expected_dd
        assert out["strategy"] == "buy-and-hold"
        assert out["ticker"] == "AAPL"

    def test_consultant_loop_dispatches_backtest(self, monkeypatch):
        from conftest import FakeLLM

        self._patch_yf(monkeypatch)
        fake = FakeLLM(
            [
                openai_tool_call("run_backtest", {"ticker": "AAPL"}),
                openai_text("Over the window the drawdown was material."),
            ]
        )
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)

        consultant = Consultant(_ctx(), model="gpt-4.1")
        answer = consultant.ask("Backtest AAPL please.", stream=False)
        assert "drawdown" in answer.lower()
        # Two calls: the tool-call turn and the final prose turn.
        assert len(fake.calls) == 2
        # The tool result was fed back as a tool message before the final answer.
        second_call_messages = fake.calls[1][1]
        assert any(m.get("role") == "tool" for m in second_call_messages)
