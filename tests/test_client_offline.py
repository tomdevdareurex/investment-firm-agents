"""Offline unit tests — no network, no tokens. These are the default suite."""

from __future__ import annotations

import httpx
import pytest

from investment_firm.llm import client, costs
from investment_firm.llm.utils import (
    extract_text,
    extract_usage,
    extract_tool_calls,
    assistant_message,
    is_error,
    is_completion_error,
    get_error_message,
)

# --- response parsing -----------------------------------------------------


def test_extract_text_openai_shape():
    resp = {"choices": [{"message": {"content": "hello"}}]}
    assert extract_text(resp) == "hello"


def test_extract_text_anthropic_shape():
    resp = {
        "content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}]
    }
    assert extract_text(resp) == "hi there"


def test_extract_text_error_nonstrict():
    resp = {"type": "error", "error": {"message": "boom"}}
    assert extract_text(resp, strict=False) == "[API error] boom"


def test_extract_usage_openai_and_anthropic():
    openai = {
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    anthropic = {"usage": {"input_tokens": 7, "output_tokens": 3}}
    assert extract_usage(openai) == (10, 5, 15)
    assert extract_usage(anthropic) == (7, 3, 10)


# --- non-dict response hardening ------------------------------------------


def test_is_error_returns_true_for_list():
    assert is_error([]) is True
    assert is_error(["some", "list"]) is True


def test_is_error_returns_true_for_string():
    assert is_error("unexpected string") is True


def test_is_error_returns_true_for_none():
    assert is_error(None) is True


def test_get_error_message_for_list():
    msg = get_error_message([{"choices": []}])
    assert "list" in msg


def test_get_error_message_for_string():
    msg = get_error_message("oops")
    assert "str" in msg


def test_extract_text_list_nonstrict():
    result = extract_text([], strict=False)
    assert "[API error]" in result
    assert "list" in result


def test_extract_text_string_nonstrict():
    result = extract_text("hello", strict=False)
    assert "[API error]" in result


def test_extract_text_list_strict_raises():
    from investment_firm.llm.utils import PlaygroundError

    with pytest.raises(PlaygroundError):
        extract_text([], strict=True)


def test_extract_tool_calls_list_returns_empty():
    assert extract_tool_calls([]) == []
    assert extract_tool_calls("string") == []
    assert extract_tool_calls(None) == []


def test_assistant_message_list_returns_none():
    assert assistant_message([]) is None
    assert assistant_message("string") is None


def test_extract_usage_list_returns_zeros():
    assert extract_usage([]) == (0, 0, 0)
    assert extract_usage(None) == (0, 0, 0)


# --- gateway error-shape hardening -----------------------------------------


def test_is_error_detects_string_error_value():
    assert is_error({"error": "quota exceeded"}) is True


def test_is_error_still_detects_dict_error_value():
    assert is_error({"error": {"message": "boom"}}) is True


def test_is_error_false_for_valid_completion_shapes():
    assert is_error({"choices": [{"message": {"content": "ok"}}]}) is False
    assert is_error({"content": [{"type": "text", "text": "ok"}]}) is False


def test_is_error_false_for_non_completion_endpoints():
    # /ai/models and token-usage payloads must NOT be flagged by is_error
    assert is_error({"data": [{"id": "gpt"}]}) is False
    assert is_error({"used": 5, "total": 10}) is False


def test_is_completion_error_flags_detail_only_body():
    assert is_completion_error({"detail": "Not authenticated"}) is True


def test_is_completion_error_flags_message_only_body():
    assert is_completion_error({"message": "rate limited"}) is True


def test_is_completion_error_false_for_valid_completions():
    assert is_completion_error({"choices": [{"message": {"content": "ok"}}]}) is False
    assert is_completion_error({"content": [{"type": "text", "text": "ok"}]}) is False


def test_get_error_message_string_error():
    assert get_error_message({"error": "quota exceeded"}) == "quota exceeded"


def test_get_error_message_detail_only():
    assert get_error_message({"detail": "Not authenticated"}) == "Not authenticated"


def test_get_error_message_message_only():
    assert get_error_message({"message": "rate limited"}) == "rate limited"


def test_get_error_message_no_payload_lists_keys():
    msg = get_error_message({"foo": 1, "bar": 2})
    assert "no completion payload" in msg
    assert "bar" in msg and "foo" in msg


def test_get_error_message_none_for_valid_completion():
    assert get_error_message({"choices": [{"message": {"content": "ok"}}]}) is None


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


def test_web_search_auto_uses_web_search_options_for_gpt(monkeypatch):
    """Generic path: non-Claude models get web_search_options={}, not web_search=True."""
    payload = _capture(
        monkeypatch,
        model="gpt-5.5",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="auto",
    )
    assert payload.get("web_search_options") == {}
    assert "web_search" not in payload
    assert "tools" not in payload


def test_web_search_generic_flag_for_claude(monkeypatch):
    """mode=generic forces web_search_options={} even for Claude."""
    payload = _capture(
        monkeypatch,
        model="claude-4.6-sonnet",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="generic",
    )
    assert payload.get("web_search_options") == {}
    assert "web_search" not in payload
    assert "tools" not in payload


def test_web_search_gemini_uses_web_search_options(monkeypatch):
    """Gemini gets web_search_options={} (confirmed grounding 2026-07-02)."""
    payload = _capture(
        monkeypatch,
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "ECB rate?"}],
        web_search=True,
        web_search_mode="auto",
    )
    assert payload.get("web_search_options") == {}
    assert "web_search" not in payload


def test_web_search_env_override_custom_flag(monkeypatch):
    """IFA_WEBSEARCH_FLAG override: a non-default flag key uses True (escape hatch)."""
    monkeypatch.setenv("IFA_WEBSEARCH_FLAG", "my_custom_flag")
    payload = _capture(
        monkeypatch,
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="auto",
    )
    assert payload.get("my_custom_flag") is True
    assert "web_search_options" not in payload
    assert "web_search" not in payload


def test_web_search_options_coexists_with_function_tools(monkeypatch):
    """web_search_options and OpenAI-format function tools can coexist on Gemini."""
    from investment_firm.core.tools.base import Tool, ToolRegistry

    dummy_tool = Tool(
        name="dummy",
        description="A dummy tool",
        parameters={"type": "object", "properties": {}, "required": []},
        func=lambda: {},
    )
    registry = ToolRegistry([dummy_tool])
    schemas = registry.schemas()  # OpenAI format

    payload = _capture(
        monkeypatch,
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "news?"}],
        web_search=True,
        web_search_mode="auto",
        tools=schemas,
    )
    # web_search_options present
    assert payload.get("web_search_options") == {}
    # function tools still present (not overwritten)
    assert isinstance(payload.get("tools"), list)
    assert any(
        t.get("function", {}).get("name") == "dummy"
        for t in payload["tools"]
        if isinstance(t, dict)
    )


def test_json_mode_sets_response_format_for_gpt(monkeypatch):
    """json_mode=True on a GPT model adds OpenAI JSON mode to the payload."""
    payload = _capture(
        monkeypatch,
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Answer in JSON."}],
        json_mode=True,
    )
    assert payload.get("response_format") == {"type": "json_object"}


def test_json_mode_is_noop_for_claude_and_gemini(monkeypatch):
    """json_mode must not add response_format for non-GPT families."""
    for model in ("claude-4.5-haiku", "gemini-2.5-flash"):
        payload = _capture(
            monkeypatch,
            model=model,
            messages=[{"role": "user", "content": "Answer in JSON."}],
            json_mode=True,
        )
        assert "response_format" not in payload, model


def test_json_mode_off_by_default(monkeypatch):
    payload = _capture(
        monkeypatch,
        model="gpt-4.1",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert "response_format" not in payload


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
    assert (
        client.supports_websearch("claude-4.6-sonnet", models=_MODELS_PAYLOAD) is True
    )
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
