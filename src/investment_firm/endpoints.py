"""Endpoint registry loaded from ``config/endpoints.yaml`` — no URL is hardcoded in code.

Imports nothing else from this package so both ``llm/`` and ``core/`` can use it.
Override the file with ``IFA_ENDPOINTS_CONFIG=<path>``.
"""

from __future__ import annotations

import os
import string
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml


class EndpointsConfigError(RuntimeError):
    """Raised when ``endpoints.yaml`` is missing, malformed, or a lookup is invalid."""


def endpoints_config_path() -> Path:
    """Resolve the config path lazily (``IFA_ENDPOINTS_CONFIG`` env override wins)."""
    override = os.getenv("IFA_ENDPOINTS_CONFIG", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "config" / "endpoints.yaml"


def _check_urls(node: Any, trail: str, cfg_path: Path) -> None:
    """Every string leaf under a URL section must be an https URL."""
    if isinstance(node, dict):
        for key, value in node.items():
            _check_urls(value, f"{trail}.{key}" if trail else str(key), cfg_path)
    elif isinstance(node, str):
        if not node.startswith("https://"):
            raise EndpointsConfigError(f"{trail} must be an https URL: {cfg_path}")


@lru_cache(maxsize=1)
def load_endpoints(path: Optional[str] = None) -> dict:
    """Load, validate and cache the parsed ``endpoints.yaml`` document."""
    cfg_path = Path(path) if path else endpoints_config_path()
    if not cfg_path.exists():
        raise EndpointsConfigError(f"Endpoints config not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise EndpointsConfigError(f"Endpoints config must be a mapping: {cfg_path}")
    for section in ("data", "prediction_markets", "docs", "llm"):
        if section in data:
            _check_urls(data[section], section, cfg_path)
    return data


def reload_endpoints() -> None:
    """Drop the cached document (tests / hot-edit)."""
    load_endpoints.cache_clear()


def setting(dotted: str) -> Any:
    """Return a raw value by dotted key, e.g. ``kalshi.max_series``."""
    node: Any = load_endpoints()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise EndpointsConfigError(f"unknown endpoint setting {dotted!r}")
        node = node[part]
    return node


def url(dotted: str, **fields: Any) -> str:
    """Return the URL at ``dotted`` (e.g. ``data.ecb``) with ``{placeholders}`` filled."""
    template = setting(dotted)
    if not isinstance(template, str):
        raise EndpointsConfigError(f"endpoint {dotted!r} is not a URL string")
    needed = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    missing = needed - set(fields)
    if missing:
        raise EndpointsConfigError(
            f"endpoint {dotted!r} needs fields: {', '.join(sorted(missing))}"
        )
    return template.format(**fields)
