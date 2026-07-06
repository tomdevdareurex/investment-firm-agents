"""Databricks model-serving backend adapter.

Databricks serving endpoints are OpenAI-compatible; we obtain a pre-authenticated
OpenAI client via the Databricks SDK. Auth resolves in SDK order:

1. ``DATABRICKS_HOST`` / ``DATABRICKS_TOKEN`` environment variables
2. a profile in ``~/.databrickscfg`` (``DATABRICKS_CONFIG_PROFILE``)
3. OAuth, after running ``databricks auth login``

No secrets are stored or read by this module. The SDK import is lazy so the
default (Playground) install never needs ``databricks-sdk``.

:func:`chat` returns ``response.model_dump()`` — a raw OpenAI-shaped dict — so the
existing parsers in :mod:`investment_firm.llm.utils` work unchanged. Provider
call failures are returned as error-shaped dicts (``{"error": {...}}``) so the
agent resilience ladder handles them (e.g. retry without tools).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional, Sequence

from . import backends
from .sanitize import sanitize_openai_messages

_log = logging.getLogger(__name__)

_INSTALL_HINT = (
    "Databricks backend unavailable: {cause}.\n"
    "Install the extra and authenticate (no PATs needed):\n"
    '    .venv\\Scripts\\python.exe -m pip install -e ".[databricks]"\n'
    "    databricks auth login --host https://<your-workspace-host>\n"
    "Then retry with IFA_LLM_BACKEND=databricks (or the UI backend switch)."
)


class DatabricksBackendError(RuntimeError):
    """Raised when the Databricks SDK is missing or authentication fails."""


def _import_workspace_client():
    """Lazily import the Databricks SDK; raise a clear install hint if absent."""
    try:
        from databricks.sdk import WorkspaceClient  # noqa: PLC0415 - lazy on purpose

        return WorkspaceClient
    except ImportError as exc:
        raise DatabricksBackendError(
            _INSTALL_HINT.format(cause="databricks-sdk is not installed")
        ) from exc


@lru_cache(maxsize=1)
def _workspace():
    """Cached WorkspaceClient (auth resolved by the SDK)."""
    workspace_client_cls = _import_workspace_client()
    try:
        return workspace_client_cls()
    except Exception as exc:  # noqa: BLE001 - SDK raises many auth/config types
        raise DatabricksBackendError(
            _INSTALL_HINT.format(
                cause=f"auth/connection failed ({exc.__class__.__name__}: {exc})"
            )
        ) from exc


@lru_cache(maxsize=1)
def _openai_client():
    """Cached OpenAI-compatible client for this workspace's serving endpoints."""
    return _workspace().serving_endpoints.get_open_ai_client()


@lru_cache(maxsize=1)
def _available_endpoints() -> Optional[frozenset]:
    """Live serving-endpoint names for mapping validation, or None if unavailable."""
    try:
        return frozenset(e.name for e in _workspace().serving_endpoints.list())
    except Exception:  # noqa: BLE001 - validation is best-effort only
        return None


_warned_web_search = False


def chat(
    model: str,
    messages: Sequence[dict],
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    web_search: bool = False,
    tools: Optional[list] = None,
    tool_choice: Optional[Any] = None,
    json_mode: bool = False,
    extra: Optional[dict] = None,
) -> dict:
    """Chat completion against a Databricks serving endpoint; returns a raw dict.

    ``web_search`` is ignored (Databricks serving has no web search) with a
    one-time warning — agents ground via data tools instead. ``json_mode`` is a
    no-op here: ``response_format`` support varies per served model, so we rely
    on prompt discipline + the parse cascade (same as non-GPT on the Playground).
    """
    global _warned_web_search
    if web_search and not _warned_web_search:
        _warned_web_search = True
        _log.warning(
            "web search is not available on the Databricks backend — request "
            "ignored; agents ground via data tools only"
        )
    del json_mode  # documented no-op

    endpoint = backends.map_model(
        model, backend=backends.DATABRICKS, available=_available_endpoints()
    )
    kwargs: dict[str, Any] = {
        "model": endpoint,
        "messages": sanitize_openai_messages(messages, tools_present=bool(tools)),
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    if tools:
        kwargs["tools"] = list(tools)  # OpenAI format passes through unchanged
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
    if extra:
        kwargs.update(extra)

    try:
        response = _openai_client().chat.completions.create(**kwargs)
    except DatabricksBackendError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as error dict, not a crash
        return {
            "error": {
                "message": (
                    f"Databricks call failed for {endpoint!r} "
                    f"({exc.__class__.__name__}): {exc}"
                )
            }
        }
    return response.model_dump()
