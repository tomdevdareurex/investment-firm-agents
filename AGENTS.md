# AGENTS.md
_Last reconciled: 2026-07-05 (optional OpenBB data tools: yield curve, options summary, CPI)_

## Overview
- Buy-side investment firm simulated as orchestrated LLM agents; produces an Investment
  Committee memo (decision-support only, never executes trades).
- Runs on the Deutsche Börse AI Playground API (one endpoint, many model families),
  with **Databricks model serving** as an interchangeable second backend
  (Playground monthly quota is account-bound and was exhausted 2026-07).
- Current milestone: **M1.7+** (Run button end-to-end; /api/runs; results tabs;
  Databricks backend switch; market charts panel).

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
  `_convert_messages_for_claude`); web-search injection (`_apply_web_search`);
  dispatches to the Databricks adapter when that backend is active;
  `supports_web_search_for(model)` shim (core never branches on provider).
- `backends.py` — backend registry (`playground` default | `databricks`); selection
  precedence `set_backend()` → `IFA_LLM_BACKEND` env → playground; capability
  advertising (`supports_web_search`, `supports_tools`); per-backend `map_model`.
- `databricks_backend.py` — lazy adapter via `databricks-sdk`
  (`WorkspaceClient().serving_endpoints.get_open_ai_client()`); returns
  OpenAI-shaped dicts so `utils.py` parsers work unchanged; provider failures →
  `{"error": {...}}` envelopes; no web search (one-time warning). Model mapping:
  `databricks-*` passthrough → `IFA_DBX_MODEL_MAP` → mechanical transform →
  live-endpoint validation → `IFA_DBX_DEFAULT_MODEL` fallback.
- `sanitize.py` — `sanitize_openai_messages(messages, *, tools_present)` balances
  Anthropic-style `tool_use`/`tool_result` histories for the strict Databricks
  backend (synthesizes missing tool results, drops orphans, flattens tool
  exchanges to text when no tools are sent), then strips response-echoed extras
  (`audio`/`refusal`/`function_call`/… whitelisted to role/content/name/
  tool_calls/tool_call_id) so a re-sent assistant turn never trips
  `"messages.N.audio: Extra inputs are not permitted"`. Wired in
  `databricks_backend.chat`; the Playground path does its own conversion and
  never uses this.

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
  `simple=True` for the fixed-analyst dry-run path. Accepts `on_event=None` and
  emits coarse `StepEvent`s (run/briefing/plan/analyst/debate/synthesis/run_done);
  populates `Memo` CIO attribution fields.
- `debate.py` — `run_debate()`: alternating Senior Research Bull/Bear turns
  (`BULL_LABEL`/`BEAR_LABEL`) over the analysts' full views, then a CIO judge;
  turn/judge failures yield explicit ERROR outcomes; accepts `on_event`.
- `events.py` — step-event bus: `StepEvent`, `safe_emit` (swallows consumer
  errors), `to_dict`, kind constants. Opt-in `on_event=None`; zero LLM cost.
- `errors.py` — shared error classifier: `error_summary`, `api_error_view`,
  `parse_error_view`. Mints explicit ERROR `AnalystView`s (grounded=False,
  conviction 0); API errors go to `key_risks`, never rationale.
- `consultant.py` — read-only quant consultant: `Consultant.ask()` over a
  `RunContext` (memo + step events); default `claude-4.8-opus`
  (`IFA_CONSULTANT_MODEL`); read-only tool subset `CONSULTANT_TOOL_NAMES`;
  refuses trades/writes; `_finalize` never re-bills an already-generated answer.
- `memory.py` — `ScratchMemory` (per-agent working notes), `RunMemory` (shared
  briefing + colleagues' findings across agents).
- `schemas.py` — `AnalystView` (+ `error`, ERROR stance), `Memo` (+ CIO
  attribution fields, ERROR recommendation); `render()` + `all_sources()`.
- `tools/base.py` — `Tool`, `ToolRegistry`, `ToolError`; `dispatch()` returns
  JSON error envelopes rather than crashing the run.
- `tools/datasources.py` — free read-only tools: `get_prices` (yfinance),
  `get_ecb_rate`, `get_worldbank_indicator`, `get_company_filing` (EDGAR),
  `compute_risk_metrics` (VaR / Expected Shortfall / vol / drawdown via `risk.py`),
  `run_backtest` (read-only buy-and-hold historical compute via `risk.py`).
- `tools/openbb_datasources.py` — optional OpenBB Platform tools (keyless providers,
  provenance-tagged like `datasources.py`): `get_yield_curve` (Fed H.15),
  `get_options_summary` (Cboe chains, summarized — never raw), `get_cpi` (OECD
  monthly yoy). `default_openbb_tools()` returns `[]` when the `.[openbb]` extra is
  not installed, so uninstalled envs never advertise dead tools to the model.
  Providers return decimal fractions — tools convert to percent.
  `_patch_static_imports()` works around an upstream builder bug (generated
  `openbb.package.*` modules import `OBBject_<Model>` names that
  `openbb_core.app.provider_interface` never exports; seen with openbb 4.7.2).
  OpenBB is AGPLv3 — treated as local/personal use here.
- `risk.py` — pure-stdlib quant metrics: `returns_from_prices`, `historical_var`,
  `parametric_var`, `expected_shortfall`, `annualized_vol`, `max_drawdown`,
  `risk_summary`. Positive values = losses (documented sign convention).

### interfaces/
- `cli.py` — argparse CLI: `--models/--tokens/--smoke/--probe-websearch/--version`
  + positional `question` (runs the committee). `--stream/--no-stream` prints
  coarse step events; `--chat` opens a read-only consultant REPL over the run.
- `web/__init__.py` — guards the fastapi import with a clear install message.
- `web/app.py` — FastAPI app; mounts static files; includes runs + market routers.
  Routes: `/`, `/api/health`, `/api/profiles`, `/api/preview`,
  `GET/POST /api/backend` (LLM backend switch; unknown name → 400).
- `web/runs.py` — in-memory run registry (threading.Lock + daemon threads);
  routes: `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}` (+ event_count),
  `GET /api/runs/{run_id}/events` (SSE step-event stream, sync generator),
  `POST /api/runs/{run_id}/chat` (read-only consultant; 409 until the run is done).
  The registry buffers step events per run and stores the raw `Memo` + chat history.
- `web/market.py` / `web/market_data.py` — market chart endpoints; yfinance with
  SQLite cache (`.cache/investment_firm/market_data.sqlite`, override
  `INVESTMENT_FIRM_MARKET_CACHE`); Zscaler SSL via `REQUESTS_CA_BUNDLE` /
  `CURL_CA_BUNDLE`, explicit opt-out `INVESTMENT_FIRM_MARKET_VERIFY_SSL=false`.
- `web/static/` — `index.html`, `app.css`, `app.js`, `charts.js`, vendored
  `lightweight-charts` (candles + volume + SMA 20/50); plain no-build page.
  Run button live: confirm dialog → POST /api/runs → 3s poll + live SSE feed → tabbed
  results (Memo / Reasoning / Debate / Briefing / Sources / Costs / Consultant). The
  Reasoning + Debate tabs show a live step-event feed via `EventSource`; the Consultant
  tab posts to `/api/runs/{id}/chat`. LLM-backend dropdown in the run form. All API text
  via textContent.

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
  test_errors.py           error classifier (api/parse ERROR views, invariants)
  test_events.py           step-event bus (ordered kinds, safe_emit, raising consumer)
  test_debate.py           Senior Research Bull/Bear labels, prompt carries analyst reasoning
  test_consultant.py       read-only consultant (answers from memory, read-only subset, backtest)
  test_llm_backends.py     backend registry + Databricks adapter (SDK fully mocked)
  test_citations.py        web-search citations → Source models → memo web_sources
  test_risk.py             quant metrics (VaR/ES/vol/drawdown sign conventions)
  test_roster.py           resolve_profile precedence, round-robin, family, pin, errors
  test_tools_format.py     tool schema/dispatch format
  test_openbb_tools.py     OpenBB tools — gating, schemas, summaries, agent loop (all mocked)
  test_web_offline.py      FastAPI routes via TestClient (no network)
  test_web_runs.py         POST/GET /api/runs — validation, happy, error, list, SSE, chat, attribution
  test_web_backend.py      GET/POST /api/backend switch
  test_web_market.py       market chart endpoints + cache
  test_smoke_live.py       opt-in live smoke (@pytest.mark.live)
```

**FakeLLM** (`conftest.py`): monkeypatches `investment_firm.llm.client.chat` with a
queue of canned responses. Supports OpenAI text, Anthropic text, and OpenAI tool-call
shapes. Tests assert call counts and response parsing without any network.

Run: `.venv\Scripts\python.exe -m pytest` (offline default).

## Build & run
- Install: `python -m venv .venv` then `.venv\Scripts\python.exe -m pip install -e .`
- Extras: `.[data]` (M1.5), `.[api]` (web UI), `.[databricks]` (second backend SDK),
  `.[openbb]` (OpenBB market-data tools, AGPLv3 — local/personal use),
  `.[dev]` (pytest+jupyter+black).
- Backend switch: `IFA_LLM_BACKEND=databricks` (env or `.env`) or the web UI
  dropdown; Databricks auth via `DATABRICKS_HOST`+`DATABRICKS_TOKEN` env vars
  (preferred here — the Databricks CLI .exe may be AppLocker-blocked).
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
- Freshness gate: `Agent.run` counts successful tool calls (JSON without an
  `"error"` key) and web citations (`llm.utils.extract_citations`, both gateway
  shapes). Views with neither get `grounded=False` plus an "UNVERIFIED" key_risk;
  failed tools add "DATA GAP" key_risks; stale `as_of` dates (windows in
  `agent._FRESHNESS_WINDOWS_DAYS`) are flagged in memory notes.
- Real web-search URLs are carried as `Source` models (url/title/origin/verified)
  on `AnalystView.citations` and `Memo.web_sources`; the web UI renders them as
  scheme-checked clickable links (DOM APIs only, never innerHTML).
- The `research_librarian` pins `family: claude`; the orchestrator additionally
  overrides any non-Claude/Gemini resolution to a web-capable WORKER model
  (warn + degrade, never crash).

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

## Rules for coding agents

**1. Offline tests only, by default.** `pytest` deselects `live` tests via
`addopts` in `pyproject.toml` — leave that alone. Never run `-m live`,
`tests/test_smoke_live.py`, or CLI runs against the real API unless the user
explicitly asks in the current conversation; these spend tokens. Run tests as
`.venv/Scripts/python.exe -m pytest -q`. Offline tests use the FakeLLM fixture
in `tests/conftest.py`.

**2. Decision-support only — hard scope boundary.** Never add order execution,
broker/exchange/wallet connectivity, or automation that acts on a memo without
a human in the loop. Read-only market data and research are fine.

**3. Environment quirks (DBAG work laptop).** Group policy blocks native
binaries in user-writable dirs — invoke tools as
`.venv/Scripts/python.exe -m <tool>` (e.g. black works, ruff's binary does
not). `jq` is not installed.

## Claude Code tooling in this repo

- **`CLAUDE.md`** imports this file (`@AGENTS.md`) so it loads into Claude
  Code's context every session — keep this file the single source of truth.
- **Project subagents** (`.claude/agents/`):
  - `provenance-auditor` — checks changes keep datapoint tagging, memo source
    citations, trust order, price cross-checks.
  - `scope-compliance-guard` — enforces the decision-support-only boundary.
  - `llm-cost-auditor` — reviews diffs for token-spend regressions (prompt
    bloat, fan-out growth, budget bypasses).
  - `web-ui-tester` — browser-level smoke test of the FastAPI UI via Playwright.
  - Plus generic copies for teammates: `python-reviewer`, `fastapi-reviewer`,
    `security-reviewer`, `silent-failure-hunter`.
- **Skills** (`.claude/skills/`): `run-offline-tests` (test-safety rules),
  `add-agent-role` (checklist for adding a roster role).
- **Hooks** (`.claude/settings.json`): edits to `.env*` are blocked
  (except `.env.example`); edited `.py` files are auto-formatted with black.
- **MCP servers** — the same two servers are configured for both harnesses:
  - `.mcp.json` (repo root, **Claude Code** format, `mcpServers` key): `context7`
    (HTTP, live library docs), `playwright` (npx stdio, browser automation). A
    top-level `_comment` key documents what each is for (JSON has no comments;
    Claude Code only reads `mcpServers`, so the key is ignored at load time).
  - `.vscode/mcp.json` (**VS Code Copilot** format, `servers` key): same two
    servers. Copilot does **not** read `.mcp.json`, so this file is required to
    expose the servers in Copilot Chat's Agent mode. The two files are separate —
    edit both to keep the harnesses in sync.
