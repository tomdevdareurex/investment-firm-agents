"""Offline unit tests — no network, no tokens. These are the default suite."""
from __future__ import annotations

import httpx
import pytest

from investment_firm.llm import client, costs
from investment_firm.llm.utils import extract_text, extract_usage


# --- response parsing -----------------------------------------------------


def test_extract_text_openai_shape():
    resp = {"choices": [{"message": {"content": "hello"}}]}
    assert extract_text(resp) == "hello"


def test_extract_text_anthropic_shape():
    resp = {"content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}]}
    assert extract_text(resp) == "hi there"


def test_extract_text_error_nonstrict():
    resp = {"type": "error", "error": {"message": "boom"}}
    assert extract_text(resp, strict=False) == "[API error] boom"


def test_extract_usage_openai_and_anthropic():
    openai = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    anthropic = {"usage": {"input_tokens": 7, "output_tokens": 3}}
    assert extract_usage(openai) == (10, 5, 15)
    assert extract_usage(anthropic) == (7, 3, 10)


# --- chat payload construction (mocked transport) -------------------------


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

    def fake_post(self, url, headers=None, json=None):  # noqa: A002 - mirror httpx API
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setenv("AI_PLAYGROUND_API_KEY", "test-key")
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client.chat(**chat_kwargs)
    return captured["json"]


def test_chat_injects_max_tokens_for_claude(monkeypatch):
    payload = _capture(
        monkeypatch,
        model="claude-4.5-haiku",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert payload["max_tokens"] == 16000


def test_chat_omits_temperature_by_default(monkeypatch):
    payload = _capture(
        monkeypatch,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert "temperature" not in payload
    assert "max_tokens" not in payload  # not a Claude model, none requested


def test_web_search_auto_uses_tool_for_claude(monkeypatch):
    payload = _capture(
        monkeypatch,
        model="claude-4.6-sonnet",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="auto",
    )
    assert payload["tools"][0]["type"] == "web_search_20250305"
    assert "web_search" not in payload  # not the generic flag for Claude in auto mode


def test_web_search_auto_uses_generic_flag_for_gpt(monkeypatch):
    payload = _capture(
        monkeypatch,
        model="gpt-5.5",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="auto",
    )
    assert payload.get("web_search") is True
    assert "tools" not in payload


def test_web_search_generic_flag_for_claude(monkeypatch):
    payload = _capture(
        monkeypatch,
        model="claude-4.6-sonnet",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="generic",
    )
    assert payload.get("web_search") is True
    assert "tools" not in payload


# --- cost model -----------------------------------------------------------


def test_estimate_cost_scales_with_tokens_and_weight():
    cheap = costs.estimate_cost("gpt-4o-mini", 1000, 0)
    dear = costs.estimate_cost("claude-4.8-opus", 1000, 0)
    assert dear > cheap > 0


def test_run_tracker_summary_and_budget():
    tracker = costs.RunTracker(token_budget=100)
    tracker.record("equity_analyst", "gpt-4o-mini", 40, 10)
    assert tracker.total_tokens == 50
    assert tracker.would_exceed(60) is True
    assert tracker.would_exceed(40) is False
    assert "TOTAL" in tracker.render_summary()


# --- web-search capability (offline, using a provided models payload) ------

_MODELS_PAYLOAD = [
    {"name": "Claude 4.6 Sonnet", "model": "claude-4.6-sonnet", "webSearch": True},
    {"name": "Gemini 2.5 Flash", "model": "gemini-2.5-flash", "webSearch": True},
    {"name": "GPT-5.5", "model": "gpt-5.5", "webSearch": False},
    {"name": "o4-mini", "model": "o4-mini", "webSearch": False},
]


def test_supports_websearch_reads_capability_flag():
    assert client.supports_websearch("gemini-2.5-flash", models=_MODELS_PAYLOAD) is True
    assert client.supports_websearch("claude-4.6-sonnet", models=_MODELS_PAYLOAD) is True
    assert client.supports_websearch("gpt-5.5", models=_MODELS_PAYLOAD) is False
    assert client.supports_websearch("o4-mini", models=_MODELS_PAYLOAD) is False


def test_supports_websearch_unknown_model_returns_none():
    assert client.supports_websearch("does-not-exist", models=_MODELS_PAYLOAD) is None


def test_supports_websearch_accepts_data_envelope():
    payload = {"data": _MODELS_PAYLOAD}
    assert client.supports_websearch("gpt-5.5", models=payload) is False


def test_model_capabilities_returns_full_entry():
    entry = client.model_capabilities("gpt-5.5", models=_MODELS_PAYLOAD)
    assert entry is not None and entry["model"] == "gpt-5.5"
    assert client.model_capabilities("nope", models=_MODELS_PAYLOAD) is None

