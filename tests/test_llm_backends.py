"""Offline tests for LLM backend selection, mapping, capabilities, and the
Databricks adapter (SDK fully mocked — no network, no tokens, no Databricks)."""
from __future__ import annotations

import sys

import pytest

from investment_firm.llm import backends, client, databricks_backend


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
    assert backends.map_model("claude-4.8-opus", backend="playground") == "claude-4.8-opus"


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
    monkeypatch.setenv(
        "IFA_DBX_MODEL_MAP", '{"claude-4.6-opus": "my-custom-endpoint"}'
    )
    assert backends.map_model("claude-4.6-opus", backend="databricks") == "my-custom-endpoint"


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
    resp = databricks_backend.chat("claude-4.5-haiku", [{"role": "user", "content": "hi"}])
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
    resp = databricks_backend.chat("claude-4.5-haiku", [{"role": "user", "content": "hi"}])
    from investment_firm.llm.utils import get_error_message, is_error

    assert is_error(resp) is True
    msg = get_error_message(resp)
    assert "Databricks call failed" in msg
    assert "endpoint not found" in msg


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
