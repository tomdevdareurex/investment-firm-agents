"""Thin, self-contained client for the Deutsche Börse AI Playground API.

* :func:`chat` / :func:`ask` use a raw HTTP POST and return the *raw* JSON, so they work
  uniformly for every model (OpenAI- and Anthropic-format alike).
* :func:`stream_chat` / :func:`embeddings` use OpenAI's official library, which is
  convenient but assumes OpenAI-format models (GPT, Gemini, Kimi).

Web search is wired generic-flag-first with a per-provider fallback; see the README
"Web search" section and :func:`_apply_web_search`.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional, Sequence, Union

import httpx
from openai import OpenAI

from . import config
from .models import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MAX_TOKENS,
    is_claude,
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
    return "rate limit" in body or "tokens per min" in body or "too many requests" in body


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying: honour ``Retry-After`` else exponential backoff."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 90.0)
        except ValueError:
            pass
    # Exponential backoff with a cap; tokens-per-minute windows are ~60s.
    return min(2.0 * (2 ** attempt), 60.0)


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
      * ``generic``   — set a single top-level flag (``flag_key``) for any model
                        (hypothesis A; confirm the exact key with the M0 probe).
      * ``auto``      — Claude uses the Anthropic tool (known-good); every other model
                        uses the generic flag (the path under test). This is the default.
    """
    mode = (mode or config.websearch_mode()).lower()
    flag_key = flag_key or config.websearch_flag()

    use_anthropic_tool = mode == "anthropic" or (mode == "auto" and is_claude(model))
    if use_anthropic_tool:
        payload.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
        payload["tools"] = [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_uses,
            }
        ]
    else:  # generic flag (hypothesis A — unconfirmed until the M0 probe)
        payload.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
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
        extra: Extra provider-specific keys merged into the payload.

    Returns:
        The raw JSON response dict (OpenAI- or Anthropic-shaped).

    Raises:
        PlaygroundError: if the response body is not JSON.
    """
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
        msgs = [m for m in msgs if not (isinstance(m, dict) and m.get("role") == "system")]
        if system_parts:
            payload["system"] = "\n\n".join(p for p in system_parts if p)
    payload["messages"] = msgs

    if max_tokens is None and is_claude(model):
        max_tokens = DEFAULT_MAX_TOKENS
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if web_search:
        _apply_web_search(payload, model, mode=web_search_mode, max_uses=max_uses)
    if tools:
        payload["tools"] = list(tools)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
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


def model_capabilities(model: str, *, models: Optional[object] = None) -> Optional[dict]:
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


def supports_websearch(model: str, *, models: Optional[object] = None) -> Optional[bool]:
    """Return whether ``model`` advertises web-search support per ``/ai/models``.

    Returns ``True``/``False`` from the live ``webSearch`` capability flag, or ``None``
    when the model is not found in the payload (capability unknown). Pass ``models`` to
    reuse an already-fetched payload and skip the network round-trip.
    """
    entry = model_capabilities(model, models=models)
    if entry is None or "webSearch" not in entry:
        return None
    return bool(entry["webSearch"])



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
