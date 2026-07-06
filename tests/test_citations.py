"""Offline tests for memo-trust hardening: citations, grounding, freshness.

Covers: extract_citations (both gateway shapes), the agent freshness gate
(grounded flag + UNVERIFIED/DATA GAP key_risks), key_risks cleanup, staleness
notes, and the librarian web-capable-model guard. No network, no tokens.
"""

from __future__ import annotations

import datetime
import json

from investment_firm.core.agent import (
    Agent,
    _clean_str_list,
    _salvage_fields,
    _staleness_note,
)
from investment_firm.core.roster import RoleSpec
from investment_firm.core.schemas import Source
from investment_firm.core.tools.base import Tool, ToolError, ToolRegistry
from investment_firm.llm.utils import extract_citations, has_web_evidence

from conftest import openai_text, openai_tool_call


def _spec(name: str = "equity_analyst", model: str = "claude-4.5-haiku") -> RoleSpec:
    return RoleSpec(
        name=name, group="research", tier="WORKER", model=model, mandate="Test mandate."
    )


_CLEAN_VIEW = json.dumps(
    {
        "stance": "BULLISH",
        "conviction": 4,
        "rationale": "ok",
        "key_risks": ["recession"],
        "evidence": ["tool: +5%"],
    }
)


# ---------------------------------------------------------------------------
# extract_citations — both gateway shapes
# ---------------------------------------------------------------------------


class TestExtractCitations:
    def test_gemini_openai_annotations(self):
        """Gemini grounding arrives as OpenAI url_citation annotations."""
        resp = {
            "choices": [
                {
                    "message": {
                        "content": "text",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": "https://example.com/a",
                                    "title": "example.com",
                                },
                            },
                            {
                                "type": "other",
                                "url_citation": {"url": "https://skip.me"},
                            },
                        ],
                    }
                }
            ]
        }
        cites = extract_citations(resp)
        assert cites == [
            {
                "url": "https://example.com/a",
                "title": "example.com",
                "origin": "web:gemini",
            }
        ]
        assert has_web_evidence(resp)

    def test_claude_web_search_tool_result_blocks(self):
        resp = {
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {
                            "type": "web_search_result",
                            "url": "https://news.example/x",
                            "title": "News X",
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "answer",
                    "citations": [{"url": "https://cite.example/y", "title": "Cite Y"}],
                },
            ]
        }
        cites = extract_citations(resp)
        urls = [c["url"] for c in cites]
        assert urls == ["https://news.example/x", "https://cite.example/y"]
        assert all(c["origin"] == "web:claude" for c in cites)

    def test_dedup_by_url(self):
        resp = {
            "content": [
                {
                    "type": "text",
                    "text": "a",
                    "citations": [
                        {"url": "https://same.example", "title": "1"},
                        {"url": "https://same.example", "title": "2"},
                    ],
                },
            ]
        }
        assert len(extract_citations(resp)) == 1

    def test_non_dict_safe(self):
        assert extract_citations(None) == []
        assert extract_citations(["x"]) == []
        assert extract_citations("text") == []
        assert not has_web_evidence(None)


# ---------------------------------------------------------------------------
# key_risks cleanup — the mangled-JSON render bug
# ---------------------------------------------------------------------------


class TestCleanStrList:
    def test_stringified_array_parsed(self):
        assert _clean_str_list('["risk a", "risk b"]') == ["risk a", "risk b"]

    def test_plain_string_kept_whole(self):
        assert _clean_str_list("single risk") == ["single risk"]

    def test_structural_fragments_dropped(self):
        assert _clean_str_list([": [", ",", "],", "real risk", ""]) == ["real risk"]

    def test_dict_items_dropped(self):
        assert _clean_str_list([{"nested": "x"}, "kept"]) == ["kept"]

    def test_non_list_non_str_empty(self):
        assert _clean_str_list({"a": 1}) == []
        assert _clean_str_list(None) == []

    def test_salvage_key_risks_bounded_to_bracket(self):
        """Salvage must not capture quoted strings after the key_risks array."""
        text = (
            '{"stance": "BEARISH", "rationale": "r", '
            '"key_risks": ["a", "b"], "evidence": ["leak1", "leak2"]'
        )
        result = _salvage_fields(text)
        assert result is not None
        assert result["key_risks"] == ["a", "b"]


# ---------------------------------------------------------------------------
# Freshness gate — grounded flag + UNVERIFIED / DATA GAP risks
# ---------------------------------------------------------------------------


class TestFreshnessGate:
    def _tool(self, func) -> ToolRegistry:
        return ToolRegistry(
            [
                Tool("get_data", "d", {"type": "object", "properties": {}}, func),
            ]
        )

    def test_text_only_run_is_ungrounded(self, fake_llm):
        fake_llm([openai_text(_CLEAN_VIEW)])
        agent = Agent(_spec(), tools=None)
        view = agent.run("Q?")
        assert view.grounded is False
        assert any(r.startswith("UNVERIFIED") for r in view.key_risks)

    def test_successful_tool_call_grounds_view(self, fake_llm):
        fake_llm(
            [
                openai_tool_call("get_data", {}),
                openai_text(_CLEAN_VIEW),
            ]
        )
        agent = Agent(_spec(), tools=self._tool(lambda: {"value": 1}))
        view = agent.run("Q?")
        assert view.grounded is True
        assert not any(r.startswith("UNVERIFIED") for r in view.key_risks)

    def test_tool_error_produces_data_gap(self, fake_llm):
        def _boom():
            raise ToolError("yfinance not installed")

        fake_llm(
            [
                openai_tool_call("get_data", {}),
                openai_text(_CLEAN_VIEW),
            ]
        )
        agent = Agent(_spec(), tools=self._tool(_boom))
        view = agent.run("Q?")
        assert view.grounded is False
        assert any(r.startswith("DATA GAP: get_data") for r in view.key_risks)
        assert any(n.startswith("DATA GAP: get_data") for n in agent.memory.notes)

    def test_web_citations_ground_view_without_tools(self, fake_llm):
        resp = openai_text(_CLEAN_VIEW)
        resp["choices"][0]["message"]["annotations"] = [
            {
                "type": "url_citation",
                "url_citation": {"url": "https://example.com", "title": "t"},
            },
        ]
        fake_llm([resp])
        agent = Agent(_spec(), tools=None)
        view = agent.run("Q?")
        assert view.grounded is True
        assert view.citations and view.citations[0].url == "https://example.com"
        assert view.citations[0].origin == "web:gemini"


# ---------------------------------------------------------------------------
# Staleness notes
# ---------------------------------------------------------------------------


class TestStaleness:
    def test_old_as_of_flagged(self):
        old = (datetime.date.today() - datetime.timedelta(days=300)).isoformat()
        note = _staleness_note("get_prices", {"as_of": old})
        assert note is not None and "stale as_of=" in note

    def test_fresh_as_of_not_flagged(self):
        today = datetime.date.today().isoformat()
        assert _staleness_note("get_prices", {"as_of": today}) is None

    def test_unknown_tool_not_flagged(self):
        assert _staleness_note("unknown_tool", {"as_of": "2000-01-01"}) is None

    def test_stale_note_recorded_in_memory(self, fake_llm):
        old = (datetime.date.today() - datetime.timedelta(days=300)).isoformat()
        fake_llm(
            [
                openai_tool_call("get_prices", {}),
                openai_text(_CLEAN_VIEW),
            ]
        )
        registry = ToolRegistry(
            [
                Tool(
                    "get_prices",
                    "d",
                    {"type": "object", "properties": {}},
                    lambda: {"as_of": old, "price": 100.0},
                ),
            ]
        )
        agent = Agent(_spec(), tools=registry)
        agent.run("Q?")
        assert any("stale as_of=" in n for n in agent.memory.notes)


# ---------------------------------------------------------------------------
# Librarian guard — must never run on a model without web search
# ---------------------------------------------------------------------------


class TestLibrarianGuard:
    def test_gpt_librarian_overridden(self, fake_llm, monkeypatch):
        from investment_firm.core import orchestrator
        from investment_firm.llm.costs import RunTracker

        gpt_spec = _spec(name="research_librarian", model="gpt-4.1")
        monkeypatch.setattr(orchestrator, "_resolve", lambda role, prof: gpt_spec)
        llm = fake_llm([openai_text(_CLEAN_VIEW)])

        orchestrator._build_briefing("Q?", "balanced", RunTracker())
        model, _, _ = llm.calls[0]
        assert model.startswith(("claude", "gemini"))

    def test_web_capable_worker_model_balanced(self):
        from investment_firm.core.orchestrator import _web_capable_worker_model

        model = _web_capable_worker_model("balanced")
        assert model is not None
        assert model.startswith(("claude", "gemini"))


# ---------------------------------------------------------------------------
# Source schema
# ---------------------------------------------------------------------------


class TestSourceSchema:
    def test_label_with_title(self):
        s = Source(url="https://x.example", title="X")
        assert s.label() == "X — https://x.example"

    def test_label_without_title(self):
        assert Source(url="https://x.example").label() == "https://x.example"
