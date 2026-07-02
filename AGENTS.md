# AGENTS.md
_Last reconciled: 2026-07-01 (M1.7 — Run button live, /api/runs endpoints, results tabs)_

## Overview
- Buy-side investment firm simulated as orchestrated LLM agents; produces an Investment
  Committee memo (decision-support only, never executes trades).
- Runs on the Deutsche Börse AI Playground API (one endpoint, many model families).
- Current milestone: **M1.7** (Run button wired end-to-end; POST/GET /api/runs; results
  panel with Memo / Reasoning / Briefing / Sources / Costs tabs).

## Architecture

```
config/firm.yaml  →  core/roster  →  core/planner  →  core/agent  →  core/orchestrator  →  Memo
                                                         ↑
                                               core/tools (data tools)
                                               core/memory (ScratchMemory, RunMemory)
                                               core/schemas (AnalystView, Memo)
```

The `llm/` layer is at the bottom: `config → models → utils → costs → client`.
Nothing in `llm/` knows about `core/`.

## Module inventory

### llm/
- `config.py` — lazy env/.env accessors; never module constants (testable).
- `models.py` — static model lists + `is_claude/is_gemini/is_gpt/family`.
- `utils.py` — format-agnostic parsing (`extract_text`, `extract_usage`,
  `extract_tool_calls` — handles both OpenAI `tool_calls` and Anthropic `tool_use`
  blocks, normalized to OpenAI style; `assistant_message` handles both response shapes).
- `costs.py` — `COST_WEIGHTS`, `estimate_cost`, `RunTracker` (per-run budget).
- `client.py` — raw httpx POST to `/chat/completions`; Claude system-hoist + retries;
  Anthropic format conversion (`_convert_tools_for_claude`, `_convert_tool_choice_for_claude`,
  `_convert_messages_for_claude`); web-search injection (`_apply_web_search`).

### core/
- `roster.py` — `load_firm()`, `resolve_profile()`, `resolve_roles()` → `RoleSpec`;
  tier round-robin + family hints + per-role model pin.
- `planner.py` — `plan_roles()`: LLM call picks ordered analyst subset; falls back
  to all candidates on unparseable JSON.
- `agent.py` — `Agent`: tool-using observe-think-act loop; `_strip_fences`,
  `_salvage_fields`, `_extract_json_block`; `_parse` cascade; resilience ladder
  (error retry without tools → fallback view; finalization call on max_steps exhaust).
  Accepts `web_search` / `web_search_max_uses` params (set by orchestrator).
- `orchestrator.py` — `run_committee()`: briefing → plan → analysts → CIO synthesis;
  `simple=True` for the fixed-analyst dry-run path.
- `memory.py` — `ScratchMemory` (per-agent working notes), `RunMemory` (shared
  briefing + colleagues' findings across agents).
- `schemas.py` — `AnalystView`, `Memo` (Pydantic); `render()` + `all_sources()`.
- `tools/base.py` — `Tool`, `ToolRegistry`, `ToolError`; `dispatch()` returns
  JSON error envelopes rather than crashing the run.
- `tools/datasources.py` — free read-only tools: `get_prices` (yfinance),
  `get_ecb_rate`, `get_worldbank_indicator`, `get_company_filing` (EDGAR),
  `compute_risk_metrics` (VaR / Expected Shortfall / vol / drawdown via `risk.py`).
- `risk.py` — pure-stdlib quant metrics: `returns_from_prices`, `historical_var`,
  `parametric_var`, `expected_shortfall`, `annualized_vol`, `max_drawdown`,
  `risk_summary`. Positive values = losses (documented sign convention).

### interfaces/
- `cli.py` — argparse CLI: `--models/--tokens/--smoke/--probe-websearch/--version`
  + positional `question` (runs the committee).
- `web/__init__.py` — guards the fastapi import with a clear install message.
- `web/app.py` — FastAPI app; mounts static files; includes runs router.
  Routes: `/`, `/api/health`, `/api/profiles`, `/api/preview`.
- `web/runs.py` — in-memory run registry (threading.Lock + daemon threads);
  routes: `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}`.
- `web/static/` — `index.html`, `app.css`, `app.js`; plain no-build page.
  Run button live: confirm dialog → POST /api/runs → 3s poll → tabbed results
  (Memo / Reasoning / Briefing / Sources / Costs). All API text via textContent.

### config/
- `firm.yaml` — single source of truth for roles, tiers, profiles, data sources,
  committee voting rules.

### docs/
- `ARCHITECTURE.md` — layer diagram, run pipeline, firm.yaml contract, Playground
  quirks, web UI, testing philosophy, safety.

## Tests

```
tests/
  conftest.py              FakeLLM fixture + openai_text/anthropic_text/openai_tool_call builders
  test_client_offline.py   llm/ layer (response shapes, payload construction, web-search)
  test_core_offline.py     agent parsing, tool dispatch, memory, run_committee, planner
  test_roster.py           resolve_profile precedence, round-robin, family, pin, errors
  test_web_offline.py      FastAPI routes via TestClient (no network)
  test_web_runs.py         POST/GET /api/runs — validation, happy path, error path, list
  test_smoke_live.py       opt-in live smoke (@pytest.mark.live)
```

**FakeLLM** (`conftest.py`): monkeypatches `investment_firm.llm.client.chat` with a
queue of canned responses. Supports OpenAI text, Anthropic text, and OpenAI tool-call
shapes. Tests assert call counts and response parsing without any network.

Run: `.venv\Scripts\python.exe -m pytest` (offline default).

## Build & run
- Install: `python -m venv .venv` then `.venv\Scripts\python.exe -m pip install -e .`
- Extras: `.[data]` (M1.5), `.[api]` (web UI), `.[dev]` (pytest+jupyter).
- CLI: `investment-firm "<question>" [--profile budget|balanced|premium] [--simple]`
- Web: `.venv\Scripts\python.exe -m uvicorn investment_firm.interfaces.web.app:app`
- Test: `.venv\Scripts\python.exe -m pytest` (offline); `-m live` to spend tokens.

## Conventions
- Config read lazily via functions (not module constants) so tests can monkeypatch.
- `client.chat` auto-hoists system messages to `payload["system"]` for Claude.
- `_salvage_fields` rescues truncated Gemini JSON before the plain-text fallback.
- Cost weights are rough/unit-less, anchored to gpt-4o-mini≈0.2 (budgeting only).
- `votes`/`veto` in firm.yaml are stored in `RoleSpec` but not enforced until M2.
- System prompts (agent, librarian, synthesis) inject today's date at call time;
  all three instruct the model to prefer tool results / web search / briefing over
  training data, to state gaps explicitly, and to label unverifiable figures as
  "unverified (training data)".
- `Agent.run` passes `json_mode=True` on every `client.chat` call; `client.chat`
  applies `response_format={"type":"json_object"}` for GPT-family models only
  (family branching stays in `llm/`). budget/balanced WORKER tiers contain only
  Claude/Gemini (web-search-capable); GPT remains in SENIOR+ tiers and premium.

## Gotchas for future contributors

**1. Format conversion belongs only in `llm/`.** All OpenAI ↔ Anthropic format
conversion (`_convert_tools_for_claude`, `_convert_tool_choice_for_claude`,
`_convert_messages_for_claude`, `extract_tool_calls` Anthropic branch) lives in
`llm/client.py` and `llm/utils.py`. **Never add model-family branching (`is_claude`,
`is_gemini`) to `core/agent.py`.** The agent loop is intentionally format-agnostic;
it always passes OpenAI-format structures to `client.chat`, which converts them
transparently per-model family.

**2. Web search is per-family and profile-gated.** The orchestrator enables web
search for an agent only when (a) the role's model is Claude or Gemini (`is_claude`
/ `is_gemini` from `llm/models.py`) AND (b) the profile's `web_search_max_uses`
in `firm.yaml` is > 0. GPT and Kimi never receive the flag. Simple-mode runs skip
web search entirely. For Claude, the `web_search_20250305` tool is **appended**
(merged) to any existing function tools list — do not overwrite `payload["tools"]`.
For Gemini (and other non-Claude models), the generic path sends
`web_search_options: {}` — confirmed grounding on 2026-07-02; the old boolean
`web_search: true` flag is accepted by the gateway but does NOT ground.

**3. API errors must never surface as rationale.** The resilience ladder in
`Agent.run` ensures error messages from the API are captured in `key_risks` as
`"API error: <msg>"` and produce a fallback `AnalystView`, not raw error text in
`rationale`. The web UI Warnings tab also flags these views. Any future changes to
the agent loop must preserve this invariant.

## Auth & security
- Key via `AI_PLAYGROUND_API_KEY` env / `.env`. `require_api_key()` raises `ConfigError`.
- `AI_PLAYGROUND_VERIFY_SSL` defaults to `false` (Zscaler TLS inspection).
- Decision-support only: no broker/exchange/wallet connections, no order execution.
- `DISCLAIMER` from `investment_firm.__init__` appears in every Memo + CLI + web UI.
