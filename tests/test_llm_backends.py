"""Offline tests for LLM backend selection, mapping, capabilities, and the
Databricks adapter (SDK fully mocked — no network, no tokens, no Databricks)."""

from __future__ import annotations

import sys

import pytest

from investment_firm.llm import backends, client, databricks_backend, sanitize


@pytest.fixture(autouse=True)
def _clean_backend_state(monkeypatch):
    monkeypatch.delenv("IFA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("IFA_DBX_MODEL_MAP", raising=False)
    monkeypatch.delenv("IFA_DBX_DEFAULT_MODEL", raising=False)
    # Never let the adapter reach the network in offline tests.
    monkeypatch.setattr(databricks_backend, "_available_endpoints", lambda: None)
    backends.reset_backend()
    yield
    backends.reset_backend()


# --- backend selection ------------------------------------------------------


def test_default_backend_is_playground():
    assert backends.current_backend() == backends.PLAYGROUND


def test_env_selects_databricks(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "databricks")
    assert backends.current_backend() == backends.DATABRICKS


def test_env_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "Databricks")
    assert backends.current_backend() == backends.DATABRICKS


def test_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "bedrock")
    with pytest.raises(backends.BackendError):
        backends.current_backend()


def test_set_backend_overrides_env(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "playground")
    backends.set_backend("databricks")
    assert backends.current_backend() == backends.DATABRICKS
    backends.reset_backend()
    assert backends.current_backend() == backends.PLAYGROUND


def test_set_backend_invalid_raises():
    with pytest.raises(backends.BackendError):
        backends.set_backend("nope")
    assert backends.current_backend() == backends.PLAYGROUND  # unchanged


# --- capabilities -----------------------------------------------------------


def test_playground_web_search_by_family():
    assert backends.supports_web_search("claude-4.6-sonnet") is True
    assert backends.supports_web_search("gemini-2.5-flash") is True
    assert backends.supports_web_search("gpt-4.1") is False
    assert backends.supports_web_search("o4-mini") is False


def test_databricks_never_supports_web_search(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "databricks")
    assert backends.supports_web_search("claude-4.6-sonnet") is False
    assert backends.supports_web_search("databricks-claude-opus-4-6") is False


def test_supports_tools_on_both_backends():
    assert backends.supports_tools("gpt-4.1", backend="playground") is True
    assert backends.supports_tools("claude-4.5-haiku", backend="databricks") is True


def test_client_capability_shim_is_backend_aware(monkeypatch):
    assert client.supports_web_search_for("claude-4.5-haiku") is True
    monkeypatch.setenv("IFA_LLM_BACKEND", "databricks")
    assert client.supports_web_search_for("claude-4.5-haiku") is False


# --- model mapping ----------------------------------------------------------


def test_map_model_playground_is_identity():
    assert (
        backends.map_model("claude-4.8-opus", backend="playground") == "claude-4.8-opus"
    )


def test_map_model_databricks_names_pass_through():
    assert (
        backends.map_model("databricks-claude-opus-4-6", backend="databricks")
        == "databricks-claude-opus-4-6"
    )


def test_map_model_claude_transform():
    assert (
        backends.map_model("claude-4.6-opus", backend="databricks")
        == "databricks-claude-opus-4-6"
    )
    assert (
        backends.map_model("claude-4.5-haiku", backend="databricks")
        == "databricks-claude-haiku-4-5"
    )


def test_map_model_env_map_wins(monkeypatch):
    monkeypatch.setenv("IFA_DBX_MODEL_MAP", '{"claude-4.6-opus": "my-custom-endpoint"}')
    assert (
        backends.map_model("claude-4.6-opus", backend="databricks")
        == "my-custom-endpoint"
    )


def test_map_model_invalid_env_map_is_ignored(monkeypatch):
    monkeypatch.setenv("IFA_DBX_MODEL_MAP", "not json")
    assert (
        backends.map_model("claude-4.6-opus", backend="databricks")
        == "databricks-claude-opus-4-6"
    )


def test_map_model_generic_transform_for_gpt_and_gemini():
    # Verified live 2026-07-04: these endpoints exist in the workspace.
    assert backends.map_model("gpt-5.4", backend="databricks") == "databricks-gpt-5-4"
    assert (
        backends.map_model("gemini-2.5-flash", backend="databricks")
        == "databricks-gemini-2-5-flash"
    )


def test_map_model_available_set_validates_candidate():
    available = frozenset({"databricks-gpt-5-4"})
    assert (
        backends.map_model("gpt-5.4", backend="databricks", available=available)
        == "databricks-gpt-5-4"
    )
    # candidate not live → fall back to the default endpoint
    assert (
        backends.map_model("gpt-4o-mini", backend="databricks", available=available)
        == backends._DBX_FALLBACK_DEFAULT
    )


def test_map_model_default_env_override(monkeypatch):
    monkeypatch.setenv("IFA_DBX_DEFAULT_MODEL", "databricks-gpt-oss-120b")
    assert (
        backends.map_model("kimi-k2.6", backend="databricks", available=frozenset())
        == "databricks-gpt-oss-120b"
    )


# --- client.chat dispatch ---------------------------------------------------


def test_chat_dispatches_to_databricks_backend(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "databricks")
    captured: dict = {}

    def fake_chat(model, messages, **kwargs):
        captured["model"] = model
        captured["messages"] = list(messages)
        captured["kwargs"] = kwargs
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(databricks_backend, "chat", fake_chat)
    resp = client.chat(
        "claude-4.5-haiku",
        [{"role": "user", "content": "hi"}],
        web_search=True,
        max_tokens=123,
    )
    assert resp == {"choices": [{"message": {"content": "ok"}}]}
    assert captured["model"] == "claude-4.5-haiku"  # mapping happens in the adapter
    assert captured["kwargs"]["web_search"] is True
    assert captured["kwargs"]["max_tokens"] == 123


# --- Databricks adapter (mocked OpenAI client) -------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class _FakeOpenAIClient:
    def __init__(self, payload=None, error=None):
        self.calls: list = []
        self._payload = payload or {
            "choices": [{"message": {"content": "dbx ok", "tool_calls": None}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        self._error = error

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._error is not None:
                    raise outer._error
                return _FakeResponse(outer._payload)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def test_databricks_chat_returns_openai_shaped_dict(monkeypatch):
    fake = _FakeOpenAIClient()
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    resp = databricks_backend.chat(
        "claude-4.5-haiku", [{"role": "user", "content": "hi"}]
    )
    from investment_firm.llm.utils import extract_text, extract_usage, is_error

    assert is_error(resp) is False
    assert extract_text(resp) == "dbx ok"
    assert extract_usage(resp) == (5, 2, 7)


def test_databricks_chat_maps_model_name(monkeypatch):
    fake = _FakeOpenAIClient()
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    databricks_backend.chat("claude-4.6-opus", [{"role": "user", "content": "hi"}])
    assert fake.calls[0]["model"] == "databricks-claude-opus-4-6"


def test_databricks_chat_ignores_web_search(monkeypatch):
    fake = _FakeOpenAIClient()
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    databricks_backend.chat(
        "claude-4.5-haiku", [{"role": "user", "content": "hi"}], web_search=True
    )
    kwargs = fake.calls[0]
    assert "web_search" not in kwargs
    assert "web_search_options" not in kwargs
    assert "tools" not in kwargs


def test_databricks_chat_passes_openai_tools_through(monkeypatch):
    fake = _FakeOpenAIClient()
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    tools = [{"type": "function", "function": {"name": "dummy", "parameters": {}}}]
    databricks_backend.chat(
        "claude-4.5-haiku",
        [{"role": "user", "content": "hi"}],
        tools=tools,
        tool_choice="auto",
    )
    kwargs = fake.calls[0]
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == "auto"


def test_databricks_chat_wraps_provider_failure_as_error_dict(monkeypatch):
    fake = _FakeOpenAIClient(error=RuntimeError("endpoint not found"))
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    resp = databricks_backend.chat(
        "claude-4.5-haiku", [{"role": "user", "content": "hi"}]
    )
    from investment_firm.llm.utils import get_error_message, is_error

    assert is_error(resp) is True
    msg = get_error_message(resp)
    assert "Databricks call failed" in msg
    assert "endpoint not found" in msg


# --- message-history sanitizer (llm/sanitize.py) -----------------------------


class TestSanitizeOpenAIMessages:
    def _assistant_call(self, call_id, name="get_prices", content=""):
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
            ],
        }

    def test_balanced_history_unchanged_with_tools(self):
        msgs = [
            {"role": "user", "content": "q"},
            self._assistant_call("c1"),
            {"role": "tool", "tool_call_id": "c1", "content": '{"ok": 1}'},
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=True)
        assert out == msgs

    def test_strips_response_echoed_extras(self):
        # A re-sent assistant turn from Databricks model_dump() carries audio=None
        # etc.; the strict endpoint 400s ("Extra inputs are not permitted") unless
        # those empty extras are stripped before resend.
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "hi",
                "audio": None,
                "refusal": None,
                "function_call": None,
                "annotations": [],
            },
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=True)
        assert out[1] == {"role": "assistant", "content": "hi"}
        assert "audio" not in out[1]

    def test_strips_extras_but_keeps_tool_calls(self):
        call = self._assistant_call("c1")
        call["audio"] = None  # response echo
        call["tool_calls"][0]["index"] = 0  # extra key on the tool_call
        msgs = [
            {"role": "user", "content": "q"},
            call,
            {"role": "tool", "tool_call_id": "c1", "content": "{}", "audio": None},
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=True)
        assert "audio" not in out[1]
        assert out[1]["tool_calls"][0] == {
            "id": "c1",
            "type": "function",
            "function": {"name": "get_prices", "arguments": "{}"},
        }
        assert "audio" not in out[2]

    def test_dangling_tool_call_gets_synthesized_result(self):
        msgs = [
            {"role": "user", "content": "q"},
            self._assistant_call("c1"),
            {"role": "user", "content": "answer now"},
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=True)
        assert out[1]["tool_calls"]  # assistant turn preserved, never dropped
        stub = out[2]
        assert stub["role"] == "tool"
        assert stub["tool_call_id"] == "c1"
        assert "tool result unavailable" in stub["content"]
        assert out[3] == {"role": "user", "content": "answer now"}

    def test_orphan_tool_result_dropped(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "tool", "tool_call_id": "ghost", "content": "{}"},
            {"role": "assistant", "content": "hi"},
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=True)
        assert all(m.get("role") != "tool" for m in out)
        assert len(out) == 2

    def test_flatten_without_tools(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "q"},
            self._assistant_call("c1", name="get_prices", content="thinking"),
            {"role": "tool", "tool_call_id": "c1", "content": '{"price": 10}'},
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=False)
        assert all("tool_calls" not in m for m in out)
        assert all(m["role"] != "tool" for m in out)
        flat_assistant = out[2]
        assert flat_assistant["role"] == "assistant"
        assert "thinking" in flat_assistant["content"]
        assert "[called tools: get_prices]" in flat_assistant["content"]
        flat_result = out[3]
        assert flat_result["role"] == "user"
        assert flat_result["content"] == 'Tool result (c1): {"price": 10}'

    def test_flatten_also_repairs_dangling_ids(self):
        msgs = [
            {"role": "user", "content": "q"},
            self._assistant_call("c1"),
        ]
        out = sanitize.sanitize_openai_messages(msgs, tools_present=False)
        assert all(m["role"] != "tool" for m in out)
        assert any(
            m["role"] == "user" and "tool result unavailable" in m["content"]
            for m in out
        )


def test_databricks_chat_sanitizes_unbalanced_history(monkeypatch):
    """Dangling tool_calls in a tools-present request get stub results."""
    fake = _FakeOpenAIClient()
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    tools = [{"type": "function", "function": {"name": "dummy", "parameters": {}}}]
    msgs = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "dummy", "arguments": "{}"},
                }
            ],
        },
    ]
    databricks_backend.chat("claude-4.5-haiku", msgs, tools=tools)
    sent = fake.calls[0]["messages"]
    assert sent[-1]["role"] == "tool"
    assert sent[-1]["tool_call_id"] == "c1"


def test_databricks_chat_flattens_tool_history_when_tools_absent(monkeypatch):
    """Retry-without-tools resends a tool exchange with no tools kwarg — must flatten."""
    fake = _FakeOpenAIClient()
    monkeypatch.setattr(databricks_backend, "_openai_client", lambda: fake)
    msgs = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_prices", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"price": 10}'},
    ]
    databricks_backend.chat("claude-4.5-haiku", msgs)
    sent = fake.calls[0]["messages"]
    assert all("tool_calls" not in m for m in sent)
    assert all(m["role"] != "tool" for m in sent)
    assert any("Tool result (c1)" in m.get("content", "") for m in sent)


def test_missing_sdk_gives_install_and_auth_hint(monkeypatch):
    databricks_backend._openai_client.cache_clear()
    monkeypatch.setitem(sys.modules, "databricks", None)
    monkeypatch.setitem(sys.modules, "databricks.sdk", None)
    with pytest.raises(databricks_backend.DatabricksBackendError) as excinfo:
        databricks_backend._import_workspace_client()
    text = str(excinfo.value)
    assert 'pip install -e ".[databricks]"' in text
    assert "databricks auth login" in text
    databricks_backend._openai_client.cache_clear()


# --- capability downgrade in the orchestrator seam ---------------------------


def test_web_capable_worker_model_playground():
    from investment_firm.core.orchestrator import _web_capable_worker_model

    assert _web_capable_worker_model("balanced") == "claude-4.5-haiku"


def test_web_capable_worker_model_none_under_databricks(monkeypatch):
    monkeypatch.setenv("IFA_LLM_BACKEND", "databricks")
    from investment_firm.core.orchestrator import _web_capable_worker_model

    assert _web_capable_worker_model("balanced") is None
