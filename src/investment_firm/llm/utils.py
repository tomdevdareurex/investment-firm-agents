"""Parse responses uniformly across OpenAI- and Anthropic-style models.

``/chat/completions`` is a passthrough: GPT/Gemini/Kimi replies arrive in OpenAI format
(``choices[].message.content``) while Claude replies arrive in Anthropic format
(``content[].text``). These helpers hide that difference so every model "just works".
"""
from __future__ import annotations

from typing import Optional, Tuple


class PlaygroundError(RuntimeError):
    """Raised when the API returns an error response."""


def is_error(resp: dict) -> bool:
    """True if the response looks like an API error payload."""
    if not isinstance(resp, dict):
        return False
    if resp.get("type") == "error":  # Anthropic style
        return True
    if isinstance(resp.get("error"), dict):  # OpenAI style
        return True
    return False


def get_error_message(resp: dict) -> Optional[str]:
    """Return a human-readable error message, or ``None`` if not an error."""
    if not is_error(resp):
        return None
    err = resp.get("error", {})
    if isinstance(err, dict):
        return err.get("message") or err.get("type") or str(err)
    return str(err)


def extract_text(resp: dict, strict: bool = True) -> str:
    """Return the assistant's text from any supported response shape.

    Handles OpenAI Chat Completions and Anthropic Messages formats as well as error
    payloads.

    Args:
        resp: The raw JSON response dict.
        strict: If ``True`` (default), an error response raises
            :class:`PlaygroundError`; if ``False`` it returns an ``[API error] ...``
            string instead (handy when comparing many models at once).

    Returns:
        The assistant's text content (possibly an empty string).

    Raises:
        PlaygroundError: if ``strict`` and the response is an error or has no text.
    """
    if is_error(resp):
        message = get_error_message(resp) or "Unknown API error"
        if strict:
            raise PlaygroundError(message)
        return f"[API error] {message}"

    # OpenAI / GPT / Gemini / Kimi style
    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # some providers return content parts
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if content is None:
            return ""

    # Anthropic / Claude style
    content = resp.get("content")
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )

    if strict:
        raise PlaygroundError(
            "Could not find any text in the response. Top-level keys: "
            + ", ".join(sorted(resp.keys()))
        )
    return ""


def extract_tool_calls(resp: dict) -> list:
    """Return the OpenAI-style ``tool_calls`` list from a response, or ``[]``.

    Each entry is a dict like
    ``{"id": ..., "type": "function", "function": {"name": ..., "arguments": "<json>"}}``.
    Only the OpenAI Chat Completions shape is handled (GPT/Gemini/Kimi); Anthropic
    tool-use blocks are not parsed here (deferred).
    """
    if not isinstance(resp, dict):
        return []
    choices = resp.get("choices")
    if not (isinstance(choices, list) and choices):
        return []
    message = choices[0].get("message") or {}
    calls = message.get("tool_calls")
    return calls if isinstance(calls, list) else []


def assistant_message(resp: dict) -> Optional[dict]:
    """Return the raw assistant ``message`` dict from an OpenAI-shaped response.

    Useful for appending the model's tool-call turn back into the conversation before
    feeding tool results. Returns ``None`` for non-OpenAI shapes.
    """
    if not isinstance(resp, dict):
        return None
    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message")
        if isinstance(message, dict):
            return message
    return None


def extract_usage(resp: dict) -> Tuple[int, int, int]:
    """Return ``(input_tokens, output_tokens, total_tokens)`` for either format.

    Missing values are treated as 0. Works for OpenAI-style
    (``prompt_tokens``/``completion_tokens``) and Anthropic-style
    (``input_tokens``/``output_tokens``) usage blocks.
    """
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(usage, dict):
        return (0, 0, 0)

    def _as_int(value: object) -> int:
        return value if isinstance(value, int) else 0

    if "prompt_tokens" in usage or "completion_tokens" in usage:  # OpenAI
        inp = _as_int(usage.get("prompt_tokens"))
        out = _as_int(usage.get("completion_tokens"))
        total = _as_int(usage.get("total_tokens")) or (inp + out)
        return (inp, out, total)

    if "input_tokens" in usage or "output_tokens" in usage:  # Anthropic
        inp = _as_int(usage.get("input_tokens"))
        out = _as_int(usage.get("output_tokens"))
        return (inp, out, inp + out)

    return (0, 0, 0)


def format_usage(resp: dict) -> str:
    """Return a compact token-usage summary string for either response format."""
    inp, out, total = extract_usage(resp)
    if total == 0 and inp == 0 and out == 0:
        return "tokens: n/a"
    return f"tokens: input={inp}, output={out}, total={total}"


def model_name(resp: dict) -> str:
    """Return the model name reported by the response, or ``'?'``."""
    return resp.get("model", "?") if isinstance(resp, dict) else "?"


def print_response(resp: dict) -> None:
    """Pretty-print the assistant text and token usage of a response."""
    if is_error(resp):
        print(f"[API error] {get_error_message(resp)}")
        return
    print(extract_text(resp, strict=False))
    print("-" * 40)
    print(f"model: {model_name(resp)} | {format_usage(resp)}")
