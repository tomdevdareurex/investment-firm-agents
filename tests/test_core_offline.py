"""Offline unit tests for core/ — no network, no tokens.

Covers:
- Agent JSON parsing (clean / fenced / truncated / plain-text fallback)
- Agent.run with one fake tool-call round
- ToolRegistry.dispatch (unknown tool, bad JSON args, ToolError, success)
- ScratchMemory and RunMemory.context_for
- AnalystView.render and Memo.render / all_sources dedup
- run_committee(simple=True) end-to-end via FakeLLM
- planner plan_roles fallback to all candidates on unparseable JSON
- Agent resilience (error retry, finalization, API error fallback)
- Orchestrator web-search enablement per model family and profile setting
- runs.py API-error warning generation
"""
from __future__ import annotations

import datetime
import json
from typing import List
from unittest.mock import MagicMock

import pytest

from investment_firm.core.agent import Agent, _extract_json_block, _salvage_fields, _strip_fences
from investment_firm.core.memory import RunMemory, ScratchMemory
from investment_firm.core.orchestrator import run_committee
from investment_firm.core.planner import plan_roles
from investment_firm.core.roster import RoleSpec, load_firm, resolve_roles
from investment_firm.core.schemas import AnalystView, Memo
from investment_firm.core.tools.base import Tool, ToolError, ToolRegistry
from investment_firm.llm.costs import RunTracker

from conftest import anthropic_text, openai_text, openai_tool_call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIRM = load_firm()


def _spec(name: str = "equity_analyst", model: str = "gpt-4o-mini") -> RoleSpec:
    """Return a minimal RoleSpec for testing — avoids firm.yaml lookup."""
    return RoleSpec(
        name=name,
        group="research",
        tier="WORKER",
        model=model,
        mandate="Test mandate.",
    )


def _clean_json() -> str:
    return json.dumps({
        "stance": "BULLISH",
        "conviction": 4,
        "rationale": "Strong earnings.",
        "key_risks": ["recession"],
        "evidence": ["Bloomberg: +5%"],
    })


# ---------------------------------------------------------------------------
# Agent JSON parsing
# ---------------------------------------------------------------------------

class TestAgentParsing:
    def _agent(self) -> Agent:
        return Agent(_spec())

    def test_clean_json(self):
        view = self._agent()._parse(_clean_json())
        assert view.stance == "BULLISH"
        assert view.conviction == 4
        assert view.rationale == "Strong earnings."
        assert "recession" in view.key_risks
        assert "Bloomberg: +5%" in view.evidence

    def test_json_fenced(self):
        fenced = f"```json\n{_clean_json()}\n```"
        view = self._agent()._parse(fenced)
        assert view.stance == "BULLISH"

    def test_truncated_salvage(self):
        # Truncated before closing braces — _salvage_fields should rescue it.
        truncated = '{"stance": "BEARISH", "conviction": 2, "rationale": "Too much debt'
        view = self._agent()._parse(truncated)
        assert view.stance == "BEARISH"
        assert view.conviction == 2
        assert "Too much debt" in view.rationale

    def test_plain_text_fallback(self):
        # Total garbage — falls through to the plain-text fallback.
        view = self._agent()._parse("I think it is bullish overall.")
        assert view.stance == "NEUTRAL"
        assert view.conviction == 2
        assert "bullish overall" in view.rationale

    def test_invalid_stance_normalised(self):
        data = json.dumps({"stance": "VERY_BULLISH", "conviction": 3, "rationale": "x"})
        view = self._agent()._parse(data)
        assert view.stance == "NEUTRAL"

    def test_conviction_clamped(self):
        data = json.dumps({"stance": "BULLISH", "conviction": 99, "rationale": "x"})
        view = self._agent()._parse(data)
        assert view.conviction == 5


# ---------------------------------------------------------------------------
# _strip_fences / _extract_json_block / _salvage_fields helpers
# ---------------------------------------------------------------------------

def test_strip_fences_removes_markers():
    assert _strip_fences("```json\n{}\n```") == "{}"


def test_extract_json_block_balanced():
    text = 'prefix {"a": 1, "b": {"c": 2}} suffix'
    assert _extract_json_block(text) == '{"a": 1, "b": {"c": 2}}'


def test_extract_json_block_returns_none_for_no_brace():
    assert _extract_json_block("no braces here") is None


def test_salvage_fields_truncated():
    text = '{"stance": "NEUTRAL", "conviction": 3, "rationale": "OK data'
    result = _salvage_fields(text)
    assert result is not None
    assert result["stance"] == "NEUTRAL"
    assert result["conviction"] == 3


def test_salvage_fields_returns_none_on_no_signal():
    assert _salvage_fields("completely unrelated text") is None


# ---------------------------------------------------------------------------
# Agent.run with one tool-call round
# ---------------------------------------------------------------------------

class TestAgentRun:
    def _make_tool(self, result: str = "42") -> Tool:
        return Tool(
            name="get_data",
            description="Get some data",
            parameters={"type": "object", "properties": {}},
            func=lambda: result,
        )

    def test_agent_run_with_tool_call(self, fake_llm):
        """Agent does one tool-call round then emits a final JSON view."""
        final = _clean_json()
        llm = fake_llm([
            openai_tool_call("get_data", {}),          # first call → tool call
            openai_text(final),                         # second call → final view
        ])

        registry = ToolRegistry([self._make_tool("market data")])
        agent = Agent(_spec(), tools=registry, max_steps=4)
        tracker = RunTracker()
        view = agent.run("Should we buy AAPL?", tracker=tracker)

        assert view.stance == "BULLISH"
        llm.assert_call_count(2)
        # Memory should capture the tool dispatch
        assert any("get_data" in n for n in agent.memory.notes)

    def test_agent_run_no_tools(self, fake_llm):
        """Without tools, agent exits after the first response."""
        llm = fake_llm([openai_text(_clean_json())])
        agent = Agent(_spec(), tools=None, max_steps=3)
        view = agent.run("Simple question")
        assert view.stance == "BULLISH"
        llm.assert_call_count(1)

    def test_agent_run_budget_exceeded(self, fake_llm):
        """Agent stops early when the tracker budget would be exceeded."""
        llm = fake_llm([])  # no responses — should not be called at all
        tracker = RunTracker(token_budget=1)  # already exhausted
        tracker.record("x", "m", 1, 0)  # consume 1 token → budget full
        agent = Agent(_spec(), tools=None, max_steps=3, max_tokens=10)
        view = agent.run("question", tracker=tracker)
        # Falls back gracefully
        assert view.stance == "NEUTRAL"
        llm.assert_call_count(0)

    def test_agent_run_anthropic_response(self, fake_llm):
        """Agent correctly parses an Anthropic-shaped response."""
        llm = fake_llm([anthropic_text(_clean_json())])
        agent = Agent(_spec(), tools=None)
        view = agent.run("question")
        assert view.stance == "BULLISH"


# ---------------------------------------------------------------------------
# ToolRegistry.dispatch
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def _registry(self) -> ToolRegistry:
        def _good(**kwargs):
            return {"value": kwargs.get("x", 0) * 2}

        def _bad(**kwargs):
            raise ToolError("simulated failure")

        return ToolRegistry([
            Tool("good_tool", "desc", {"type": "object", "properties": {"x": {"type": "number"}}}, _good),
            Tool("bad_tool", "desc", {"type": "object", "properties": {}}, _bad),
        ])

    def test_dispatch_success(self):
        r = self._registry()
        result = json.loads(r.dispatch("good_tool", {"x": 5}))
        assert result == {"value": 10}

    def test_dispatch_unknown_tool(self):
        r = self._registry()
        result = json.loads(r.dispatch("no_such_tool", {}))
        assert "error" in result
        assert "unknown tool" in result["error"]

    def test_dispatch_bad_json_args(self):
        r = self._registry()
        result = json.loads(r.dispatch("good_tool", "not-json!!"))
        assert "error" in result
        assert "invalid JSON" in result["error"]

    def test_dispatch_tool_error(self):
        r = self._registry()
        result = json.loads(r.dispatch("bad_tool", {}))
        assert "error" in result
        assert "simulated failure" in result["error"]

    def test_dispatch_args_as_json_string(self):
        r = self._registry()
        result = json.loads(r.dispatch("good_tool", '{"x": 3}'))
        assert result == {"value": 6}

    def test_dispatch_empty_args_string(self):
        r = self._registry()
        result = json.loads(r.dispatch("good_tool", ""))
        assert result == {"value": 0}


# ---------------------------------------------------------------------------
# ScratchMemory
# ---------------------------------------------------------------------------

class TestScratchMemory:
    def test_remember_and_render(self):
        m = ScratchMemory()
        m.remember("observation A")
        m.remember("  observation B  ")  # strips whitespace
        text = m.render()
        assert "observation A" in text
        assert "observation B" in text

    def test_empty_render(self):
        assert ScratchMemory().render() == ""

    def test_blank_note_ignored(self):
        m = ScratchMemory()
        m.remember("   ")
        assert m.notes == []


# ---------------------------------------------------------------------------
# RunMemory.context_for
# ---------------------------------------------------------------------------

class TestRunMemory:
    def test_context_includes_briefing(self):
        mem = RunMemory()
        mem.set_briefing("ECB rate: 2.5%")
        ctx = mem.context_for("equity_analyst")
        assert "ECB rate" in ctx

    def test_context_excludes_self(self):
        mem = RunMemory()
        mem.record_finding("equity_analyst", "BULLISH 4/5")
        mem.record_finding("credit_analyst", "BEARISH 2/5")
        ctx = mem.context_for("equity_analyst")
        assert "credit_analyst" in ctx
        assert "equity_analyst" not in ctx

    def test_context_includes_peers(self):
        mem = RunMemory()
        mem.record_finding("rates_analyst", "NEUTRAL 3/5")
        ctx = mem.context_for("equity_analyst")
        assert "rates_analyst" in ctx

    def test_context_empty_when_nothing_recorded(self):
        mem = RunMemory()
        assert mem.context_for("anyone") == ""

    def test_set_briefing_strips_whitespace(self):
        mem = RunMemory()
        mem.set_briefing("  hello  ")
        assert mem.briefing == "hello"


# ---------------------------------------------------------------------------
# AnalystView.render and Memo.render / all_sources
# ---------------------------------------------------------------------------

class TestSchemas:
    def _view(self, role: str = "equity_analyst", stance: str = "BULLISH") -> AnalystView:
        return AnalystView(
            role=role,
            model="gpt-4o-mini",
            stance=stance,
            conviction=4,
            rationale="Good fundamentals.",
            key_risks=["rate hike"],
            evidence=["Bloomberg: P/E=18"],
        )

    def test_analyst_view_render_contains_role(self):
        text = self._view().render()
        assert "equity_analyst" in text
        assert "BULLISH" in text
        assert "Good fundamentals" in text
        assert "rate hike" in text
        assert "Bloomberg" in text

    def test_memo_render_contains_recommendation(self):
        memo = Memo(
            question="Buy AAPL?",
            profile="balanced",
            recommendation="BUY",
            summary="Strong fundamentals.",
            views=[self._view()],
            sources=["ECB SDW"],
            disclaimer="Decision-support only.",
        )
        text = memo.render()
        assert "BUY" in text
        assert "Strong fundamentals" in text
        assert "ECB SDW" in text
        assert "Decision-support only" in text

    def test_all_sources_dedup(self):
        view1 = AnalystView(role="a", evidence=["src1", "src2"])
        view2 = AnalystView(role="b", evidence=["src2", "src3"])
        memo = Memo(
            question="Q",
            recommendation="HOLD",
            summary="s",
            views=[view1, view2],
            sources=["src1", "src0"],
        )
        sources = memo.all_sources()
        # No duplicates
        assert len(sources) == len(set(sources))
        # All present
        for s in ["src0", "src1", "src2", "src3"]:
            assert s in sources


# ---------------------------------------------------------------------------
# run_committee(simple=True) — end-to-end via FakeLLM
# ---------------------------------------------------------------------------

# JSON views for the three simple-mode analysts.
_VIEW = '{"stance":"BULLISH","conviction":4,"rationale":"Strong","key_risks":["risk"],"evidence":["src: data"]}'
_SYNTH = '{"recommendation":"BUY","summary":"The committee recommends BUY."}'


class TestRunCommitteeSimple:
    def test_returns_memo_with_views(self, fake_llm, monkeypatch):
        # simple=True runs 3 fixed analysts + 1 synthesis = 4 calls.
        llm = fake_llm([
            openai_text(_VIEW),   # equity_analyst
            openai_text(_VIEW),   # credit_analyst
            openai_text(_VIEW),   # rates_analyst
            openai_text(_SYNTH),  # cio synthesis
        ])
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")

        memo, tracker = run_committee(
            "Should we buy AAPL?",
            profile="budget",
            simple=True,
        )

        assert isinstance(memo, Memo)
        assert memo.recommendation == "BUY"
        assert len(memo.views) == 3
        assert memo.profile == "budget"
        assert "Decision-support" in memo.disclaimer
        llm.assert_call_count(4)

    def test_tracker_records_calls(self, fake_llm, monkeypatch):
        llm = fake_llm([
            openai_text(_VIEW),
            openai_text(_VIEW),
            openai_text(_VIEW),
            openai_text(_SYNTH),
        ])
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")

        memo, tracker = run_committee("Q?", profile="budget", simple=True)

        assert tracker.total_tokens > 0
        assert len(tracker.records) == 4

    def test_memo_sources_dedup(self, fake_llm, monkeypatch):
        # All three views carry the same evidence; all_sources should dedup.
        llm = fake_llm([
            openai_text(_VIEW),
            openai_text(_VIEW),
            openai_text(_VIEW),
            openai_text(_SYNTH),
        ])
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
        memo, _ = run_committee("Q?", profile="budget", simple=True)
        sources = memo.all_sources()
        assert len(sources) == len(set(sources))


# ---------------------------------------------------------------------------
# plan_roles — fallback to all candidates on unparseable JSON
# ---------------------------------------------------------------------------

class TestPlanRoles:
    def _candidates(self) -> List[RoleSpec]:
        return [
            _spec("equity_analyst"),
            _spec("credit_analyst"),
            _spec("rates_analyst"),
        ]

    def test_valid_plan_returned(self, fake_llm, monkeypatch):
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
        plan_json = '{"plan": ["equity_analyst", "rates_analyst"], "reasoning": "macro focus"}'
        llm = fake_llm([openai_text(plan_json)])
        candidates = self._candidates()
        planner_spec = _spec("cio", "gpt-4o-mini")
        result = plan_roles("Buy AAPL?", candidates, planner_spec)
        assert result == ["equity_analyst", "rates_analyst"]

    def test_fallback_on_invalid_json(self, fake_llm, monkeypatch):
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
        llm = fake_llm([openai_text("not valid json at all")])
        candidates = self._candidates()
        planner_spec = _spec("cio", "gpt-4o-mini")
        result = plan_roles("Buy something?", candidates, planner_spec)
        # Fallback = all candidates
        assert result == [c.name for c in candidates]

    def test_fallback_filters_unknown_roles(self, fake_llm, monkeypatch):
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
        plan_json = '{"plan": ["equity_analyst", "unknown_role"], "reasoning": "ok"}'
        llm = fake_llm([openai_text(plan_json)])
        candidates = self._candidates()
        planner_spec = _spec("cio", "gpt-4o-mini")
        result = plan_roles("Q?", candidates, planner_spec)
        assert "unknown_role" not in result
        assert "equity_analyst" in result

    def test_fallback_on_empty_plan(self, fake_llm, monkeypatch):
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
        plan_json = '{"plan": [], "reasoning": "nothing relevant"}'
        llm = fake_llm([openai_text(plan_json)])
        candidates = self._candidates()
        planner_spec = _spec("cio", "gpt-4o-mini")
        result = plan_roles("Q?", candidates, planner_spec)
        # Empty plan → fallback to all
        assert result == [c.name for c in candidates]


# ---------------------------------------------------------------------------
# Agent resilience ladder
# ---------------------------------------------------------------------------

_ERROR_RESP = {"type": "error", "error": {"message": "tool_choice: Input should be an object"}}
_ERROR_RESP2 = {"type": "error", "error": {"message": "persistent error"}}


def _make_tool_registry():
    return ToolRegistry([
        Tool("get_data", "desc", {"type": "object", "properties": {}}, lambda: "42"),
    ])


class TestAgentResilience:
    def test_error_then_retry_without_tools_succeeds(self, fake_llm):
        """Error on a tools call → retry without tools → success parsed as view."""
        final = '{"stance":"BEARISH","conviction":3,"rationale":"retry ok","key_risks":[],"evidence":[]}'
        llm = fake_llm([
            _ERROR_RESP,       # first call (with tools) → error
            openai_text(final),  # retry without tools → success
        ])
        registry = _make_tool_registry()
        agent = Agent(_spec(), tools=registry, max_steps=4)
        view = agent.run("Q?")

        assert view.stance == "BEARISH"
        # Two calls made
        llm.assert_call_count(2)
        # Second call must have NO 'tools' key
        _, _, second_kwargs = llm.calls[1]
        assert "tools" not in second_kwargs or second_kwargs.get("tools") is None

    def test_persistent_error_returns_api_error_view(self, fake_llm):
        """Both calls error → view with key_risks starting with 'API error'."""
        llm = fake_llm([
            _ERROR_RESP,   # first call (with tools) → error
            _ERROR_RESP2,  # retry without tools → also error
        ])
        registry = _make_tool_registry()
        agent = Agent(_spec(), tools=registry, max_steps=4)
        view = agent.run("Q?")

        assert any(r.startswith("API error") for r in view.key_risks)

    def test_error_no_tools_returns_api_error_view(self, fake_llm):
        """Error with no tools → immediate fallback view (no retry)."""
        llm = fake_llm([_ERROR_RESP])
        agent = Agent(_spec(), tools=None, max_steps=4)
        view = agent.run("Q?")

        llm.assert_call_count(1)
        assert any(r.startswith("API error") for r in view.key_risks)

    def test_max_steps_exhausted_triggers_finalization(self, fake_llm):
        """max_steps exhausted while model still tool-calling → one finalization call."""
        final = '{"stance":"NEUTRAL","conviction":3,"rationale":"finalized","key_risks":[],"evidence":[]}'
        llm = fake_llm([
            openai_tool_call("get_data", {}),  # step 1 → tool call
            openai_tool_call("get_data", {}),  # step 2 → tool call (max_steps=2 exhausted)
            openai_text(final),               # finalization call
        ])
        registry = _make_tool_registry()
        agent = Agent(_spec(), tools=registry, max_steps=2)
        view = agent.run("Q?")

        llm.assert_call_count(3)
        # Finalization response parsed
        assert view.rationale == "finalized"

    def test_web_search_forwarded_to_client(self, fake_llm):
        """web_search=True on Agent is forwarded as kwarg to client.chat."""
        llm = fake_llm([openai_text('{"stance":"NEUTRAL","conviction":3,"rationale":"r","key_risks":[],"evidence":[]}')])
        agent = Agent(_spec(), tools=None, web_search=True, web_search_max_uses=2)
        agent.run("Q?")

        _, _, kwargs = llm.calls[0]
        assert kwargs.get("web_search") is True
        assert kwargs.get("max_uses") == 2

    def test_system_prompt_contains_today(self):
        """system_prompt includes today's date evaluated at call time."""
        agent = Agent(_spec())
        today = datetime.date.today().isoformat()
        assert today in agent.system_prompt

    def test_system_prompt_date_in_captured_call(self, fake_llm):
        """The system message sent to client.chat contains today's date."""
        llm = fake_llm([openai_text('{"stance":"NEUTRAL","conviction":3,"rationale":"r","key_risks":[]}')])
        agent = Agent(_spec())
        agent.run("Q?")

        _, messages, _ = llm.calls[0]
        today = datetime.date.today().isoformat()
        system_msgs = [m for m in messages if m.get("role") == "system"]
        assert system_msgs, "no system message found"
        assert today in system_msgs[0]["content"]

    def test_system_prompt_requires_unverified_labeling(self):
        """Stale-data guard: prompt demands labeling unverified figures."""
        agent = Agent(_spec())
        assert "unverified (training data)" in agent.system_prompt

    def test_json_mode_forwarded_to_client(self, fake_llm):
        """Agent.run always requests json_mode (GPT-only no-op handled in llm/)."""
        llm = fake_llm([openai_text('{"stance":"NEUTRAL","conviction":3,"rationale":"r","key_risks":[]}')])
        agent = Agent(_spec())
        agent.run("Q?")

        _, _, kwargs = llm.calls[0]
        assert kwargs.get("json_mode") is True


# ---------------------------------------------------------------------------
# Orchestrator web-search eligibility
# ---------------------------------------------------------------------------

class TestOrchestratorWebSearch:
    """Verify per-agent web_search flag based on model family and profile setting."""

    _CLEAN_VIEW = '{"stance":"BULLISH","conviction":4,"rationale":"ok","key_risks":[],"evidence":[]}'
    _SYNTH = '{"recommendation":"BUY","summary":"buy."}'

    def test_gpt_analyst_does_not_get_web_search(self, fake_llm, monkeypatch):
        """credit_analyst uses GPT in budget profile → web_search=False forwarded."""
        monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
        # simple=True → 3 analysts + 1 synthesis (no librarian/planner)
        llm = fake_llm([
            openai_text(self._CLEAN_VIEW),
            openai_text(self._CLEAN_VIEW),
            openai_text(self._CLEAN_VIEW),
            openai_text(self._SYNTH),
        ])
        run_committee("Q?", profile="budget", simple=True)

        for model, messages, kwargs in llm.calls:
            # simple=True passes no tools, so web_search should be False (default)
            # This verifies that even when simple=True, GPT models aren't getting web_search
            assert kwargs.get("web_search", False) is False

    def test_web_search_max_uses_zero_disables_for_everyone(self, fake_llm, monkeypatch):
        """If web_search_max_uses=0 in profile, no agent gets web_search=True."""
        from investment_firm.core.roster import load_firm

        # Patch load_firm to return a modified firm config with max_uses=0
        base_firm = load_firm()
        import copy
        patched = copy.deepcopy(base_firm)
        patched["profiles"]["budget"]["web_search_max_uses"] = 0
        monkeypatch.setattr(
            "investment_firm.core.orchestrator.profile_setting",
            lambda key, default=None, **kwargs: (
                0 if key == "web_search_max_uses" else
                base_firm["profiles"]["budget"].get(key, default)
            ),
        )
        llm = fake_llm([
            openai_text(self._CLEAN_VIEW),
            openai_text(self._CLEAN_VIEW),
            openai_text(self._CLEAN_VIEW),
            openai_text(self._SYNTH),
        ])
        run_committee("Q?", profile="budget", simple=True)

        for model, messages, kwargs in llm.calls:
            assert kwargs.get("web_search", False) is False


# ---------------------------------------------------------------------------
# runs.py API-error warning
# ---------------------------------------------------------------------------

class TestRunsWarnings:
    """_run_worker should emit warnings for API error risks."""

    def _make_view(self, role: str, key_risks: list) -> AnalystView:
        return AnalystView(
            role=role,
            model="gpt-4o-mini",
            stance="NEUTRAL",
            conviction=2,
            rationale="(no parseable response)",
            key_risks=key_risks,
        )

    def test_api_error_risk_produces_warning(self):
        """View with key_risk starting 'API error' → warning containing role and 'API error'."""
        # Simulate the warning-building logic from _run_worker
        from investment_firm.interfaces.web.runs import _FALLBACK_RISK

        view = self._make_view("equity_analyst", ["API error: boom"])
        warnings: list = []

        if _FALLBACK_RISK in view.key_risks or _FALLBACK_RISK in view.rationale:
            warnings.append(f"{view.role}: model did not return structured JSON")
        for risk in view.key_risks:
            if risk.startswith("API error"):
                warnings.append(f"{view.role}: API error — {risk}")

        assert len(warnings) == 1
        assert "equity_analyst" in warnings[0]
        assert "API error" in warnings[0]

    def test_fallback_risk_still_produces_warning(self):
        """Existing fallback risk check still works."""
        from investment_firm.interfaces.web.runs import _FALLBACK_RISK

        view = self._make_view("credit_analyst", [_FALLBACK_RISK])
        warnings: list = []

        if _FALLBACK_RISK in view.key_risks or _FALLBACK_RISK in view.rationale:
            warnings.append(f"{view.role}: model did not return structured JSON — rationale contains raw text fallback.")
        for risk in view.key_risks:
            if risk.startswith("API error"):
                warnings.append(f"{view.role}: API error — {risk}")

        assert any("model did not return structured JSON" in w for w in warnings)

    def test_no_warning_for_clean_view(self):
        """Clean view produces no warnings."""
        from investment_firm.interfaces.web.runs import _FALLBACK_RISK

        view = AnalystView(
            role="rates_analyst",
            model="gpt-4o-mini",
            stance="BULLISH",
            conviction=4,
            rationale="Strong rates outlook.",
            key_risks=["recession"],
        )
        warnings: list = []

        if _FALLBACK_RISK in view.key_risks or _FALLBACK_RISK in view.rationale:
            warnings.append(f"{view.role}: model did not return structured JSON")
        for risk in view.key_risks:
            if risk.startswith("API error"):
                warnings.append(f"{view.role}: API error — {risk}")

        assert warnings == []
