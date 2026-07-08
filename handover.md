# Handover — investment-firm-agents

_Last updated: 2026-07-07 (latest: structural refactor Steps 5–7 in progress — charts.js series reuse; Steps 0–4 committed on `main`). See the top session section for exact resume state._

## What this repo is

Buy-side investment firm simulated as orchestrated LLM agents on the Deutsche
Börse AI Playground gateway → structured Investment Committee memo.
**Decision-support only — never executes trades.**

---

## Session 2026-07-07: structural refactor Steps 5–7 (charts.js reuse + final review) — IN PROGRESS

**Plan:** `~/.claude/plans/you-are-working-in-warm-fog.md` (original, Steps 0–7) and
`~/.claude/plans/continue-wiht-the-previous-linear-moth.md` (this continuation).
Behavior-preserving refactor; Steps 0–4 committed on `main`
(`ca789fb` lazy firm.yaml path + `IFA_FIRM_CONFIG`, `f71eb80` data/risk,
`292a553` data/indicators, `a74f684` data/technicals — `data/` package with permanent
re-export shims at the old `core/` paths). Baseline suite: **441 passed** offline.

### State right now (if resuming after token cutoff)

- **Step 5 (chart reuse on refetch) — implemented and STAGED** in git index:
  `charts.js` `ensureChart()` (create chart+candle+volume once, `setData()` per fetch),
  `volumeData()` helper, single `fitContent()` after full render. The staged snapshot is
  the Step-5-only state. Commit it as its own commit:
  `git commit -m "refactor: reuse chart + main series across fetches in charts.js"`
  (do NOT `git add` charts.js first — the working tree already contains Step 6).
- **Step 6 (overlay/subpane series reuse on toggle) — implemented in WORKING TREE**
  (unstaged): `renderOverlays` / `renderServerOverlays` / `renderSubpanes` now diff
  against checkbox+data state, `setData()` on existing series, add/remove only on
  change. Keyed maps unchanged (`smaSeries` by period, `serverSeries`/`subpaneSeries`
  by indicator name). After Step 5 commit: `git add` charts.js + commit
  `refactor: reuse overlay/subpane series on toggle in charts.js`.
- **web-ui-tester** agent was launched for browser verification (uvicorn :8000 +
  Playwright, Market Charts panel only — never trigger committee runs). If its result
  is unknown, re-run it: load SPY, switch ticker/period (chart instance must survive
  refetch), double-toggle SMA20/50, EMA10, SMA200, Boll, RSI, MACD (layout reflow),
  invalid ticker → error path clears chart, resize. Suite after both steps: 441 passed.
- **Step 7 (pending):** full pytest + black no-op; **provenance-auditor** +
  **scope-compliance-guard** over `ea91e7f..HEAD`; final summary. AGENTS.md is stale
  re: `data/` layer (`_Last reconciled_ 2026-07-05`) — update only if the user asks.
- `.claude/settings.local.json` modified — local permissions churn, do not commit.
- Deferred (documented, not done): lightweight-charts v5 bump, datasources
  per-provider split, rAF batching, `core/graph/` folder (rejected).

---

## Session 2026-07-06: fable-5 (debate naming, streaming, attribution, errors, consultant) — DONE (uncommitted)

**Goal:** harden trust + visibility of a run. All offline-tested (408 passed, black-clean).
Continued a Claude Code session that ran out of tokens mid-Slice-2.

### What was built

1. **Real error handling** — `core/errors.py` (NEW): `error_summary`, `api_error_view`,
   `parse_error_view`. `Stance`/`Recommendation` gained `"ERROR"`; `AnalystView.error`
   field; `conviction ge=0`. Any failed analyst/debate/synthesis step now yields an
   explicit labelled ERROR outcome (never a bland NEUTRAL). API errors stay in
   `key_risks` as `"API error: <msg>"`, never in rationale. 4a: `llm/sanitize.py` (NEW)
   balances Databricks `tool_use`/`tool_result` histories (wired in `databricks_backend`).
   4b: `get_stocktwits_sentiment` retries crypto with a `.X` suffix, else structured
   ToolError → DATA GAP. 4c: news_analyst parse failures yield an explicit ERROR view.
2. **Named Bull/Bear debate** — `core/debate.py`: `BULL_LABEL`/`BEAR_LABEL` =
   "Senior Research Bull/Bear"; prompts tell debaters to cite colleagues by role.
   Debaters consume each analyst's full `AnalystView.render()` (rationale + key_risks).
3. **CIO attribution** — `Memo` gained `synth_role`/`synth_model`/`debate_judge_role`/
   `debate_judge_model`; `Memo.render()` + web memo tab + debate verdict heading show
   "issued by CIO (model)". Populated in `orchestrator.run_committee`.
4. **Live step-event bus** — `core/events.py` (NEW): `StepEvent`, `safe_emit` (swallows
   consumer errors), `to_dict`. Opt-in `on_event=None` threaded through `Agent`,
   `run_debate`, `run_committee` (zero LLM cost — pure emits). CLI `--stream/--no-stream`
   prints coarse events to stderr. Web: run registry buffers events; `GET /api/runs/{id}/events`
   is an SSE stream (sync generator); `app.js` opens an `EventSource` live feed (Reasoning +
   Debate tabs) and falls back to the 3s poll on error.
5. **Read-only quant consultant** — `core/consultant.py` (NEW): `Consultant.ask()` over a
   `RunContext` (memo + step events), default model `claude-4.8-opus` (env
   `IFA_CONSULTANT_MODEL`). Hard read-only: tool subset `CONSULTANT_TOOL_NAMES`
   (get_prices/get_indicators/compute_risk_metrics/run_backtest) — no write/order tools
   exist in its registry; prompt refuses trades/writes. `run_backtest` (NEW tool in
   `datasources.py`) = read-only buy-and-hold historical compute on `risk.py`. Web:
   `POST /api/runs/{id}/chat` (409 if run not done); CLI `--chat` REPL; GUI "Consultant" tab.
   `client.supports_streaming_for` shim gates token streaming (llm/ only). Fix applied:
   `_finalize` never re-generates an already-billed answer (chunks it locally when streaming).

### Audits (this session)
- **scope-compliance-guard: PASS** — consultant + run_backtest are strictly read-only,
  no execution/broker/wallet, no new outbound connections.
- **llm-cost-auditor: PASS** — committee path spends the same call count (events add zero);
  consultant bounded + budget-guarded. Fixed one MEDIUM latent double-generation in streaming.

### New tests (all offline)
`test_errors.py`, `test_events.py`, `test_consultant.py`, new SSE + chat + attribution +
label cases in `test_web_runs.py`, error/label updates in `test_debate.py`. **408 passed.**

---

## Session 2026-07-05/06: TradingAgents pattern integration — DONE (uncommitted)

**Goal:** empower this repo with patterns from the local `TradingAgents` (TA) repo
(`C:\Users\wn686\...\REPOs\TradingAgents`) WITHOUT merging. Decisions locked:
**NO LangGraph, NO databricks-langchain** (both only pay off under a full LangChain
migration; the gateway + databricks-sdk path already works). Repos stay separate;
we copied patterns/code only. `stockstats` is BSD (used directly), so TA's license
is not triggered for indicators.

### What was built (all green, all offline-tested)

1. **Shared indicator engine** — `src/investment_firm/core/indicators.py` (NEW).
   `stockstats`-backed. `INDICATORS` catalog (ema/sma/macd/macds/macdh/rsi/boll/
   boll_ub/boll_lb/atr/vwma/mfi), `available_indicators()`, `compute(df, names)`
   (full series, NaN→None), `latest_snapshot(df, names)`, `overlay_series(...)`,
   `IndicatorError`. NOTE: stockstats uses min_periods=1 (partial-window fill, no
   leading-NaN gaps for SMA).
2. **New data tools** in `core/tools/datasources.py` — `default_data_tools()` now
   returns **11 tools** (was 6). Added: `get_indicators` (yfinance+stockstats),
   `get_fred_series` (keyless FRED CSV), `get_prediction_market_odds` (Polymarket
   Gamma, read-only), `get_stocktwits_sentiment`, `get_av_overview` (Alpha Vantage
   fundamentals, key-gated), `get_reddit_sentiment` (Reddit app-only OAuth,
   key-gated). All provenance-tagged (`source`, `as_of`); lazy imports via
   `_require`; raise `ToolError` on failure.
3. **Bull/Bear debate** — `core/debate.py` (NEW). `run_debate(...)` alternates
   Bull→Bear tool-free turns then a judge → `{stance, summary}`. Budget-guarded
   (`_estimate_tokens` reserves input+output). `schemas.py` gained `DebateTurn`
   + `Memo.debate` / `Memo.debate_summary` (rendered before SOURCES).
   `orchestrator.py` runs the debate between analyst views and CIO synthesis when
   `not simple and max_debate_rounds>0 and views`; judge reuses the CIO spec.
4. **firm.yaml** — new roles `technical_analyst`, `sentiment_analyst`,
   `news_analyst` (WORKER; news pins `family: claude`), `bull_researcher` (SENIOR,
   gpt), `bear_researcher` (SENIOR, claude). Added `max_debate_rounds` per profile
   (budget=1, balanced=2, premium=3). `CANDIDATE_ANALYSTS` expanded 8→11.
5. **Web UI** — chart indicator overlays (`?indicators=` on
   `/api/market/price-history`, 400-validated), RSI/MACD oscillator sub-panes
   (`charts.js` SERVER_LINES/SUBPANES), new **Debate tab** (`index.html`,
   `app.js` `renderDebateTab`, `app.css`). `/api/runs` result now includes
   `debate` + `debate_summary`.
6. **pyproject.toml** — `stockstats>=0.6.2` added to the `[data]` extra.

### Tests
- New: `tests/test_indicators.py`, `tests/test_altdata_tools.py` (17, requests
  mocked — incl. Alpha Vantage + Reddit), `tests/test_debate.py` (FakeLLM).
  Plus additions to `test_web_market.py`, `test_roster.py`, `test_web_runs.py`.
- **Full offline suite: 359 passed, 3 deselected** (`.venv\Scripts\python.exe -m
  pytest -q`). black-clean. scope-compliance + provenance guarantees preserved
  (all read-only, source-tagged; decision-support boundary intact).

### API keys (in `.env`, gitignored; `.env.example` stays blank)
- **Alpha Vantage: LIVE.** Key `ALPHA_VANTAGE_API_KEY=IC3PO33E4QJZPNC6` stored
  and **verified live** — `get_av_overview('AAPL')` returned real fundamentals
  (P/E 37.3, mktcap $4.5T, EPS 8.27). Free tier = 25 calls/day.
- **Reddit: NOT set up (blank, optional).** `REDDIT_CLIENT_ID/SECRET/USER_AGENT`
  placeholders exist but are empty. The 'script'-app creation is blocked because
  **Zscaler blocks Google reCAPTCHA** on the corp network, so `create app`
  silently no-ops. To finish: create the app **off the corp network** (phone /
  home wifi) at `https://old.reddit.com/prefs/apps` (type=script, redirect
  `http://localhost:8080`), then paste client id + secret into `.env`. Until then
  `get_reddit_sentiment` cleanly raises `ToolError`; **StockTwits already covers
  retail sentiment** with no OAuth. Recommendation: leave Reddit blank.

### NEW environment fix — Zscaler broke Python `requests` (verified 2026-07-06)
- Symptom: `SSLCertVerificationError [CERTIFICATE_VERIFY_FAILED] unable to get
  local issuer certificate` from the new `requests`-based tools (Alpha Vantage etc).
  `requests` uses certifi, which lacks the Zscaler root CA (same root as Node's
  `NODE_EXTRA_CA_CERTS` issue).
- **FIX (persistent, no code change):** set user env vars
  `REQUESTS_CA_BUNDLE` and `CURL_CA_BUNDLE` = `C:\Users\wn686\corp-ca.pem`
  (done via `setx`; takes effect in NEW terminals only). `requests` auto-honors
  `REQUESTS_CA_BUNDLE`. Inline for current shell:
  `$env:REQUESTS_CA_BUNDLE="C:\Users\wn686\corp-ca.pem"`. Also recorded in user
  memory `network-zscaler-latency.md`.
- The existing `web/market_data.py` already handled this via the same env vars +
  `INVESTMENT_FIRM_MARKET_VERIFY_SSL=false` opt-out; the newer plain-`requests`
  tools rely on the global env var instead of per-call SSL handling.

### Open / next-session options (all optional)
- Finish Reddit OAuth off-network (above), or drop it permanently.
- TA 5-tier rating (Buy/Overweight/Hold/Underweight/Sell) on the memo.
- Combined `get_verified_market_snapshot` tool (price + indicators in one call).
- Per-section report tree (TA-style readable memo sections).
- **Everything is uncommitted on `main`** — consider committing this session's diff
  before starting new work. Run offline tests first; NEVER run `-m live` (spends
  Playground/Databricks tokens) unless the user asks in-session.

---

## Prior session (2026-07-04): Databricks second LLM backend — DONE end-to-end

**Motivation:** Playground monthly quota exhausted (1,014,362 / 1,000,000
tokens; quota is account-bound, key rotation does not reset it). Databricks
model serving is now a fully interchangeable fallback backend.

### What was built

- **`src/investment_firm/llm/backends.py`** (new) — backend registry
  (`playground` default | `databricks`), selection precedence
  `set_backend()` override → `IFA_LLM_BACKEND` env → playground, capability
  advertising (`supports_web_search`, `supports_tools`), and per-backend model
  mapping (`map_model`).
- **`src/investment_firm/llm/databricks_backend.py`** (new) — lazy adapter via
  `databricks-sdk` (`WorkspaceClient().serving_endpoints.get_open_ai_client()`).
  Returns `response.model_dump()` (OpenAI-shaped dict) so all `llm/utils.py`
  parsers work unchanged. Provider failures → `{"error": {...}}` dicts (agent
  resilience ladder handles them). Missing SDK/auth →
  `DatabricksBackendError` with install + `databricks auth login` hint.
  `web_search` ignored (one-time warning); `json_mode` documented no-op.
- **`client.py`** — dispatches to the Databricks adapter at the top of
  `chat()` when that backend is active; new `supports_web_search_for(model)`
  shim. Playground path byte-identical.
- **`config.py`** — `llm_backend()` lazy env accessor.
- **`core/orchestrator.py`** — only core change: family checks
  (`is_claude or is_gemini`) replaced by `client.supports_web_search_for()`.
  Core never branches on the provider.
- **Web UI** — "LLM backend" dropdown + degradation note
  (`GET/POST /api/backend`; unknown name → 400). `app.py`, `index.html`,
  `app.js`, `app.css`.
- **`pyproject.toml`** — optional extra `databricks = ["databricks-sdk>=0.30.0"]`.

### Model mapping (verified live 2026-07-04)

Logical Playground names stay everywhere (`firm.yaml` untouched). On
Databricks: `databricks-*` passthrough → `IFA_DBX_MODEL_MAP` (JSON) →
mechanical transform (`claude-4.6-opus` → `databricks-claude-opus-4-6`
variant/version swap; others dots→dashes, `gpt-5.4` → `databricks-gpt-5-4`)
→ validated against the live endpoint list (38 endpoints) → fallback
`IFA_DBX_DEFAULT_MODEL` (default `databricks-claude-sonnet-4-6`).

### Graceful degradation

Databricks has **no web search** — agents ground via data tools only
(yfinance/ECB/EDGAR/World Bank). Grounding gate, UNVERIFIED labeling, and
citation rules untouched; no fake web sources. Costs tracked as raw tokens
(family "other", weight 1.0 — unit-less).

### Verification done

- Offline suite: **297 passed** (baseline was 266; +31 new), ~3.2s, zero
  network. New: `tests/test_llm_backends.py` (SDK fully mocked, autouse
  fixture pins `_available_endpoints → None`), `tests/test_web_backend.py`.
- Live (user-authorized, ~5k tokens on Databricks): OAuth auth OK
  (workspace `https://1977773360680501.1.gcp.databricks.com`, profile
  DEFAULT, GCP); tiny chat OK; function tool-calling OK
  (`get_price({"ticker":"AAPL"})`); full `--simple --profile budget`
  committee run: 4,319 tokens, 3 families mapped correctly, honest NEUTRAL/
  UNVERIFIED output (simple mode has no tools by design).

### Docs updated

`README.md` (setup line + "LLM backend switch" section), `QUICK_README.md`
(backend section), `docs/ARCHITECTURE.md` (layer diagram, new "LLM backends"
section, `/api/backend` in Web UI surface, new test files).

## Earlier work also in this uncommitted diff (previous sessions)

- **Market endpoint SSL fix** — Zscaler broke yfinance/curl_cffi.
  `REQUESTS_CA_BUNDLE`/`CURL_CA_BUNDLE` preferred;
  `INVESTMENT_FIRM_MARKET_VERIFY_SSL=false` explicit opt-out; never silent.
  Enriched 502 detail. (`web/market.py`, `web/market_data.py` — both new files.)
- **Error-shape hardening** — `llm/utils.py` `is_error`/`get_error_message`
  now catch string `error`, `detail`, `message` shapes; fixes silent
  "(no parseable response)" ungrounded analysts. Parse-fallback memory
  breadcrumb in `agent.py`.
- **Charts panel** — Lightweight Charts vendored, candles + volume + SMA
  20/50, SQLite market cache (`.cache/investment_firm/market_data.sqlite`,
  override `INVESTMENT_FIRM_MARKET_CACHE`).
- **Grounding/citations** — `grounded` flag, DATA GAP risks, real Claude +
  Gemini web citations as clickable sources (`tests/test_citations.py`).

## How to use the new backend

```bat
.venv\Scripts\python.exe -m pip install -e ".[databricks]"
databricks auth login --host https://1977773360680501.1.gcp.databricks.com
set IFA_LLM_BACKEND=databricks
.venv\Scripts\python.exe -m investment_firm.interfaces.cli --simple "Is AAPL fairly valued?"
```

Or the web UI dropdown ("LLM backend"). Auth is CLI-profile/OAuth only — no
PATs, no keys in `.env`.

## Environment gotchas (Windows work laptop)

- AppLocker blocks `pip.exe`/`pytest.exe` shims → always
  `.venv\Scripts\python.exe -m pip / -m pytest`.
- Zscaler TLS interception → market data needs `REQUESTS_CA_BUNDLE` or the
  explicit verify-off env; Playground client defaults
  `AI_PLAYGROUND_VERIFY_SSL=false`.
- Stray uvicorn processes cause pip Errno 13 — kill first (in Git Bash
  `ps -W`, PID is column 4).

## Session addendum (2026-07-04, operator Q&A) — usage clarifications + 1 open issue

### RESOLVED — web UI "LLM backend" dropdown now showing
- Symptom: user initially saw only Profile + Simple mode; no "LLM backend" column.
- The dropdown was in code all along: `web/static/index.html` (~line 37, `.field-row`
  left of Profile) + `app.js` `loadBackend()` → `GET /api/backend`. It was just a
  STALE served page (browser cache / uvicorn started before the static files existed).
- Fix that worked: hard-refresh / uvicorn restart. STATUS: RESOLVED — dropdown is
  now visible in the run form.
- If it recurs after edits: hard-refresh `Ctrl+Shift+R`, restart uvicorn with
  `--reload`, or check `http://127.0.0.1:8000/api/backend` (404 = old build → restart).

### AppLocker caveat for Databricks auth (this laptop)
- `databricks auth login` needs the separate Databricks **CLI** (`databricks.exe`),
  which the `[databricks]` extra does NOT install (that's the Python SDK only) and
  which AppLocker may block (unsigned .exe shim).
- PREFERRED auth path here = env vars (no executable): set `DATABRICKS_HOST` and
  `DATABRICKS_TOKEN`; the SDK reads them directly (`WorkspaceClient()` resolves
  env → ~/.databrickscfg → OAuth). Only fall back to `databricks auth login` if the
  CLI is actually runnable.

### Backend switch — persistent option
- `IFA_LLM_BACKEND` is read via `os.getenv` in `config.py`, which auto-loads `.env`.
- So instead of `set IFA_LLM_BACKEND=databricks` every session, add a line to `.env`:
  `IFA_LLM_BACKEND=databricks` (gitignored). Precedence: UI dropdown > env/.env >
  playground default.

### pip extras are additive (FYI)
- Running `.[data,api]` then `.[databricks]` separately does NOT remove the first —
  final env = data + api + databricks. Same as one line `.[data,api,databricks]`.
  Only `pip uninstall` removes packages. (Confirmed this session: user ran the
  combined `.[data,api,databricks]` install, exit 0.)

## Session addendum (2026-07-04, later) — Claude Code project setup

Repo-level Claude Code tooling added (recommendations in `setup_fixes.md`,
all implemented):

- **`CLAUDE.md`** (new) — one line, `@AGENTS.md`: imports AGENTS.md into Claude
  Code context every session. AGENTS.md stays the single source of truth and was
  reconciled to 2026-07-04 (Databricks backend, market layer, new tests, "Rules
  for coding agents" + "Claude Code tooling" sections).
- **`.claude/agents/`** (8 files) — custom: `provenance-auditor`,
  `scope-compliance-guard`, `llm-cost-auditor`, `web-ui-tester`; plus copies of
  global ECC agents for teammates: `python-reviewer`, `fastapi-reviewer`,
  `security-reviewer`, `silent-failure-hunter` (copies override globals by name;
  re-copy if ECC updates them).
- **`.claude/skills/`** — `run-offline-tests` (Claude-only; never `-m live`),
  `add-agent-role` (roster checklist).
- **`.claude/settings.json`** (new) — hooks: PreToolUse denies Edit/Write on
  `.env*` (except `.env.example`); PostToolUse auto-formats edited `.py` with
  black. Both use `.venv/Scripts/python.exe` for JSON parsing (no jq on this
  machine). Pipe-tested OK; **needs `/hooks` or a Claude Code restart to load**
  (file created mid-session).
- **`.mcp.json`** (new, team-shared) — `context7` (HTTP, live library docs) and
  `playwright` (npx stdio, browser automation). Moved out of user-local
  `~/.claude.json` on request. A top-level `_comment` key documents what each
  server is for (JSON has no comments; Claude Code only reads `mcpServers`).
- **`pyproject.toml`** — `black>=24.0` added to `[dev]` (ruff's native binary is
  AppLocker-blocked; black runs in-process via `python -m black`).

No src/ or test code was changed this session.

## Session addendum (2026-07-04, latest) — VS Code Copilot MCP + doc reconcile

Pure config/docs — no src/ or test changes.

- **`.vscode/mcp.json`** (new) — exposes the same `context7` + `playwright`
  servers to **VS Code Copilot Chat** (Agent mode). Copilot uses a different
  format/location than Claude Code: top-level `servers` key (not `mcpServers`),
  and it does **not** read the repo-root `.mcp.json`. Verified this session that
  Copilot was NOT reading `.mcp.json` (no `.vscode/` folder existed, no
  `chat.mcp.discovery.enabled` in user settings) — the "Start" control the user
  saw belongs to the Claude Code extension, not Copilot.
- **Two-harness rule:** `.mcp.json` (Claude Code) and `.vscode/mcp.json` (Copilot)
  are independent — editing one does not update the other. Keep both in sync by
  hand when adding/changing a server.
- **Activation:** in Copilot, open `.vscode/mcp.json` and click ▶ Start on each
  server (or run **MCP: List Servers**), switch chat to **Agent mode**, and
  confirm the 🛠️ Tools list shows `context7` + `playwright`. First `playwright`
  start pays the npx + Zscaler cold-start (~10s) — not a hang.
- **`setup_fixes.md` caveat (stale):** its "Auto-run ruff" hook section still
  describes the original ruff plan; the top status box correctly records the
  ruff→black swap (AppLocker blocks ruff's native binary). Body vs status box
  disagree — harmless, but fix the ruff section if that file is kept.
- **Docs:** `AGENTS.md` "Claude Code tooling" MCP bullet rewritten to cover both
  harnesses + the `_comment` key; date line bumped. `CLAUDE.md` unchanged by
  design (one-line `@AGENTS.md` import — its content tracks AGENTS.md
  automatically).

## Suggested next steps

1. **Commit the work** — everything above is uncommitted. Suggest splitting:
   (a) market/SSL/charts, (b) error-shape hardening, (c) Databricks backend +
   docs, (d) Claude Code + Copilot tooling (`.claude/`, `.mcp.json`,
   `.vscode/mcp.json`, `CLAUDE.md`, `setup_fixes.md`, AGENTS.md/handover updates).
2. **M2 milestone** (per README): full committee vote (votes/veto currently
   stored but unenforced), parallel analyst fan-out.
3. Optional: full (non-simple) committee run on Databricks to see data-tool
   grounding end-to-end (spends Databricks tokens, not Playground).
4. Playground quota resets monthly — backend can be switched back via env/UI.
