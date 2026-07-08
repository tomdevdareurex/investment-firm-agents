"""LLM layer for the DBAG AI Playground API (client, config, models, costs, utils)."""

from __future__ import annotations

from .client import (
    ask,
    chat,
    embeddings,
    get_openai_client,
    get_token_usage,
    list_models,
    stream_chat,
)
from .config import ConfigError, has_api_key
from .costs import (
    CallRecord,
    RunTracker,
    cost_weight,
    estimate_cost,
    estimate_usd,
    usd_price,
)
from .models import (
    CHAT_MODELS,
    CLAUDE_MODELS,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_MODELS,
    GEMINI_MODELS,
    GPT_MODELS,
    OTHER_MODELS,
    family,
    is_claude,
)
from .utils import (
    PlaygroundError,
    extract_text,
    extract_usage,
    format_usage,
    get_error_message,
    is_error,
    print_response,
)

__all__ = [
    "ask",
    "chat",
    "embeddings",
    "get_openai_client",
    "get_token_usage",
    "list_models",
    "stream_chat",
    "ConfigError",
    "has_api_key",
    "CallRecord",
    "RunTracker",
    "cost_weight",
    "estimate_cost",
    "estimate_usd",
    "usd_price",
    "CHAT_MODELS",
    "CLAUDE_MODELS",
    "GEMINI_MODELS",
    "GPT_MODELS",
    "OTHER_MODELS",
    "EMBEDDING_MODELS",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "family",
    "is_claude",
    "PlaygroundError",
    "extract_text",
    "extract_usage",
    "format_usage",
    "get_error_message",
    "is_error",
    "print_response",
]
