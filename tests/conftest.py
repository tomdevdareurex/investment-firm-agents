"""Shared pytest fixtures — offline only (no network, no tokens).

FakeLLM
-------
A scriptable monkeypatch for ``investment_firm.llm.client.chat``.

Design notes
~~~~~~~~~~~~
``client.chat`` is called with positional args ``(model, messages, **kwargs)``
and must return a raw JSON dict.  FakeLLM stores a queue of *responses*; each
call pops the next one and records ``(model, messages, kwargs)`` in ``.calls``
for assertion.

Supported response shapes
~~~~~~~~~~~~~~~~~~~~~~~~~
* OpenAI text:   ``{"choices": [{"message": {"content": "..."}}], "usage": {...}}``
* Anthropic text:``{"content": [{"type": "text", "text": "..."}], "usage": {...}}``
* OpenAI tool-call (one round):
  ``{"choices": [{"message": {"tool_calls": [...], "content": null}}], "usage": {...}}``

Helpers
~~~~~~~
* ``openai_text(text)``    — build a minimal OpenAI text response
* ``anthropic_text(text)`` — build a minimal Anthropic text response
* ``openai_tool_call(name, args_dict, call_id)`` — build a tool-call response
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from investment_firm.llm import backends as _backends

# ---------------------------------------------------------------------------
# Hermetic environment
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _hermetic_llm_backend(monkeypatch):
    """Pin every test to the default (playground) backend regardless of .env.

    A developer's ``.env`` may set ``IFA_LLM_BACKEND=databricks``; the offline
    suite must never dispatch to a real backend adapter. Tests that need a
    specific backend still work — they ``monkeypatch.setenv`` after this runs.
    """
    monkeypatch.delenv("IFA_LLM_BACKEND", raising=False)
    _backends.reset_backend()
    yield
    _backends.reset_backend()


# ---------------------------------------------------------------------------
# Response-builder helpers
# ---------------------------------------------------------------------------


def openai_text(text: str, inp: int = 10, out: int = 10) -> dict:
    """Minimal OpenAI-shaped text response."""
    return {
        "choices": [{"message": {"content": text, "tool_calls": None}}],
        "usage": {
            "prompt_tokens": inp,
            "completion_tokens": out,
            "total_tokens": inp + out,
        },
    }


def anthropic_text(text: str, inp: int = 10, out: int = 10) -> dict:
    """Minimal Anthropic-shaped text response."""
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": inp, "output_tokens": out},
    }


def openai_tool_call(
    name: str,
    args: Dict[str, Any],
    call_id: str = "call_1",
) -> dict:
    """OpenAI-shaped response with a single tool call (no text content)."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


# ---------------------------------------------------------------------------
# FakeLLM class
# ---------------------------------------------------------------------------


class FakeLLM:
    """Scriptable replacement for ``investment_firm.llm.client.chat``.

    Usage::

        fake = FakeLLM([resp1, resp2, ...])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)

    Each call to the fake pops the next response from the queue.  If the queue
    is exhausted it raises ``RuntimeError`` (so tests fail clearly rather than
    silently returning empty dicts).

    Attributes:
        calls: List of ``(model, messages, kwargs)`` tuples recorded on each call.
    """

    def __init__(self, responses: Optional[List[dict]] = None) -> None:
        self._queue: List[dict] = list(responses or [])
        self.calls: List[tuple] = []

    def __call__(
        self,
        model: str,
        messages: list,
        **kwargs: Any,
    ) -> dict:
        if not self._queue:
            raise RuntimeError(
                f"FakeLLM: no more queued responses (got call for model={model!r})"
            )
        resp = self._queue.pop(0)
        self.calls.append((model, messages, kwargs))
        return resp

    def assert_call_count(self, n: int) -> None:
        assert len(self.calls) == n, f"Expected {n} LLM call(s), got {len(self.calls)}"


# ---------------------------------------------------------------------------
# Pytest fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_llm(monkeypatch):
    """Return a factory that creates a FakeLLM and patches client.chat.

    Usage in a test::

        def test_something(fake_llm):
            llm = fake_llm([openai_text('{"stance":"BULLISH","conviction":4,"rationale":"ok","key_risks":[]}')])
            # ... call code that invokes client.chat ...
            llm.assert_call_count(1)

    The fixture patches ``investment_firm.llm.client.chat`` so **all** code
    paths that import and call ``client.chat`` use the fake.
    """

    def _make(responses: List[dict]) -> FakeLLM:
        llm = FakeLLM(responses)
        monkeypatch.setattr("investment_firm.llm.client.chat", llm)
        return llm

    return _make
