# AGENTS.md
_Last reconciled: 2025-02-14_

## Overview
- Buy-side investment firm simulated as orchestrated LLM agents; produces an Investment Committee memo (decision-support only, never executes trades).
- Runs on the Deutsche Börse AI Playground API (one endpoint, many model families). Currently at milestone **M0** (scaffold + LLM client + web-search probe); agents/orchestrator are M1+.

## Architecture
- Package `src/investment_firm` (src layout; `pyproject.toml` finds packages under `src`).
- `llm/client.py` — thin Playground client: `chat`/`ask` (raw httpx POST, works for all model formats), `stream_chat`/`embeddings` (OpenAI lib, OpenAI-format only), `list_models`, `get_token_usage`, `model_capabilities`, `supports_websearch`, `_apply_web_search`.
- `llm/config.py` — lazy env/`.env` accessors (`api_key`, `base_url`, `verify_ssl`, `timeout`, `profile`, `websearch_mode`, `websearch_flag`); `.env` auto-loaded at import.
- `llm/models.py` — static model-name lists by family, `DEFAULT_CHAT_MODEL=gpt-4o-mini`, `DEFAULT_MAX_TOKENS=16000`; helpers `is_claude/is_gemini/is_gpt/family`.
- `llm/utils.py` — format-agnostic parsing: `extract_text`, `extract_usage`, `is_error`, `PlaygroundError` (handles OpenAI `choices[].message.content` AND Anthropic `content[].text`).
- `llm/costs.py` — unit-less relative `COST_WEIGHTS`, `estimate_cost`, `RunTracker` (per-run usage + optional token budget).
- `interfaces/cli.py` — M0 CLI: `--models`, `--tokens`, `--smoke`, `--probe-websearch MODEL`, `--version`; positional `question` is a stub until M2.
- `config/firm.yaml` — roster, tiers (WORKER/SENIOR/AUTHORITY/HEAD), profiles (budget/balanced/premium), data sources, committee voting rules. Consumed M1+ (no code reads it yet).

## Build & run
- Install: `python -m venv .venv` then `.venv\Scripts\python.exe -m pip install -e .` (run pip as a module — pip.exe shim is blocked by AppLocker).
- Extras: `.[data]` (M1.5), `.[embed]`/`.[api]` (M3), `.[dev]` (pytest+jupyter).
- Run: `python -m investment_firm --models|--tokens|--smoke|--probe-websearch <model>`; console script `investment-firm`.
- Test: `python -m pytest` (offline default; `-m 'not live'` is auto-applied). Live API tests: `python -m pytest -m live` (spend tokens).
- Requires Python >= 3.9.

## Conventions
- Config read lazily via functions (not module constants) so tests can monkeypatch env and reconfigure at runtime.
- `chat` auto-injects `max_tokens` only for Claude (Anthropic requires it); `temperature` omitted unless explicitly set (some models reject non-default).
- Cost weights are rough/unit-less, anchored to gpt-4o-mini≈0.2 — for budgeting/comparison only, not real prices.
- `/ai/models` is the live source of truth for capabilities; static lists in `models.py` just mirror docs.
- Disclaimer string lives in `investment_firm.__init__.DISCLAIMER`; CLI prints it before token-spending commands.

## Auth & security
- Key via `AI_PLAYGROUND_API_KEY` env / `.env` (from `.env.example`); placeholder `paste-your-key-here` treated as missing. `require_api_key()` raises `ConfigError`.
- Base URL `AI_PLAYGROUND_BASE_URL` (default `https://devportal.deutsche-boerse.de/api`).
- `AI_PLAYGROUND_VERIFY_SSL` defaults to **False** (Zscaler TLS inspection); accepts true/false/0/1 or a CA-bundle path. urllib3 InsecureRequestWarning is silenced when verify is False.
- `AI_PLAYGROUND_TIMEOUT` default 60s (first request can be ~10s due to Zscaler cold-start).
- Decision-support only: no broker/exchange/wallet connections, no order execution anywhere in the codebase.

## Gotchas / notes
- Web search is per-model: only Claude and Gemini chat report `webSearch: true`; GPT/Kimi/o4-mini return `Unknown parameter: 'web_search'`. Confirmed via `/ai/models` flags + probes.
- `IFA_WEBSEARCH_MODE` (default `auto`): Claude→native `web_search_20250305` tool; all others→generic top-level flag (`IFA_WEBSEARCH_FLAG`, default `web_search`). Modes: `auto`|`generic`|`anthropic`.
- Gemini accepts the generic flag but grounding/freshness is still unconfirmed (probe returned stale text); confirm wire format via DevPortal F12 → Network payload.
- `--probe-websearch` first checks `supports_websearch`; skips unsupported models (exit code 2) without spending a call.
- `IFA_PROFILE` (default `balanced`) selects firm.yaml profile (not yet wired into a run — M2).
- (2026-06-27) Playground model quirks (M1.5): (1) Claude rejects a `system` message inside the `messages` array — it must be a top-level `system` field. `client.chat` now auto-hoists any leading system message(s) to `payload["system"]` for Claude models. (2) Gemini often wraps JSON in ```json fences and can truncate mid-object at the token cap. `core/agent.py` strips fences (`_strip_fences`), and `_salvage_fields` regex-extracts stance/conviction/rationale from truncated JSON before the generic fallback. Default agent max_tokens raised to 1200.
