"""Offline tests for the Databricks adapter's retry / max_tokens healing, and for
``utils.finish_reason`` / ``is_truncated`` (no network, no databricks-sdk needed)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from investment_firm.llm import databricks_backend as dbx
from investment_firm.llm.utils import finish_reason, is_truncated

_MESSAGES = [{"role": "user", "content": "hi"}]


class _HttpError(Exception):
    """Stand-in for an openai APIStatusError (``status_code`` + ``response.headers``)."""

    def __init__(self, message: str, status_code: int, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


class APIConnectionError(Exception):
    """Named like openai's class — recognised by name, no openai import needed."""


class _Resp:
    def model_dump(self) -> dict:
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


class _FakeOpenAI:
    """Scripted ``client.chat.completions.create``; each item is an exception or a response."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(dict(kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def dbx_env(monkeypatch):
    """Install a scripted fake client; capture sleeps instead of waiting."""
    sleeps: list[float] = []
    monkeypatch.setattr(dbx.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(dbx, "_available_endpoints", lambda: None)  # no network
    monkeypatch.setattr(dbx, "_MAX_TOKENS", {})
    monkeypatch.delenv("IFA_DBX_MAX_RETRIES", raising=False)
    monkeypatch.delenv("IFA_DBX_RETRY_BUDGET", raising=False)

    def install(script):
        fake = _FakeOpenAI(script)
        monkeypatch.setattr(dbx, "_openai_client", lambda: fake)
        return fake

    install.sleeps = sleeps
    return install


class TestRetry:
    def test_429_honours_retry_after_then_succeeds(self, dbx_env):
        fake = dbx_env([_HttpError("rate limited", 429, {"retry-after": "3"}), _Resp()])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)

        assert out["choices"][0]["message"]["content"] == "ok"
        assert len(fake.calls) == 2
        assert dbx_env.sleeps == [3.0]
        assert fake.calls[0]["model"].startswith("databricks-")

    def test_5xx_uses_jittered_exponential_backoff(self, dbx_env):
        fake = dbx_env(
            [_HttpError("bad gateway", 502), _HttpError("busy", 503), _Resp()]
        )
        dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)

        assert len(fake.calls) == 3
        first, second = dbx_env.sleeps
        assert 2.0 <= first < 3.0  # base * 2**0 + jitter
        assert 4.0 <= second < 5.0  # base * 2**1 + jitter

    def test_connection_error_recognised_by_class_name(self, dbx_env):
        fake = dbx_env([APIConnectionError("reset"), _Resp()])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)
        assert "choices" in out and len(fake.calls) == 2

    def test_gives_up_after_max_retries_with_error_envelope(self, dbx_env, monkeypatch):
        monkeypatch.setenv("IFA_DBX_MAX_RETRIES", "1")
        fake = dbx_env([_HttpError("rl", 429), _HttpError("rl", 429)])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)

        assert "error" in out and "Databricks call failed" in out["error"]["message"]
        assert len(fake.calls) == 2
        assert len(dbx_env.sleeps) == 1

    def test_zero_retries_means_single_attempt(self, dbx_env, monkeypatch):
        monkeypatch.setenv("IFA_DBX_MAX_RETRIES", "0")
        fake = dbx_env([_HttpError("rl", 429)])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)
        assert "error" in out and len(fake.calls) == 1 and dbx_env.sleeps == []

    def test_retry_budget_stops_long_waits(self, dbx_env, monkeypatch):
        monkeypatch.setenv("IFA_DBX_RETRY_BUDGET", "2")
        fake = dbx_env([_HttpError("rl", 429, {"retry-after": "10"})])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)
        assert "error" in out and len(fake.calls) == 1 and dbx_env.sleeps == []

    def test_auth_error_is_not_retried(self, dbx_env):
        fake = dbx_env([_HttpError("unauthorized", 401)])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)
        assert "error" in out and len(fake.calls) == 1 and dbx_env.sleeps == []

    def test_sdk_errors_still_propagate(self, dbx_env):
        fake = dbx_env([dbx.DatabricksBackendError("not configured")])
        with pytest.raises(dbx.DatabricksBackendError):
            dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)
        assert len(fake.calls) == 1


class TestMaxTokensRemedy:
    def test_retries_with_named_ceiling_and_remembers_it(self, dbx_env):
        fake = dbx_env(
            [
                _HttpError("max_tokens must be <= 4096, got 8000", 400),
                _Resp(),
                _Resp(),  # second chat(): should go straight through at 4096
            ]
        )
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=8000)
        assert "choices" in out
        assert [c["max_tokens"] for c in fake.calls] == [8000, 4096]
        assert dbx_env.sleeps == []  # a request fix, not a wait

        dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=8000)
        assert fake.calls[2]["max_tokens"] == 4096  # learned per endpoint

    def test_drops_parameter_when_endpoint_rejects_it_outright(self, dbx_env):
        fake = dbx_env(
            [
                _HttpError("max_tokens is not supported by this model", 400),
                _Resp(),
                _Resp(),
            ]
        )
        dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=500)
        assert "max_tokens" in fake.calls[0]
        assert "max_tokens" not in fake.calls[1]

        dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=500)
        assert "max_tokens" not in fake.calls[2]

    def test_unrelated_400_is_not_healed(self, dbx_env):
        fake = dbx_env([_HttpError("invalid tool schema", 400)])
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=100)
        assert "error" in out and len(fake.calls) == 1

    def test_remedy_terminates(self, dbx_env):
        """A persistent max_tokens 400 walks the ladder (ceiling → drop) then fails."""
        fake = dbx_env(
            [_HttpError("max_tokens too large, max 1000", 400)] * 2
            + [_HttpError("max_tokens is bad", 400)] * 2
        )
        out = dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=5000)
        assert "error" in out
        assert len(fake.calls) <= 4

    def test_healed_value_not_remembered_if_call_never_succeeds(self, dbx_env):
        dbx_env(
            [_HttpError("max_tokens must be <= 1000", 400), _HttpError("nope", 401)]
        )
        dbx.chat("claude-4.5-haiku", _MESSAGES, max_tokens=5000)
        assert dbx._MAX_TOKENS == {}


class TestFinishReason:
    def test_openai_shape(self):
        resp = {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]}
        assert finish_reason(resp) == "length"
        assert is_truncated(resp) is True

    def test_openai_stop_is_not_truncated(self):
        resp = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}
        assert finish_reason(resp) == "stop"
        assert is_truncated(resp) is False

    def test_anthropic_max_tokens_maps_to_length(self):
        resp = {"content": [{"type": "text", "text": "x"}], "stop_reason": "max_tokens"}
        assert finish_reason(resp) == "length"
        assert is_truncated(resp) is True

    def test_anthropic_end_turn_passes_through(self):
        resp = {"content": [], "stop_reason": "end_turn"}
        assert finish_reason(resp) == "end_turn"
        assert is_truncated(resp) is False

    @pytest.mark.parametrize("resp", [None, "text", [], {}, {"choices": []}])
    def test_unknown_shapes_are_none_and_not_truncated(self, resp):
        assert finish_reason(resp) is None
        assert is_truncated(resp) is False
