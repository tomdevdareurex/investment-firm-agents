"""Configuration for the DBAG AI Playground API, loaded from environment / .env.

Values are read lazily (via functions) so tests can monkeypatch the environment and so
the process can be reconfigured without re-importing. A ``.env`` file at the repository
root is loaded once at import time if present.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

_PLACEHOLDER = "paste-your-key-here"


def _load_dotenv() -> None:
    """Load the nearest ``.env`` walking up from this file to the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.exists():
            load_dotenv(dotenv_path=candidate)
            return
    # No .env found — rely on real environment variables (fine in CI / prod).
    load_dotenv()


_load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _parse_verify_ssl(raw: str | None):
    """Return ``False``/``True`` or a CA-bundle path string for httpx ``verify``.

    Corporate TLS inspection (Zscaler) usually requires either disabling verification
    (``false``) or pointing at a corporate CA bundle (a filesystem path).
    """
    if raw is None or raw.strip() == "":
        return False  # default: Zscaler-friendly, matches the DevPortal docs
    value = raw.strip()
    low = value.lower()
    if low in {"false", "0", "no", "off"}:
        return False
    if low in {"true", "1", "yes", "on"}:
        return True
    return value  # treat anything else as a path to a CA bundle


def api_key() -> str:
    """Return the configured API key (may be empty / placeholder)."""
    return os.getenv("AI_PLAYGROUND_API_KEY", "").strip()


def has_api_key() -> bool:
    """True if a real (non-placeholder) API key is configured."""
    key = api_key()
    return bool(key) and key != _PLACEHOLDER


def require_api_key() -> str:
    """Return the API key, or raise a helpful error if it is not configured.

    Raises:
        ConfigError: if no real key is present in the environment / ``.env``.
    """
    if not has_api_key():
        raise ConfigError(
            "No API key found. Copy .env.example to .env and set "
            "AI_PLAYGROUND_API_KEY to your AI Playground key (use the 'GET API KEY' "
            "button on the DevPortal AI Playground page)."
        )
    return api_key()


def base_url() -> str:
    """Return the API base URL (no trailing slash)."""
    return (
        os.getenv("AI_PLAYGROUND_BASE_URL", "https://devportal.deutsche-boerse.de/api")
        .strip()
        .rstrip("/")
    )


def verify_ssl():
    """Return the httpx ``verify`` value: ``False``, ``True``, or a CA-bundle path."""
    return _parse_verify_ssl(os.getenv("AI_PLAYGROUND_VERIFY_SSL"))


def timeout() -> float:
    """Return the per-request timeout in seconds (default 60)."""
    try:
        return float(os.getenv("AI_PLAYGROUND_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def profile() -> str:
    """Return the default firm profile name (budget | balanced | premium)."""
    return os.getenv("IFA_PROFILE", "balanced").strip() or "balanced"


def websearch_mode() -> str:
    """Return the web-search strategy: ``auto`` | ``generic`` | ``anthropic``.

    See the README "Web search" section. ``auto`` uses the Anthropic tool for Claude
    (known-good) and the generic flag for every other model (the path under test).
    """
    return (os.getenv("IFA_WEBSEARCH_MODE", "auto").strip() or "auto").lower()


def websearch_flag() -> str:
    """Return the top-level request key used by the generic web-search path."""
    return os.getenv("IFA_WEBSEARCH_FLAG", "web_search").strip() or "web_search"


def call_pause() -> float:
    """Seconds to pause between LLM calls in a run (env ``IFA_CALL_PAUSE``, default 0).

    Set this (e.g. ``2``) to spread token usage and avoid tokens-per-minute rate limits
    on the Playground when running the multi-agent committee.
    """
    try:
        return max(0.0, float(os.getenv("IFA_CALL_PAUSE", "0")))
    except ValueError:
        return 0.0


# Silence the per-request urllib3 warning that appears when verification is disabled
# (expected under Zscaler). Done once at import to keep output clean.
if verify_ssl() is False:
    try:
        import urllib3

        warnings.filterwarnings(
            "ignore", category=urllib3.exceptions.InsecureRequestWarning
        )
    except Exception:  # pragma: no cover - urllib3 always present via httpx
        pass
