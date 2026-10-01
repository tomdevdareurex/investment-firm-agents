# AGENTS.md
_Last reconciled: 2025-07-08_

## Overview
- Buy-side investment firm simulated as orchestrated LLM agents; produces an Investment Committee memo (decision-support only, never executes trades).
- Runs on the Deutsche Börse AI Playground API (one endpoint, many model families), with **Databricks model serving** as an interchangeable second backend.

## Architecture

```
config/firm.yaml  →  core/roster  →  core/planner  →  core/agent  →  core/orchestrator  →  Memo
                                                         ↑
                                               core/tools (data tools)
                                               core/memory (ScratchMemory, RunMemory)
                                               core/schemas (AnalystView, Memo)
```

The `llm/` layer is at the bottom: `config → models → backends → utils → costs → client`.
Nothing in `llm/` knows about `core/`.

### llm/
- `config.py` — lazy env/.env accessors; never module constants (testable). Key env vars: `AI_PLAYGROUND_API_KEY`, `AI_PLAYGROUND_VERIFY_SSL` (default false), `IFA_LLM_BACKEND`, `IFA_PROFILE`, `IFA_WEBSEARCH_MODE`, `IFA_CALL_PAUSE`.
- `models.py` — static model lists + `is_claude/is_gemini/is_gpt/family`. `is_gpt` matches both `gpt*` and `o4*` prefixes. `OTHER_MODELS` includes `kimi-k2.6` and `o4-mini`. `DATABRICKS_CHAT_ENDPOINTS` (53) + `DATABRICKS_EMBEDDING_ENDPOINTS` (2) = `DATABRICKS_ENDPOINTS`: the serving-endpoint corpus the `databricks:` rate card is drift-tested against (workspace-custom `mv_*` / `agents_prod_*` endpoints are deliberately excluded and keep family fallback).
- `utils.py` — format-agnostic parsing (`extract_text`, `extract_usage`, `extract_tool_calls` — handles both OpenAI `tool_calls` and Anthropic `tool_use` blocks, normalized to OpenAI style; `assistant_message` handles both response shapes).
- `costs.py` — **backend-aware** pricing; tables live in **`config/costs.yaml`** (not Python): per model `{input, output, weight}` (USD per 1M tokens + unit-less weight per 1k, anchored to gpt-4o-mini≈0.2), `families` fallback, `default`, plus a `databricks:` rate card (`aliases` + `models`, keyed by endpoint name with the `databricks-` prefix stripped). Loaded lazily via `load_costs()` (`lru_cache`; `reload_costs()` clears; `IFA_COSTS_CONFIG` env overrides the path). `price_for(model, *, backend=None)` → `Price(input_usd, output_usd, weight, source, basis, confidence)` over three orthogonal axes: `source` = which YAML key matched (`model|family|default`), `basis` = which rate table billed (`vendor|databricks`), `confidence` = how the number was obtained (`list|published|vendor-proxy|estimated`, `Price.is_estimate` for the latter two). Ladder: `databricks.models` (databricks backend only, via `backends.map_model` **without** `available=` so pricing never hits the network) → `models` → `families` → `default`. Databricks entries omit `weight`, which is inherited from the vendor ladder for the *logical* name — so a `Price` may take USD from `databricks:` and weight from `models:`. Deliberately **uncached**, so a mid-session backend switch takes effect. All public helpers gained keyword-only `backend=None`: `price_source`, `cost_weight`, `estimate_cost`, `usd_price`, `estimate_usd`. `RunTracker.record(..., *, backend=None)` stores `cost_usd_input`, `cost_usd_output`, `price_source`, `price_basis`, `price_confidence`, `backend` per call — USD is tracked per direction because output bills at 4-6x input, with `cost_usd` a derived property (`cost_units` stays single: the weight applies identically to both directions); `total_input_tokens` / `total_output_tokens` / `total_usd_input` / `total_usd_output` aggregate the split; `by_model()` / `unpriced_models()` / `estimated_models()` / `vendor_priced_models()` feed the web Costs tab; `render_summary` marks fallback-priced models `*`, estimated `~`, and vendor-rate-on-Databricks (an under-report) `!`.
- `client.py` — raw httpx POST to `/chat/completions`; Claude system-hoist + retries; Anthropic format conversion (`_convert_tools_for_claude`, `_convert_tool_choice_for_claude`, `_convert_messages_for_claude`); web-search injection (`_apply_web_search`); dispatches to the Databricks adapter when that backend is active; `supports_web_search_for(model)` and `supports_streaming_for(model)` shims (core never branches on provider). Gemini thinking models get `_GEMINI_MIN_OUTPUT_TOKENS = 4096` floor on `max_tokens` to prevent truncation by hidden reasoning tokens.
- `backends.py` — backend registry (`playground` default | `databricks`); selection precedence `set_backend()` → `IFA_LLM_BACKEND` env → playground; capability advertising (`supports_web_search`, `supports_tools`); per-backend `map_model`.
- `databricks_backend.py` — lazy adapter via `databricks-sdk` (`WorkspaceClient().serving_endpoints.get_open_ai_client()`); returns OpenAI-shaped dicts so `utils.py` parsers work unchanged; provider failures → `{"error": {...}}` envelopes; no web search (one-time warning). Model mapping: `databricks-*` passthrough → `IFA_DBX_MODEL_MAP` → mechanical transform → live-endpoint validation → `IFA_DBX_DEFAULT_MODEL` fallback.
- `sanitize.py` — `sanitize_openai_messages(messages, *, tools_present)` balances Anthropic-style `tool_use`/`tool_result` histories for the strict Databricks backend (synthesizes missing tool results, drops orphans, flattens tool exchanges to text when no tools are sent), then strips response-echoed extras (`audio`/`refusal`/`function_call`/… whitelisted to role/content/name/tool_calls/tool_call_id). Wired in `databricks_backend.chat`; the Playground path does its own conversion and never uses this.

### core/
- `roster.py` — `load_firm()`, `resolve_profile()`, `resolve_roles()` → `RoleSpec`; tier round-robin + family hints + per-role model pin.
- `planner.py` — `plan_roles()`: LLM call picks ordered analyst subset; catalogue annotates `optional: true` roles; falls back to the non-optional core candidates on unparseable JSON (all candidates only if every one is optional).
- `prompts/` — department-organized system-prompt library. `base.py`: `BASE_HEADER` + FROZEN `JSON_CONTRACT` + `compose()` (contract appended to every prompt, can't be dropped). Role bodies: `analysts.py` (8 research bodies), `economists.py` (ONE horizon-parameterized template × 3), `trading.py` (ONE asset-class-parameterized desk template × 4), `risk.py` (`MARKET_RISK_BODY` + lens-parameterized credit/liquidity), `governance.py`, `librarian.py`, `debate.py` (`BULL_LABEL`/`BEAR_LABEL` + enriched bull/bear/judge prompts). `registry.py`: `body_for(spec)` fallback chain — role body → department body (by firm.yaml `group`) → generic mandate body. Public API: `system_prompt_for(spec)`. Plain strings only — no llm imports, no model-family branching.
- `agent.py` — `Agent`: tool-using observe-think-act loop; `_strip_fences`, `_salvage_fields`, `_extract_json_block`; `_parse` cascade; resilience ladder (error retry without tools → fallback view; finalization call on max_steps exhaust). Accepts `web_search` / `web_search_max_uses` params (set by orchestrator). System prompt comes from `prompts.system_prompt_for(spec)`.
- `orchestrator.py` — `run_committee()`: briefing → plan → analysts → CIO synthesis; `simple=True` for the fixed-analyst dry-run path. Accepts `on_event=None` and emits coarse `StepEvent`s. `CANDIDATE_ANALYSTS` (9 core) + `OPTIONAL_ANALYSTS` (6, annotated as optional in the planner catalogue).
- `debate.py` — `run_debate()`: alternating Senior Research Bull/Bear turns over the analysts' full views, then a CIO judge; turn/judge failures yield explicit ERROR outcomes; accepts `on_event`.
- `events.py` — step-event bus: `StepEvent`, `safe_emit` (swallows consumer errors), `to_dict`, kind constants. Opt-in `on_event=None`; zero LLM cost.
- `errors.py` — shared error classifier: `error_summary`, `api_error_view`, `parse_error_view`. Mints explicit ERROR `AnalystView`s (grounded=False, conviction 0); API errors go to `key_risks`, never rationale.
- `consultant.py` — read-only quant consultant: `Consultant.ask()` over a `RunContext` (memo + step events); default `claude-4.8-opus` (`IFA_CONSULTANT_MODEL`); read-only tool subset `CONSULTANT_TOOL_NAMES` (get_prices, get_indicators, compute_risk_metrics, run_backtest, run_strategy_backtest); refuses trades/writes; `_finalize` never re-bills an already-generated answer; streams tokens via `client.stream_chat` when backend supports it.
- `memory.py` — `ScratchMemory` (per-agent working notes), `RunMemory` (shared briefing + colleagues' findings across agents).
- `schemas.py` — `AnalystView` (+ `error`, ERROR stance), `Memo` (+ CIO attribution fields, ERROR recommendation); `render()` + `all_sources()`.
- `tools/base.py` — `Tool`, `ToolRegistry`, `ToolError`; `dispatch()` returns JSON error envelopes rather than crashing the run.
- `tools/datasources.py` — 13 free read-only tools: `get_prices` (yfinance), `get_ecb_rate`, `get_worldbank_indicator`, `get_company_filing` (EDGAR), `get_indicators` (whitelisted stockstats catalog via `data/indicators.py`), `compute_risk_metrics`, `run_backtest` (buy-and-hold), `run_strategy_backtest` (rule-based long/flat strategies via `data/backtest.py`), `get_fred_series`, `get_prediction_market_odds` (Polymarket), `get_stocktwits_sentiment`, `get_av_overview` (Alpha Vantage, needs key), `get_reddit_sentiment` (needs OAuth).
- `tools/openbb_datasources.py` — optional OpenBB Platform tools (keyless providers): `get_yield_curve` (Fed H.15), `get_options_summary` (Cboe chains), `get_cpi` (OECD monthly yoy). `default_openbb_tools()` returns `[]` when `.[openbb]` extra is not installed. OpenBB is AGPLv3 — treated as local/personal use.

### data/
Pure, network-free compute — must not import from `core/` or `interfaces/` (both import from here).
- `risk.py` — pure-stdlib quant metrics: `returns_from_prices`, `historical_var`, `parametric_var`, `expected_shortfall`, `annualized_vol`, `max_drawdown`, `risk_summary`. Positive values = losses.
- `indicators.py` — shared stockstats indicator engine over a whitelisted catalog; feeds `get_indicators`, the web charts, and backtest signals (chart==agent invariant).
- `backtest.py` — rule-based long/flat strategy backtester: `STRATEGIES` catalog (sma_crossover, macd_crossover, rsi_reversion, bollinger_reversion) + `run_strategy()` (no-lookahead one-bar position shift, `cost_bps`, buy-and-hold benchmark, risk metrics on equity curve).
- `technicals.py` — investing.com-style technical-summary gauges for the web charts.

### interfaces/
- `cli.py` — argparse CLI: `--models/--tokens/--smoke/--probe-websearch/--version` + positional `question`. `--stream/--no-stream` prints coarse step events; `--chat` opens a read-only consultant REPL.
- `web/app.py` — FastAPI app; mounts static files; includes runs + market routers. Routes: `/`, `/api/health`, `/api/profiles`, `/api/preview`, `GET/POST /api/backend`.
- `web/runs.py` — in-memory run registry (threading.Lock + daemon threads); routes: `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{run_id}` (+ event_count), `GET /api/runs/{run_id}/events` (SSE), `POST /api/runs/{run_id}/chat` (read-only consultant; 409 until done). Buffers step events per run; stores raw `Memo` + chat history.
- `web/market.py` / `web/market_data.py` — market chart endpoints; yfinance with SQLite cache (`.cache/investment_firm/market_data.sqlite`, override `INVESTMENT_FIRM_MARKET_CACHE`); Zscaler SSL via `REQUESTS_CA_BUNDLE`/`CURL_CA_BUNDLE`, explicit opt-out `INVESTMENT_FIRM_MARKET_VERIFY_SSL=false`.
- `web/static/` — `index.html`, `app.css`, `app.js`, `charts.js`, vendored `lightweight-charts`. Plain no-build page. Run button → POST /api/runs → poll + SSE → tabbed results (Memo / Reasoning / Debate / Briefing / Sources / Costs / Consultant). LLM-backend dropdown in the run form.

### config/
- `firm.yaml` — single source of truth for roles (27 total: 13 core + 14 `optional: true`), tiers, profiles (budget/balanced/premium), data sources, committee voting rules.
- `costs.yaml` — LLM price tables (USD per 1M tokens in/out + unit-less weight per 1k) with `families`/`default` fallbacks, plus a `databricks:` section (`aliases` + 55 endpoint entries) used only while that backend is active. Edit to change cost estimates; no code changes. Unlisted models are flagged ("fallback") in CLI summary + web Costs tab rather than priced silently; Databricks entries carry `src: published|vendor-proxy|estimated` so a guessed number is never reported as a published rate. Both YAMLs ship via `[tool.setuptools.package-data]`.

## Build & run
- Install: `python -m venv .venv` then `.venv\Scripts\python.exe -m pip install -e .`
- Extras: `.[data]` (yfinance/pandas/stockstats), `.[api]` (fastapi+uvicorn), `.[databricks]` (SDK), `.[openbb]` (AGPLv3, local/personal use), `.[dev]` (pytest+jupyter+black).
- Backend switch: `IFA_LLM_BACKEND=databricks` (env or `.env`) or the web UI dropdown; Databricks auth via `DATABRICKS_HOST`+`DATABRICKS_TOKEN` env vars.
- CLI: `investment-firm "<question>" [--profile budget|balanced|premium] [--simple] [--chat]`
- Web: `.venv\Scripts\python.exe -m uvicorn investment_firm.interfaces.web.app:app`
- Test: `.venv\Scripts\python.exe -m pytest` (offline); `-m live` to spend tokens.

## Conventions
- Config read lazily via functions (not module constants) so tests can monkeypatch.
- `client.chat` auto-hoists system messages to `payload["system"]` for Claude.
- `_salvage_fields` rescues truncated Gemini JSON before the plain-text fallback.
- Cost weights are rough/unit-less, anchored to gpt-4o-mini≈0.2 (budgeting only). `USD_PRICES` provides approximate real-money estimates per 1M tokens (input, output).
- `votes`/`veto` in firm.yaml are stored in `RoleSpec` but not enforced until M2.
- `bull_researcher`/`bear_researcher` carry explicit `model:` pins in firm.yaml (gpt-5.5 / claude-4.8-opus — high-tier debate seats overriding every profile).
- Analyst system prompts come from `core/prompts/` (`system_prompt_for(spec)`); the JSON output contract in `prompts/base.py` is FROZEN (parsers in `agent.py` depend on it). All prompts inject today's date at call time. CIO synthesis + librarian task prompts still live in `orchestrator.py`.
- `Agent.run` passes `json_mode=True` on every `client.chat` call; `client.chat` applies `response_format={"type":"json_object"}` for GPT-family models only (family branching stays in `llm/`).
- Freshness gate: `Agent.run` counts successful tool calls and web citations. Views with neither get `grounded=False` plus an "UNVERIFIED" key_risk; failed tools add "DATA GAP" key_risks; stale `as_of` dates (windows in `agent._FRESHNESS_WINDOWS_DAYS`) are flagged in memory notes.
- Real web-search URLs are carried as `Source` models on `AnalystView.citations` and `Memo.web_sources`; the web UI renders them as scheme-checked clickable links.
- The `research_librarian` pins `family: claude`; the orchestrator additionally overrides any non-web-capable resolution to a web-capable WORKER model (warn + degrade, never crash).
- Format conversion belongs only in `llm/`. The agent loop is intentionally format-agnostic; it always passes OpenAI-format structures to `client.chat`, which converts them transparently per-model family. Never add `is_claude`/`is_gemini` to `core/agent.py`.
- Web search is per-family and profile-gated. Claude gets `web_search_20250305` tool **appended** (merged) to existing tools. Gemini gets `web_search_options: {}` (confirmed grounding). GPT and Kimi never receive the flag. Simple-mode runs skip web search entirely.
- API errors must never surface as rationale. The resilience ladder ensures error messages are captured in `key_risks` as `"API error: <msg>"` and produce a fallback `AnalystView`, not raw error text in `rationale`.

## Auth & security
- Key via `AI_PLAYGROUND_API_KEY` env / `.env`. `require_api_key()` raises `ConfigError`.
- `AI_PLAYGROUND_VERIFY_SSL` defaults to `false` (Zscaler TLS inspection).
- Decision-support only: no broker/exchange/wallet connections, no order execution.
- `DISCLAIMER` from `investment_firm.__init__` appears in every Memo + CLI + web UI.

## Gotchas / notes
- **Environment quirks (DBAG work laptop).** Group policy blocks native binaries in user-writable dirs — invoke tools as `.venv/Scripts/python.exe -m <tool>` (e.g. black works, ruff's binary does not). `jq` is not installed.
- **Gemini thinking models** eat the output budget with hidden reasoning; `client.py` floors `max_tokens` to 4096 for Gemini to prevent truncation.
- **Planner fallback** on parse failure runs core (non-optional) candidates only, never the optional specialists — prevents fan-out on a bad JSON parse.
- **`is_gpt` matches `o4-*` prefix** (for o4-mini reasoning model) in addition to `gpt-*`.
- **budget/balanced WORKER tiers** contain only Claude/Gemini (web-search-capable); GPT remains in SENIOR+ tiers and premium.

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
  test_strategy_backtest.py strategy engine (signals, no-lookahead equity math, costs, errors)
  test_prompts.py          prompt library — frozen contract, body selection, fallback chain
  test_roster.py           resolve_profile precedence, round-robin, family, pin, errors
  test_tools_format.py     tool schema/dispatch format
  test_openbb_tools.py     OpenBB tools — gating, schemas, summaries (all mocked)
  test_altdata_tools.py    FRED, Polymarket, StockTwits, Alpha Vantage, Reddit, EDGAR
  test_indicators.py       indicator catalog, compute, snapshot, overlay, validation
  test_technicals.py       technical summary gauges
  test_data_layout.py      data/ package isolation (no core/ or interfaces/ imports)
  test_web_offline.py      FastAPI routes via TestClient (no network)
  test_web_runs.py         POST/GET /api/runs — validation, happy, error, list, SSE, chat
  test_web_backend.py      GET/POST /api/backend switch
  test_web_market.py       market chart endpoints + cache
  test_smoke_live.py       opt-in live smoke (@pytest.mark.live)
```

**FakeLLM** (`conftest.py`): monkeypatches `investment_firm.llm.client.chat` with a queue of canned responses. Supports OpenAI text, Anthropic text, and OpenAI tool-call shapes. An autouse fixture pins every test to the playground backend regardless of `.env`.

Run: `.venv\Scripts\python.exe -m pytest` (offline default).

## Claude Code tooling

- **`CLAUDE.md`** imports this file (`@AGENTS.md`) and adds graphify instructions.
- **Project subagents** (`.claude/agents/`): `provenance-auditor`, `scope-compliance-guard`, `llm-cost-auditor`, `web-ui-tester`, `python-reviewer`, `fastapi-reviewer`, `security-reviewer`, `silent-failure-hunter`.
- **Skills** (`.claude/skills/`): `run-offline-tests` (test-safety rules), `add-agent-role` (checklist for adding a roster role), `graphify` (knowledge-graph queries).
- **Hooks** (`.claude/settings.json`): edits to `.env*` are blocked (except `.env.example`); edited `.py` files are auto-formatted with black; graphify hook-guards on Bash and Read/Glob.
- **MCP servers** (`.mcp.json`): `context7` (HTTP, live library docs), `playwright` (npx stdio, browser automation).

## Rules for coding agents

**1. Offline tests only, by default.** `pytest` deselects `live` tests via `addopts` in `pyproject.toml`. Never run `-m live` or CLI runs against the real API unless the user explicitly asks. Run tests as `.venv/Scripts/python.exe -m pytest -q`.

**2. Decision-support only — hard scope boundary.** Never add order execution, broker/exchange/wallet connectivity, or automation that acts on a memo without a human in the loop.

**3. Environment quirks (DBAG work laptop).** Group policy blocks native binaries in user-writable dirs — invoke tools as `.venv/Scripts/python.exe -m <tool>`.
- (2026-09-30) Cost gotcha: `RunTracker.record` is always called with the *logical* Playground model name (`spec.model`, see core/agent.py:214) even on the Databricks backend, because `map_model` happens inside `llm/`. `price_for` therefore does the mapping itself to reach the `databricks:` rate card, and feeds the **original** name (never the mapped endpoint) into the vendor ladder — passing `databricks-claude-opus-4-8` there would turn an exact `claude-4.8-opus` hit into a family fallback. `family()` on a `databricks-*` name returns "other", so always strip the prefix before family lookup. Tests touching costs must call `costs.reload_costs()` after monkeypatching `IFA_COSTS_CONFIG` (lru_cache) and reset the backend (`backends.reset_backend()`).
- (2026-09-30) `gpt-4.1` and `gpt-4.1-mini` hold real tier slots in all three profiles but have **no** Databricks endpoint, so those seats silently run `IFA_DBX_DEFAULT_MODEL` there. Pricing now flags it (`!` in the CLI summary, `cost_vendor_priced_models` in the web payload); the actual fix is a `firm.yaml` tier change or an `IFA_DBX_MODEL_MAP` entry.
