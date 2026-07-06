"""Opt-in live smoke tests — hit the real AI Playground API and spend a few tokens.

Deselected by default (pyproject sets ``-m 'not live'``). Run explicitly with:
    python -m pytest -m live
They skip automatically when no API key is configured.
"""

from __future__ import annotations

import pytest

from investment_firm.llm import client, config
from investment_firm.llm.models import DEFAULT_CHAT_MODEL
from investment_firm.llm.utils import extract_text

pytestmark = pytest.mark.live

_needs_key = pytest.mark.skipif(
    not config.has_api_key(), reason="no AI_PLAYGROUND_API_KEY configured"
)


@_needs_key
def test_list_models_nonempty():
    models = client.list_models()
    assert models  # non-empty list/payload


@_needs_key
def test_token_usage_has_shape():
    usage = client.get_token_usage()
    assert isinstance(usage, dict)
    assert "used" in usage or "total" in usage


@_needs_key
def test_cheap_ask_returns_text():
    text = client.ask("Reply with exactly: OK", model=DEFAULT_CHAT_MODEL, max_tokens=20)
    assert isinstance(text, str) and text.strip() != ""
