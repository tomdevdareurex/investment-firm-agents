"""LLM backend selection, capability advertising, and per-backend model mapping.

Backends
--------
* ``playground`` — Deutsche Börse AI Playground (default; raw HTTP in ``client.py``).
* ``databricks`` — Databricks model serving via the SDK (``databricks_backend.py``).

Selection precedence: :func:`set_backend` runtime override → ``IFA_LLM_BACKEND`` env
(read lazily) → ``playground``. Core code never branches on the provider — it asks
:func:`supports_web_search` / :func:`supports_tools` and lets :func:`map_model`
translate logical model names into backend-specific ones.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Optional

from . import config
from .models import is_claude, is_gemini

_log = logging.getLogger(__name__)

PLAYGROUND = "playground"
DATABRICKS = "databricks"
BACKENDS = (PLAYGROUND, DATABRICKS)


class BackendError(RuntimeError):
    """Raised for unknown backend names or invalid backend configuration."""


@dataclass(frozen=True)
class BackendCapabilities:
    """What a backend can do — queried by core/ instead of provider branching."""

    name: str
    label: str
    supports_web_search: bool
    supports_tools: bool
    cost_units_label: str


_CAPABILITIES = {
    PLAYGROUND: BackendCapabilities(
        name=PLAYGROUND,
        label="AI Playground",
        supports_web_search=True,
        supports_tools=True,
        cost_units_label="weighted playground units",
    ),
    DATABRICKS: BackendCapabilities(
        name=DATABRICKS,
        label="Databricks",
        supports_web_search=False,  # no web search on Databricks model serving
        supports_tools=True,
        cost_units_label="raw tokens (unit-less weight)",
    ),
}

_lock = threading.Lock()
_override: Optional[str] = None


def normalize(name: object) -> str:
    """Validate a backend name, returning its canonical form.

    Raises:
        BackendError: if ``name`` is not a known backend.
    """
    candidate = str(name or "").strip().lower()
    if candidate not in BACKENDS:
        raise BackendError(
            f"Unknown LLM backend {candidate!r}. Available: {', '.join(BACKENDS)}"
        )
    return candidate


def current_backend() -> str:
    """Return the active backend: runtime override → ``IFA_LLM_BACKEND`` → playground."""
    with _lock:
        override = _override
    if override:
        return override
    return normalize(config.llm_backend())


def set_backend(name: object) -> str:
    """Set a runtime backend override (used by the web UI switch).

    Returns the canonical backend name.

    Raises:
        BackendError: if ``name`` is not a known backend.
    """
    global _override
    validated = normalize(name)
    with _lock:
        _override = validated
    return validated


def reset_backend() -> None:
    """Clear the runtime override (falls back to env / default). Used by tests."""
    global _override
    with _lock:
        _override = None


def capabilities(backend: Optional[str] = None) -> BackendCapabilities:
    """Return the capability descriptor for ``backend`` (default: active backend)."""
    name = normalize(backend) if backend else current_backend()
    return _CAPABILITIES[name]


def supports_web_search(model: str, backend: Optional[str] = None) -> bool:
    """True if ``model`` can ground via web search on the given/active backend.

    Databricks serving has no web search at all. On the Playground only the
    Claude and Gemini families have working (native/gateway) web search.
    """
    caps = capabilities(backend)
    if not caps.supports_web_search:
        return False
    return is_claude(model) or is_gemini(model)


def supports_tools(model: str, backend: Optional[str] = None) -> bool:
    """True if ``model`` may be offered function tools on the given/active backend."""
    return capabilities(backend).supports_tools


# --- per-backend model mapping ---------------------------------------------

_DBX_FALLBACK_DEFAULT = "databricks-claude-sonnet-4-6"
_CLAUDE_NAME_RE = re.compile(r"^claude-(\d+(?:\.\d+)?)-([a-z0-9]+)$")
_warned_fallbacks: set = set()


def _databricks_model_map() -> dict:
    """Optional explicit logical→endpoint map from ``IFA_DBX_MODEL_MAP`` (JSON)."""
    raw = os.getenv("IFA_DBX_MODEL_MAP", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        _log.warning("IFA_DBX_MODEL_MAP is not valid JSON — ignoring")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _databricks_default_model() -> str:
    return os.getenv("IFA_DBX_DEFAULT_MODEL", "").strip() or _DBX_FALLBACK_DEFAULT


def _transform_databricks(lower: str) -> str:
    """Mechanical Playground→Databricks name transform (verified live 2026-07-04).

    * ``claude-4.6-opus``   → ``databricks-claude-opus-4-6`` (variant/version swap)
    * ``gemini-2.5-flash``  → ``databricks-gemini-2-5-flash`` (dots → dashes)
    * ``gpt-5.4``           → ``databricks-gpt-5-4``
    """
    match = _CLAUDE_NAME_RE.match(lower)
    if match:
        version, variant = match.groups()
        return f"databricks-claude-{variant}-{version.replace('.', '-')}"
    return f"databricks-{lower.replace('.', '-')}"


def _map_model_databricks(model: str, available: Optional[frozenset] = None) -> str:
    lower = model.strip().lower()
    if lower.startswith("databricks-"):
        return model.strip()

    explicit = _databricks_model_map()
    if model in explicit:
        return str(explicit[model])
    if lower in explicit:
        return str(explicit[lower])

    candidate = _transform_databricks(lower)
    # Without a live endpoint list, trust the transform; with one, verify.
    if available is None or candidate in available:
        return candidate

    fallback = _databricks_default_model()
    if model not in _warned_fallbacks:
        _warned_fallbacks.add(model)
        _log.warning(
            "no Databricks endpoint %r for model %r — substituting %s "
            "(set IFA_DBX_MODEL_MAP / IFA_DBX_DEFAULT_MODEL to control this)",
            candidate, model, fallback,
        )
    return fallback


def map_model(
    model: str,
    backend: Optional[str] = None,
    *,
    available: Optional[frozenset] = None,
) -> str:
    """Translate a logical (Playground-style) model name for the given/active backend.

    ``available`` is an optional set of live serving-endpoint names; when given,
    a transformed name that does not exist falls back to the default endpoint.
    """
    name = normalize(backend) if backend else current_backend()
    if name == PLAYGROUND:
        return model
    return _map_model_databricks(model, available)
