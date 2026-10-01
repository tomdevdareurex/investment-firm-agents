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

# --- Databricks serving endpoints ------------------------------------------
#
# Foundation-model endpoints on the DBAG workspace (verified live 2026-09-30).
# These are *endpoint* names, not Playground model names — the spelling differs
# (Claude variant/version swapped, dots → dashes); see ``backends._transform_databricks``.
# Used as the drift corpus for the ``databricks:`` rate card in ``config/costs.yaml``.
#
# Workspace-custom endpoints (``mv_*``, ``agents_prod_*``) are deliberately NOT
# listed: they are user-provisioned, churn independently of the foundation catalog,
# and are priced by the family fallback.

DATABRICKS_CHAT_ENDPOINTS = [
    "databricks-claude-fable-5",
    "databricks-claude-fable-5-1",
    "databricks-claude-haiku-4-5",
    "databricks-claude-opus-4-1",
    "databricks-claude-opus-4-5",
    "databricks-claude-opus-4-6",
    "databricks-claude-opus-4-7",
    "databricks-claude-opus-4-8",
    "databricks-claude-opus-5",
    "databricks-claude-opus-5-5",
    "databricks-claude-sonnet-4",
    "databricks-claude-sonnet-4-5",
    "databricks-claude-sonnet-4-6",
    "databricks-claude-sonnet-5",
    "databricks-claude-sonnet-5-5",
    "databricks-gemini-2-5-flash",
    "databricks-gemini-2-5-pro",
    "databricks-gemini-3-1-flash-image",
    "databricks-gemini-3-1-flash-lite",
    "databricks-gemini-3-1-pro",
    "databricks-gemini-3-5-flash",
    "databricks-gemini-3-5-flash-lite",
    "databricks-gemini-3-6-flash",
    "databricks-gemini-3-7-flash",
    "databricks-gemini-3-8-flash",
    "databricks-gemini-3-flash",
    "databricks-gemini-3-pro-image",
    "databricks-gemma-3-12b",
    "databricks-glm-5-3",
    "databricks-gpt-5",
    "databricks-gpt-5-1",
    "databricks-gpt-5-2",
    "databricks-gpt-5-3-codex",
    "databricks-gpt-5-4",
    "databricks-gpt-5-4-mini",
    "databricks-gpt-5-4-nano",
    "databricks-gpt-5-5",
    "databricks-gpt-5-5-pro",
    "databricks-gpt-5-6-luna",
    "databricks-gpt-5-6-sol",
    "databricks-gpt-5-6-terra",
    "databricks-gpt-5-mini",
    "databricks-gpt-5-nano",
    "databricks-gpt-6-1-sol",
    "databricks-gpt-6-astra",
    "databricks-gpt-6-luna",
    "databricks-gpt-6-sol",
    "databricks-gpt-oss-120b",
    "databricks-gpt-oss-20b",
    "databricks-grok-4-6",
    "databricks-grok-4-7",
    "databricks-inkling",
    "databricks-meta-llama-3-3-70b-instruct",
]

# Note ``mxbai-embed-de-large-v1`` carries no ``databricks-`` prefix.
DATABRICKS_EMBEDDING_ENDPOINTS = [
    "databricks-gte-large-en",
    "mxbai-embed-de-large-v1",
]

DATABRICKS_ENDPOINTS = DATABRICKS_CHAT_ENDPOINTS + DATABRICKS_EMBEDDING_ENDPOINTS

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
