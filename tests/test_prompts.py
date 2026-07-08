"""Prompt library (core/prompts/) — offline string assertions.

Verifies: the frozen JSON contract is on EVERY role's system prompt, role
bodies are selected correctly, parameterized departments share one template,
the role → department → generic fallback chain, debate-prompt frozen bits,
the bull/bear model pins, and the lean-roster optional flags.
"""

from __future__ import annotations

import datetime

import pytest

from investment_firm.core.orchestrator import CANDIDATE_ANALYSTS, OPTIONAL_ANALYSTS
from investment_firm.core.planner import plan_roles
from investment_firm.core.prompts import (
    BULL_SYSTEM,
    BEAR_SYSTEM,
    DEPARTMENT_BODIES,
    JUDGE_SYSTEM,
    ROLE_BODIES,
    system_prompt_for,
)
from investment_firm.core.prompts.debate import BEAR_LABEL, BULL_LABEL
from investment_firm.core.roster import RoleSpec, load_firm, resolve_roles

from conftest import openai_text

_FIRM = load_firm()
_ALL_ROLE_NAMES = list(_FIRM["roles"].keys())
_ALL_SPECS = resolve_roles(_ALL_ROLE_NAMES, profile="balanced")


def test_every_role_prompt_carries_frozen_contract():
    today = datetime.date.today().isoformat()
    for name, spec in _ALL_SPECS.items():
        prompt = system_prompt_for(spec)
        assert '"stance": "BULLISH|BEARISH|NEUTRAL"' in prompt, name
        assert '"conviction"' in prompt, name
        assert '"key_risks"' in prompt, name
        assert '"evidence"' in prompt, name
        assert "decision-support" in prompt, name
        assert today in prompt, name
        assert "unverified (training data)" in prompt, name


def test_role_specific_bodies_selected():
    technical = system_prompt_for(_ALL_SPECS["technical_analyst"])
    assert "get_indicators" in technical
    assert "RSI" in technical

    sentiment = system_prompt_for(_ALL_SPECS["sentiment_analyst"])
    assert "get_stocktwits_sentiment" in sentiment

    news = system_prompt_for(_ALL_SPECS["news_analyst"])
    assert "web search" in news

    market_risk = system_prompt_for(_ALL_SPECS["market_risk"])
    assert "compute_risk_metrics" in market_risk

    librarian = system_prompt_for(_ALL_SPECS["research_librarian"])
    assert "data_gaps" in librarian
    assert "source" in librarian


def test_economists_share_parameterized_prompt():
    from investment_firm.core.prompts.economists import HORIZONS

    stripped = {}
    for name, params in HORIZONS.items():
        body = ROLE_BODIES[name]
        assert params["horizon_label"] in body, name
        for value in params.values():
            body = body.replace(value, "")
        stripped[name] = body
    assert len(set(stripped.values())) == 1


def test_desks_share_parameterized_prompt():
    from investment_firm.core.prompts.trading import DESKS

    stripped = {}
    for name, params in DESKS.items():
        body = ROLE_BODIES[name]
        assert params["asset_class"] in body, name
        for value in params.values():
            body = body.replace(value, "")
        stripped[name] = body
    assert len(set(stripped.values())) == 1


def test_fallback_chain():
    dept_spec = RoleSpec(
        name="unknown_role",
        group="risk",
        tier="WORKER",
        model="gpt-4o-mini",
        mandate="Some risk mandate.",
    )
    assert DEPARTMENT_BODIES["risk"] in system_prompt_for(dept_spec)

    generic_spec = RoleSpec(
        name="unknown_role",
        group="nonexistent",
        tier="WORKER",
        model="gpt-4o-mini",
        mandate="A very specific mandate sentence.",
    )
    assert "A very specific mandate sentence." in system_prompt_for(generic_spec)


def test_debate_prompts_frozen_bits():
    assert BULL_LABEL == "Senior Research Bull"
    assert BEAR_LABEL == "Senior Research Bear"
    assert "Senior Research Bull" in BULL_SYSTEM
    assert "[equity_analyst]" in BULL_SYSTEM
    assert "Senior Research Bear" in BEAR_SYSTEM
    assert "[equity_analyst]" in BEAR_SYSTEM
    for tmpl in (BULL_SYSTEM, BEAR_SYSTEM):
        formatted = tmpl.format(date="2026-01-01")
        assert "2026-01-01" in formatted
        assert "unverified (training data)" in formatted
        assert "2-4 tight paragraphs" in formatted

    judge = JUDGE_SYSTEM.format(date="2026-01-01")
    assert "2026-01-01" in judge
    assert '"stance"' in judge
    assert '"summary"' in judge


@pytest.mark.parametrize("profile", ["budget", "balanced", "premium"])
def test_bull_bear_model_pins(profile):
    specs = resolve_roles(["bull_researcher", "bear_researcher"], profile=profile)
    assert specs["bull_researcher"].model == "gpt-5.5"
    assert specs["bear_researcher"].model == "claude-4.8-opus"


def test_optional_flags():
    for name in OPTIONAL_ANALYSTS:
        assert _ALL_SPECS[name].optional, name
    for name in CANDIDATE_ANALYSTS:
        assert not _ALL_SPECS[name].optional, name
    for name in (
        "ic_chair",
        "pm",
        "compliance",
        "devils_advocate",
        "rates_desk",
        "equity_desk",
        "swaps_desk",
        "fx_desk",
    ):
        assert _ALL_SPECS[name].optional, name


def test_planner_fallback_excludes_optional(fake_llm, monkeypatch):
    monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
    fake_llm([openai_text("not valid json at all")])
    candidates = [
        RoleSpec(
            name="equity_analyst",
            group="research",
            tier="WORKER",
            model="gpt-4o-mini",
            mandate="Core.",
        ),
        RoleSpec(
            name="quant",
            group="quant",
            tier="SENIOR",
            model="gpt-4o-mini",
            mandate="Optional.",
            optional=True,
        ),
    ]
    planner_spec = RoleSpec(
        name="cio",
        group="governance",
        tier="HEAD",
        model="gpt-4o-mini",
        mandate="Plan.",
    )
    result = plan_roles("Q?", candidates, planner_spec)
    assert result == ["equity_analyst"]
