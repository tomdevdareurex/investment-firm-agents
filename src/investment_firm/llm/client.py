"""Thin, self-contained client for the Deutsche Börse AI Playground API.

* :func:`chat` / :func:`ask` use a raw HTTP POST and return the *raw* JSON, so they work
  uniformly for every model (OpenAI- and Anthropic-format alike).
* :func:`stream_chat` / :func:`embeddings` use OpenAI's official library, which is
  convenient but assumes OpenAI-format models (GPT, Gemini, Kimi).

Web search is wired generic-flag-first with a per-provider fallback; see the README
"Web search" section and :func:`_apply_web_search`.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional, Sequence, Union

import httpx
from openai import OpenAI

from . import backends, config
from .models import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MAX_TOKENS,
    is_claude,
    is_gemini,
    is_gpt,
)
from .utils import PlaygroundError, extract_text, get_error_message, is_error

Message = dict
Messages = Sequence[Message]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.require_api_key()}",
        "Content-Type": "application/json",
    }


def _httpx_client() -> httpx.Client:
    """A short-lived httpx client honouring the SSL/timeout configuration."""
    return httpx.Client(verify=config.verify_ssl(), timeout=config.timeout())


def _json_or_error(response: httpx.Response, action: str) -> Any:
    """Parse a JSON response, or raise a clean :class:`PlaygroundError`.

    Many failure modes (401 auth errors, proxy pages, gateway errors) return a non-JSON
    body. Surfacing the HTTP status and a short snippet is far more useful than letting
    ``response.json()`` raise a bare ``JSONDecodeError`` stacktrace.
    """
    try:
        return response.json()
    except ValueError as exc:
        raise PlaygroundError(
            f"Failed to {action}: HTTP {response.status_code} "
            f"({response.text[:200].strip()!r})"
        ) from exc


def _is_rate_limited(response: httpx.Response) -> bool:
    """True if the response indicates a rate / tokens-per-minute limit."""
    if response.status_code == 429:
        return True
    if response.status_code in (500, 502, 503, 529):  # transient gateway/overload
        return True
    # Some gateways return 200/400 with a rate-limit message in the body.
    body = response.text.lower()
    return (
        "rate limit" in body or "tokens per min" in body or "too many requests" in body
    )


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying: honour ``Retry-After`` else exponential backoff."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 90.0)
        except ValueError:
            pass
    # Exponential backoff with a cap; tokens-per-minute windows are ~60s.
    return min(2.0 * (2**attempt), 60.0)


def _max_retries() -> int:
    """Number of rate-limit retries (env ``IFA_MAX_RETRIES``, default 4)."""
    try:
        return max(0, int(os.getenv("IFA_MAX_RETRIES", "4")))
    except ValueError:
        return 4


def _post_with_retry(url: str, payload: dict) -> httpx.Response:
    """POST with exponential backoff on rate-limit / transient errors."""
    attempts = _max_retries() + 1
    response: Optional[httpx.Response] = None
    for attempt in range(attempts):
        with _httpx_client() as client:
            response = client.post(url, headers=_headers(), json=payload)
        if not _is_rate_limited(response):
            return response
        if attempt < attempts - 1:
            wait = _retry_after_seconds(response, attempt)
            print(
                f"[rate-limit] HTTP {response.status_code}; retrying in {wait:.0f}s "
                f"(attempt {attempt + 1}/{attempts - 1}) ...",
                flush=True,
            )
            time.sleep(wait)
    return response  # exhausted retries; return the last response for normal handling


def _convert_tools_for_claude(tools: list) -> list:
    """Convert OpenAI tool schemas to Anthropic format.

    OpenAI:    ``{"type": "function", "function": {"name", "description", "parameters"}}``
    Anthropic: ``{"name", "description", "input_schema": <parameters>}``

    Entries already in Anthropic shape (have ``input_schema``, or non-function types like
    ``web_search_20250305``) pass through unchanged.
    """
    result = []
    for tool in tools:
        if not isinstance(tool, dict):
            result.append(tool)
            continue
        # Already Anthropic-shaped: has input_schema or is a non-function typed tool
        if "input_schema" in tool or tool.get("type") not in (None, "function"):
            result.append(tool)
            continue
        fn = tool.get("function") or {}
        result.append(
            {
                "name": fn.get("name", tool.get("name", "")),
                "description": fn.get("description", tool.get("description", "")),
                "input_schema": fn.get("parameters", {}),
            }
        )
    return result


def _convert_tool_choice_for_claude(tool_choice: Any) -> Any:
    """Convert an OpenAI tool_choice value to Anthropic format.

    * ``"auto"``              → ``{"type": "auto"}``
    * ``"required"`` / ``"any"`` → ``{"type": "any"}``
    * ``"none"``              → sentinel ``None`` (caller should omit the key)
    * dict                    → pass through unchanged
    """
    if isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice == "none":
        return None  # caller should omit the key
    if tool_choice in ("required", "any"):
        return {"type": "any"}
    if tool_choice == "auto":
        return {"type": "auto"}
    # Unknown string — best-effort pass-through
    return tool_choice


def _convert_messages_for_claude(messages: list) -> list:
    """Convert an OpenAI-format message list to Anthropic-compatible format.

    * ``role="tool"`` messages → user message with ``tool_result`` content block.
      Consecutive tool messages are merged into ONE user turn (Anthropic requires
      role alternation).
    * Assistant messages with ``tool_calls`` list → assistant message whose ``content``
      is a list of ``tool_use`` blocks (plus a text block if text was present).
    * Assistant messages whose ``content`` is already a list (raw Anthropic blocks) pass
      through unchanged.
    * All other messages are forwarded verbatim.
    """
    converted: list = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if not isinstance(msg, dict):
            converted.append(msg)
            i += 1
            continue

        role = msg.get("role")

        # --- tool result messages → merged user turn -------------------------
        if role == "tool":
            blocks = []
            while (
                i < len(messages)
                and isinstance(messages[i], dict)
                and messages[i].get("role") == "tool"
            ):
                m = messages[i]
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", ""),
                        "content": m.get("content", ""),
                    }
                )
                i += 1
            converted.append({"role": "user", "content": blocks})
            continue

        # --- assistant with OpenAI-style tool_calls --------------------------
        if role == "assistant":
            content = msg.get("content")
            tool_calls = msg.get("tool_calls")
            # Already Anthropic-shaped (content is a list of blocks) → pass through
            if isinstance(content, list):
                converted.append(msg)
                i += 1
                continue
            if isinstance(tool_calls, list) and tool_calls:
                blocks = []
                if content:  # text portion, if any
                    blocks.append({"type": "text", "text": str(content)})
                for call in tool_calls:
                    fn = call.get("function", {}) if isinstance(call, dict) else {}
                    raw_args = fn.get("arguments", "{}")
                    try:
                        parsed_input = (
                            json.loads(raw_args)
                            if isinstance(raw_args, str)
                            else raw_args
                        )
                    except (ValueError, TypeError):
                        parsed_input = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id", "") if isinstance(call, dict) else "",
                            "name": fn.get("name", ""),
                            "input": parsed_input,
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
                i += 1
                continue

        # --- all other messages pass through ---------------------------------
        converted.append(msg)
        i += 1

    return converted


_DEFAULT_WEBSEARCH_FLAG = "web_search"

# Gemini 2.5+ are "thinking" models: their hidden reasoning is billed against the
# same output budget as the visible reply, so a tight ``max_tokens`` can starve the
# answer and truncate it mid-sentence (the salvage path then returns half a rationale).
# Give Gemini enough headroom that reasoning + a complete reply both fit. This is only
# a CAP raise, so non-thinking replies are unaffected and never cost more.
_GEMINI_MIN_OUTPUT_TOKENS = 4096


def _apply_web_search(
    payload: dict,
    model: str,
    *,
    mode: Optional[str] = None,
    flag_key: Optional[str] = None,
    max_uses: int = 3,
) -> None:
    """Mutate ``payload`` to request web search according to the configured strategy.

    Strategy (``mode``):
      * ``anthropic`` — always use the Anthropic ``web_search_20250305`` tool (Claude).
      * ``generic``   — use the generic path for any model (see below).
      * ``auto``      — Claude uses the Anthropic tool (confirmed working); every other
                        model uses the generic path. This is the default.

    Generic path (confirmed 2026-07-02 on Deutsche Börse AI Playground):
      When ``flag_key`` is the default (``"web_search"``), the generic path sends
      ``payload["web_search_options"] = {}`` (OpenAI-style web-search options dict).
      This was confirmed to ground Gemini responses (returned the current ECB deposit
      rate of 2.25% effective 2026-06-17), whereas ``web_search=True`` (the old flag)
      was accepted but did NOT ground the answer.

      If ``IFA_WEBSEARCH_FLAG`` is set to something other than the default
      ``"web_search"``, the custom key is used with ``True`` as an escape hatch for
      future gateway changes.

    For Claude in auto/anthropic mode, the web_search tool is APPENDED to any existing
    ``payload["tools"]`` list (to allow function tools and web search to coexist).
    """
    mode = (mode or config.websearch_mode()).lower()
    flag_key = flag_key or config.websearch_flag()

    use_anthropic_tool = mode == "anthropic" or (mode == "auto" and is_claude(model))
    if use_anthropic_tool:
        payload.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
        ws_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_uses,
        }
        # Merge: append to existing tools list instead of overwriting
        existing = payload.get("tools")
        if isinstance(existing, list):
            payload["tools"] = existing + [ws_tool]
        else:
            payload["tools"] = [ws_tool]
    else:
        # Generic path: use web_search_options={} (confirmed grounding for Gemini
        # on this gateway 2026-07-02).  When a non-default flag key is configured
        # via IFA_WEBSEARCH_FLAG, fall back to setting that key to True (escape hatch).
        payload.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
        if flag_key == _DEFAULT_WEBSEARCH_FLAG:
            payload["web_search_options"] = {}
        else:
            payload[flag_key] = True


# --- Chat -----------------------------------------------------------------


def chat(
    model: str,
    messages: Messages,
    *,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    web_search: bool = False,
    web_search_mode: Optional[str] = None,
    max_uses: int = 3,
    tools: Optional[list] = None,
    tool_choice: Optional[Any] = None,
    json_mode: bool = False,
    extra: Optional[dict] = None,
) -> dict:
    """POST to ``/chat/completions`` and return the raw JSON response.

    Works for every model. Claude models *require* ``max_tokens``, so a sensible default
    is injected automatically when you do not pass one. Provider-specific parameters can
    be supplied via ``extra`` (e.g. ``extra={"max_completion_tokens": 1000}`` for some
    reasoning models). ``temperature`` is omitted unless explicitly set, because some
    models only accept their default.

    Args:
        model: Model name (see :data:`investment_firm.llm.models.CHAT_MODELS`).
        messages: Chat messages in OpenAI format.
        max_tokens: Output cap; auto-defaulted for Claude.
        temperature: Sampling temperature; omitted entirely when ``None``.
        web_search: If ``True``, request web search (see :func:`_apply_web_search`).
        web_search_mode: Override the configured web-search strategy for this call.
        max_uses: Max web searches when web search is enabled.
        tools: OpenAI-format function/tool schemas the model may call. Used by the
            agent loop; supported by OpenAI-format models (GPT/Gemini/Kimi).
        tool_choice: Optional tool-choice directive (e.g. ``"auto"``).
        json_mode: If ``True``, request structured JSON output where the model
            family supports it (GPT: ``response_format={"type":"json_object"}``;
            other families: no-op — they rely on prompt discipline + parse cascade).
        extra: Extra provider-specific keys merged into the payload.

    Returns:
        The raw JSON response dict (OpenAI- or Anthropic-shaped).

    Raises:
        PlaygroundError: if the response body is not JSON.
    """
    # Backend dispatch: core code always calls this function; which provider
    # actually serves the request is decided here (IFA_LLM_BACKEND / UI switch).
    if backends.current_backend() == backends.DATABRICKS:
        from . import databricks_backend

        return databricks_backend.chat(
            model,
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            web_search=web_search,
            tools=tools,
            tool_choice=tool_choice,
            json_mode=json_mode,
            extra=extra,
        )

    msgs = list(messages)

    # Claude on this gateway rejects a `system` *message* in the array; it must be a
    # top-level `system` field. Hoist any leading system message(s) accordingly.
    payload: dict[str, Any] = {"model": model}
    if is_claude(model):
        system_parts = [
            m.get("content", "")
            for m in msgs
            if isinstance(m, dict) and m.get("role") == "system"
        ]
        msgs = [
            m for m in msgs if not (isinstance(m, dict) and m.get("role") == "system")
        ]
        if system_parts:
            payload["system"] = "\n\n".join(p for p in system_parts if p)
        # Convert message history to Anthropic format (tool results, tool_calls, etc.)
        msgs = _convert_messages_for_claude(msgs)

    payload["messages"] = msgs

    if max_tokens is None and is_claude(model):
        max_tokens = DEFAULT_MAX_TOKENS
    if max_tokens is not None:
        # Gemini reasoning eats the output budget — floor the cap so the visible
        # answer isn't truncated by hidden thinking tokens (family logic stays here).
        if is_gemini(model):
            max_tokens = max(max_tokens, _GEMINI_MIN_OUTPUT_TOKENS)
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature

    # Apply function tools FIRST, then web search (web search appends for Claude).
    if tools:
        if is_claude(model):
            payload["tools"] = _convert_tools_for_claude(list(tools))
            converted_choice = _convert_tool_choice_for_claude(tool_choice)
            if converted_choice is not None:
                payload["tool_choice"] = converted_choice
        else:
            payload["tools"] = list(tools)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

    if json_mode and is_gpt(model):
        # OpenAI JSON mode requires the word "JSON" in the prompt; the agent
        # system prompt already demands a JSON object.
        payload["response_format"] = {"type": "json_object"}

    if web_search:
        _apply_web_search(payload, model, mode=web_search_mode, max_uses=max_uses)

    if extra:
        payload.update(extra)

    url = f"{config.base_url()}/chat/completions"
    response = _post_with_retry(url, payload)

    try:
        return response.json()
    except ValueError as exc:  # non-JSON body
        raise PlaygroundError(
            f"Non-JSON response (HTTP {response.status_code}): {response.text[:200]}"
        ) from exc


def ask(
    prompt: str,
    *,
    model: str = DEFAULT_CHAT_MODEL,
    system: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Send a single prompt and return just the assistant's text.

    Any extra keyword arguments are forwarded to :func:`chat`.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = chat(model, messages, **kwargs)
    return extract_text(resp, strict=False)


# --- OpenAI-library helpers ----------------------------------------------


def get_openai_client() -> OpenAI:
    """Return an OpenAI client pointed at the AI Playground (SSL-aware)."""
    return OpenAI(
        api_key=config.require_api_key(),
        base_url=config.base_url(),
        http_client=httpx.Client(verify=config.verify_ssl(), timeout=config.timeout()),
    )


def stream_chat(
    model: str,
    messages: Messages,
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    on_chunk=None,
) -> str:
    """Stream a completion, returning the full concatenated text.

    Best suited to OpenAI-format models (GPT, Gemini, Kimi). By default each chunk is
    printed as it arrives; pass ``on_chunk=callable`` to handle the pieces yourself.
    """
    client = get_openai_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "stream": True,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    full: list[str] = []
    for chunk in client.chat.completions.create(**kwargs):
        if not chunk.choices:
            continue
        piece = getattr(chunk.choices[0].delta, "content", None)
        if piece:
            full.append(piece)
            if on_chunk:
                on_chunk(piece)
            else:
                print(piece, end="", flush=True)
    if on_chunk is None:
        print()
    return "".join(full)


def embeddings(
    text: Union[str, Sequence[str]],
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> Union[list, list]:
    """Return embedding vector(s).

    Pass a single string to get one vector back, or a list of strings to get a list of
    vectors (one per input).
    """
    client = get_openai_client()
    single = isinstance(text, str)
    inputs = [text] if single else list(text)
    resp = client.embeddings.create(model=model, input=inputs)
    vectors = [item.embedding for item in resp.data]
    return vectors[0] if single else vectors


# --- Other endpoints ------------------------------------------------------


def list_models() -> list:
    """GET ``/ai/models`` — available chat models and their capabilities.

    Raises:
        PlaygroundError: if the API returns an error payload.
    """
    url = f"{config.base_url()}/ai/models"
    with _httpx_client() as client:
        response = client.get(url, headers=_headers())
    data = _json_or_error(response, "list models")
    if isinstance(data, dict) and is_error(data):
        raise PlaygroundError(get_error_message(data) or "Failed to list models")
    return data


def _model_entries(models: object) -> list:
    """Normalise a ``/ai/models`` payload into a flat list of dict entries."""
    if isinstance(models, dict) and isinstance(models.get("data"), list):
        models = models["data"]
    if isinstance(models, list):
        return [m for m in models if isinstance(m, dict)]
    return []


def model_capabilities(
    model: str, *, models: Optional[object] = None
) -> Optional[dict]:
    """Return the ``/ai/models`` capability entry for ``model``, or ``None``.

    The entry includes flags such as ``webSearch`` and ``temperature``. Pass an existing
    ``models`` payload (e.g. from :func:`list_models`) to avoid a second API call.
    """
    entries = _model_entries(models if models is not None else list_models())
    target = model.strip().lower()
    for entry in entries:
        ident = str(entry.get("model") or entry.get("id") or "").strip().lower()
        if ident == target:
            return entry
    return None


def supports_websearch(
    model: str, *, models: Optional[object] = None
) -> Optional[bool]:
    """Return whether ``model`` advertises web-search support per ``/ai/models``.

    Returns ``True``/``False`` from the live ``webSearch`` capability flag, or ``None``
    when the model is not found in the payload (capability unknown). Pass ``models`` to
    reuse an already-fetched payload and skip the network round-trip.
    """
    entry = model_capabilities(model, models=models)
    if entry is None or "webSearch" not in entry:
        return None
    return bool(entry["webSearch"])


def supports_web_search_for(model: str) -> bool:
    """Backend-aware, offline web-search capability check.

    Core code (orchestrator) calls this instead of branching on model families,
    so switching backends never requires core changes. Databricks: always
    ``False``; Playground: Claude/Gemini families only.
    """
    return backends.supports_web_search(model)


def supports_streaming_for(model: str) -> bool:
    """Backend-aware token-streaming capability check.

    Token-level streaming uses the OpenAI-format SSE path (:func:`stream_chat`),
    which is only wired for the Playground backend and OpenAI-format families
    (Databricks returns full JSON; Anthropic uses a different shape). Callers
    that get ``False`` should fall back to the blocking :func:`chat`. Family
    logic stays here in ``llm/`` so core never branches on the provider.
    """
    from .models import is_claude

    return backends.current_backend() == backends.PLAYGROUND and not is_claude(model)


def get_token_usage() -> dict:
    """GET ``/ai/tokens`` — your monthly token usage as ``{used, total}``.

    Raises:
        PlaygroundError: if the API returns an error payload.
    """
    url = f"{config.base_url()}/ai/tokens"
    with _httpx_client() as client:
        response = client.get(url, headers=_headers())
    data = _json_or_error(response, "get token usage")
    if isinstance(data, dict) and is_error(data):
        raise PlaygroundError(get_error_message(data) or "Failed to get token usage")
    return data
