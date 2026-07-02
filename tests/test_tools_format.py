"""Tests for Anthropic tool-format conversion, web-search merging, and utils parsing.

All offline — no network calls. Client-level tests monkeypatch the HTTP transport
(same pattern as test_client_offline.py); utils/agent tests use FakeLLM.
"""
from __future__ import annotations

import datetime
import json

import httpx
import pytest

from investment_firm.llm import client
from investment_firm.llm.utils import (
    assistant_message,
    extract_tool_calls,
)

from conftest import anthropic_text, openai_text, openai_tool_call


# ---------------------------------------------------------------------------
# HTTP-capture helper (mirrors test_client_offline._capture)
# ---------------------------------------------------------------------------

class _FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


def _capture(monkeypatch, **chat_kwargs):
    captured: dict = {}

    def fake_post(self, url, headers=None, json=None):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client.chat(**chat_kwargs)
    return captured["json"]


# ---------------------------------------------------------------------------
# A. Claude payload — tool schema conversion
# ---------------------------------------------------------------------------

class TestClaudeToolConversion:
    """OpenAI tools → Anthropic format for Claude models."""

    _OPENAI_TOOL = {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Fetch a price",
            "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}},
        },
    }

    def test_tools_converted_to_input_schema(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="auto",
        )
        tools = payload["tools"]
        assert len(tools) == 1
        t = tools[0]
        # Anthropic shape: no "type"/"function" wrapper
        assert "input_schema" in t
        assert t["name"] == "get_price"
        assert t["description"] == "Fetch a price"
        assert "type" not in t or t.get("type") != "function"

    def test_tool_choice_auto_becomes_object(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="auto",
        )
        assert payload["tool_choice"] == {"type": "auto"}

    def test_tool_choice_required_becomes_any(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="required",
        )
        assert payload["tool_choice"] == {"type": "any"}

    def test_tool_choice_none_is_omitted(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="none",
        )
        assert "tool_choice" not in payload

    def test_tool_choice_dict_passes_through(self, monkeypatch):
        choice = {"type": "tool", "name": "get_price"}
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice=choice,
        )
        assert payload["tool_choice"] == choice

    def test_already_anthropic_tool_passes_through(self, monkeypatch):
        """Tools already in Anthropic format (have input_schema) are not double-converted."""
        anthropic_tool = {
            "name": "get_price",
            "description": "Fetch a price",
            "input_schema": {"type": "object", "properties": {}},
        }
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=[{"role": "user", "content": "hi"}],
            tools=[anthropic_tool],
            tool_choice="auto",
        )
        tools = payload["tools"]
        assert tools[0]["name"] == "get_price"
        assert "input_schema" in tools[0]


# ---------------------------------------------------------------------------
# A. Claude payload — message history conversion
# ---------------------------------------------------------------------------

class TestClaudeMessageConversion:
    """tool-role messages and assistant tool_calls → Anthropic format."""

    def test_tool_message_becomes_user_tool_result(self, monkeypatch):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "result_data"},
        ]
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=msgs,
        )
        # Find the converted user message with tool_result block
        user_msgs = [m for m in payload["messages"] if m["role"] == "user"]
        tool_result_msgs = [
            m for m in user_msgs
            if isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
        ]
        assert len(tool_result_msgs) == 1
        block = tool_result_msgs[0]["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "c1"
        assert block["content"] == "result_data"

    def test_two_consecutive_tool_messages_merged_into_one_user_turn(self, monkeypatch):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
        ]
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=msgs,
        )
        # Both tool messages must collapse into exactly ONE user turn
        user_tool_msgs = [
            m for m in payload["messages"]
            if m["role"] == "user"
            and isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
        ]
        assert len(user_tool_msgs) == 1
        assert len(user_tool_msgs[0]["content"]) == 2

    def test_assistant_with_tool_calls_converted_to_tool_use_blocks(self, monkeypatch):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "get_data", "arguments": '{"x": 1}'}}
            ]},
        ]
        payload = _capture(
            monkeypatch,
            model="claude-4.5-haiku",
            messages=msgs,
        )
        asst_msgs = [m for m in payload["messages"] if m["role"] == "assistant"]
        assert asst_msgs, "no assistant message in payload"
        content = asst_msgs[0]["content"]
        assert isinstance(content, list)
        tool_use = [b for b in content if b.get("type") == "tool_use"]
        assert len(tool_use) == 1
        assert tool_use[0]["name"] == "get_data"
        assert tool_use[0]["input"] == {"x": 1}


# ---------------------------------------------------------------------------
# A. Claude payload — tools + web_search coexistence
# ---------------------------------------------------------------------------

class TestClaudeWebSearchPlusTools:
    """Web search tool appended (not replacing) function tools for Claude."""

    _OPENAI_TOOL = {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Fetch a price",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    def test_claude_tools_and_web_search_both_present(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="claude-4.6-sonnet",
            messages=[{"role": "user", "content": "search and call tool"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="auto",
            web_search=True,
            web_search_mode="auto",
        )
        tools = payload["tools"]
        names = [t.get("name") for t in tools]
        # The converted function tool must be present
        assert "get_price" in names
        # The web search tool must also be present
        assert "web_search" in names
        ws = next(t for t in tools if t.get("name") == "web_search")
        assert ws["type"] == "web_search_20250305"

    def test_gpt_web_search_uses_web_search_options_not_tools(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="gpt-5.5",
            messages=[{"role": "user", "content": "search"}],
            web_search=True,
            web_search_mode="auto",
        )
        # Confirmed 2026-07-02: web_search_options grounds; bare flag does not.
        assert payload.get("web_search_options") == {}
        assert "web_search" not in payload
        assert "tools" not in payload

    def test_gemini_web_search_options_coexists_with_tools(self, monkeypatch):
        """Gemini: web_search_options set, tools list preserved (OpenAI pass-through)."""
        tool = {"type": "function", "function": {"name": "foo", "description": "d",
                                                   "parameters": {}}}
        payload = _capture(
            monkeypatch,
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "q"}],
            tools=[tool],
            tool_choice="auto",
            web_search=True,
            web_search_mode="auto",
        )
        assert payload.get("web_search_options") == {}
        assert "web_search" not in payload
        # Function tool still present (OpenAI pass-through)
        assert "tools" in payload
        assert payload["tools"][0]["function"]["name"] == "foo"


# ---------------------------------------------------------------------------
# A. GPT/Gemini payloads unchanged
# ---------------------------------------------------------------------------

class TestNonClaudePayloads:
    """GPT and Gemini receive OpenAI-format tools and tool_choice unchanged."""

    _OPENAI_TOOL = {
        "type": "function",
        "function": {"name": "foo", "description": "desc", "parameters": {}},
    }

    def test_gpt_tools_unchanged(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="auto",
        )
        assert payload["tools"][0]["type"] == "function"
        assert payload["tool_choice"] == "auto"

    def test_gemini_tools_unchanged(self, monkeypatch):
        payload = _capture(
            monkeypatch,
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "hi"}],
            tools=[self._OPENAI_TOOL],
            tool_choice="required",
        )
        assert payload["tools"][0]["type"] == "function"
        assert payload["tool_choice"] == "required"


# ---------------------------------------------------------------------------
# Utils: extract_tool_calls — Anthropic tool_use blocks
# ---------------------------------------------------------------------------

class TestExtractToolCallsAnthropic:
    """extract_tool_calls normalises Anthropic tool_use blocks to OpenAI style."""

    def _anthropic_resp(self, blocks):
        return {"content": blocks, "stop_reason": "tool_use"}

    def test_single_tool_use_normalised(self):
        resp = self._anthropic_resp([
            {"type": "tool_use", "id": "tu_1", "name": "get_price",
             "input": {"ticker": "AAPL"}},
        ])
        calls = extract_tool_calls(resp)
        assert len(calls) == 1
        c = calls[0]
        assert c["id"] == "tu_1"
        assert c["type"] == "function"
        assert c["function"]["name"] == "get_price"
        # arguments must be a JSON string
        parsed = json.loads(c["function"]["arguments"])
        assert parsed == {"ticker": "AAPL"}

    def test_multiple_tool_use_blocks(self):
        resp = self._anthropic_resp([
            {"type": "tool_use", "id": "tu_1", "name": "a", "input": {}},
            {"type": "text", "text": "some text"},
            {"type": "tool_use", "id": "tu_2", "name": "b", "input": {"k": "v"}},
        ])
        calls = extract_tool_calls(resp)
        assert len(calls) == 2
        names = [c["function"]["name"] for c in calls]
        assert "a" in names and "b" in names

    def test_no_tool_use_returns_empty(self):
        resp = self._anthropic_resp([{"type": "text", "text": "hello"}])
        assert extract_tool_calls(resp) == []

    def test_openai_shape_still_works(self):
        resp = openai_tool_call("foo", {"x": 1})
        calls = extract_tool_calls(resp)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "foo"


# ---------------------------------------------------------------------------
# Utils: assistant_message — Anthropic shape
# ---------------------------------------------------------------------------

class TestAssistantMessageAnthropic:
    """assistant_message returns raw content list for Anthropic responses."""

    def test_anthropic_text_response(self):
        resp = anthropic_text("hello")
        msg = assistant_message(resp)
        assert msg is not None
        assert msg["role"] == "assistant"
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["text"] == "hello"

    def test_anthropic_tool_use_response(self):
        resp = {
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "get_data", "input": {}},
            ],
            "stop_reason": "tool_use",
        }
        msg = assistant_message(resp)
        assert msg is not None
        assert msg["role"] == "assistant"
        assert msg["content"][0]["type"] == "tool_use"

    def test_openai_shape_still_works(self):
        resp = openai_text("hello")
        msg = assistant_message(resp)
        assert msg is not None
        assert msg["content"] == "hello"

    def test_none_for_unrecognised(self):
        assert assistant_message({"foo": "bar"}) is None
