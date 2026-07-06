"""Tools the agents can call (M1.5).

A :class:`Tool` wraps a Python callable with a name, description, and JSON-schema
parameters so it can be advertised to an LLM as an OpenAI-format function tool and then
executed when the model calls it. :class:`ToolRegistry` collects tools and renders the
schema list / dispatches calls.

Data-source tools live in :mod:`datasources`; they degrade gracefully when the optional
``.[data]`` providers are not installed.
"""

from __future__ import annotations

from .base import Tool, ToolError, ToolRegistry
from .datasources import default_data_tools
from .openbb_datasources import default_openbb_tools

__all__ = [
    "Tool",
    "ToolError",
    "ToolRegistry",
    "default_data_tools",
    "default_openbb_tools",
]
