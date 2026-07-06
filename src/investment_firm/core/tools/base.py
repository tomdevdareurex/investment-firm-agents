"""Tool abstraction and registry for agent tool-calling (M1.5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


class ToolError(RuntimeError):
    """Raised when a tool cannot run (bad args, missing provider, fetch failure)."""


@dataclass
class Tool:
    """A callable the model can invoke.

    Attributes:
        name: Function name the model calls (snake_case).
        description: What the tool does (shown to the model — be specific).
        parameters: JSON-schema describing the arguments (OpenAI function schema).
        func: The Python callable; receives keyword args, returns a JSON-able result.
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[..., Any]

    def schema(self) -> dict:
        """Return the OpenAI function-tool schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, **kwargs: Any) -> Any:
        """Execute the tool, wrapping any failure in :class:`ToolError`."""
        try:
            return self.func(**kwargs)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a tool-level error
            raise ToolError(f"{self.name} failed: {exc}") from exc


class ToolRegistry:
    """A collection of tools the agent may use."""

    def __init__(self, tools: Optional[List[Tool]] = None):
        self._tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> List[str]:
        return list(self._tools)

    def schemas(self) -> List[dict]:
        """Return the OpenAI tool-schema list to pass to ``client.chat(tools=...)``."""
        return [tool.schema() for tool in self._tools.values()]

    def dispatch(self, name: str, arguments: Any) -> str:
        """Run tool ``name`` with ``arguments`` and return a JSON string result.

        ``arguments`` may be a dict or a JSON string (as models emit). Errors are
        returned as a JSON ``{"error": ...}`` payload so the loop can continue and the
        model can react, rather than aborting the whole run.
        """
        if name not in self._tools:
            return json.dumps({"error": f"unknown tool {name!r}"})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except ValueError:
                return json.dumps({"error": f"invalid JSON arguments for {name!r}"})
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = self._tools[name].run(**arguments)
        except ToolError as exc:
            return json.dumps({"error": str(exc)})
        try:
            return json.dumps(result, default=str)
        except (TypeError, ValueError):
            return json.dumps({"result": str(result)})
