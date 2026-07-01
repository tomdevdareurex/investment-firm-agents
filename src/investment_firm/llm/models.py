"""Known model names for the AI Playground, grouped by family.

These lists mirror the documentation; the live source of truth is the ``/ai/models``
endpoint (see :func:`investment_firm.llm.client.list_models`).
"""
from __future__ import annotations

CLAUDE_MODELS = [
    "claude-4.8-opus",
    "claude-4.7-opus",
    "claude-4.6-opus",
    "claude-4.6-sonnet",
    "claude-4.5-opus",
    "claude-4.5-sonnet",
    "claude-4.5-haiku",
]

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

GPT_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
]

# Models that don't fit the families above.
OTHER_MODELS = ["kimi-k2.6", "o4-mini"]

EMBEDDING_MODELS = [
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-005",
    "text-embedding-ada-002",
]

CHAT_MODELS = CLAUDE_MODELS + GEMINI_MODELS + GPT_MODELS + OTHER_MODELS

# Cheap, broadly available default for quick experiments / smoke tests.
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Claude models *require* max_tokens; this default is injected when none is supplied.
DEFAULT_MAX_TOKENS = 16000


def is_claude(model: str) -> bool:
    """True if ``model`` is a Claude (Anthropic-format) model."""
    return model.lower().startswith("claude")


def is_gemini(model: str) -> bool:
    """True if ``model`` is a Gemini model."""
    return model.lower().startswith("gemini")


def is_gpt(model: str) -> bool:
    """True if ``model`` is an OpenAI GPT / o-series model."""
    m = model.lower()
    return m.startswith("gpt") or m.startswith("o4")


def family(model: str) -> str:
    """Return ``'claude'``, ``'gemini'``, ``'gpt'``, or ``'other'`` for a model name."""
    if is_claude(model):
        return "claude"
    if is_gemini(model):
        return "gemini"
    if is_gpt(model):
        return "gpt"
    return "other"
