# investment-firm-agents — Technical Summary

_Snapshot: 2026-10-23 · package version `0.4.0` · Python ≥ 3.9_

A buy-side investment firm simulated as a team of orchestrated LLM agents. A question
(e.g. *"Should we increase duration in the EUR rates book?"*) goes through a research
briefing, a set of specialist analysts, a bull/bear dhttp://127.0.0.1:8000ebate, a weighted committee vote
and a CIO ruling. The output is a structured **Investment Committee memo**.

> **Decision-support only.** The system never executes orders and never connects to
> brokers, exchanges or wallets. Every memo, CLI output and web page carries the
> `DISCLAIMER` from [`investment_firm/__init__.py`](src/investment_firm/__init__.py).

Further reading: [README.md](README.md) (setup and usage), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
(the ~10-minute architecture tour), [AGENTS.md](AGENTS.md) (dense agent-facing reference) and
[handover.md](handover.md) (session log).

---

## 1. Run pipeline

`run_committee(question, *, profile, simple, horizon, user_context, portfolio_id)` in
[`core/orchestrator.py`](src/investment_firm/core/orchestrator.py) returns `(Memo, RunTracker)`:

```
question + horizon ─► frame_question()        ("Investment horizon: …" marker)
  1. Briefing      research_librarian agent + data tools  ─► RunMemory briefing
                   (an uploaded portfolio, if any, is prepended as highest-trust context)
  2. Plan          CIO planner picks and orders analysts (core + optional specialists)
  3. Analysts      sequential tool-using Agent loops (max_steps 3); each sees the briefing
                   and earlier colleagues' findings
  4. Debate        alternating Bull / Bear turns, then a CIO judge (max_debate_rounds 1/2/3)
  5. Vote          weighted tally + veto (core/vote.py)
  6. Synthesis     CIO ─► Synthesis(recommendation, headline, summary, key_reasons,
                   main_risks, what_to_watch, confidence 0–5), plain-language rules
  7. Cross-check   second opinion from a different model family (premium only, advisory)
  ─► Memo ─► build_run_result() ─► CLI / web UI tabs / standalone HTML report
```

`simple=True` skips the briefing, planner, tools, web search, debate and vote. It runs a fixed
equity/credit/rates trio with `max_steps 1`, which makes it a cheap dry run.

**Resilience ladder** (in [`core/agent.py`](src/investment_firm/core/agent.py)), in order:
1. On an API error, retry once without tools.
2. If the answer is truncated, retry once at 2× `max_tokens`.
3. Make one tool-free JSON **repair** call. This also happens when the answer is empty but tool results exist.
4. Make one call on a **fallback model** from the same or nearest tier (`roster.fallback_model_for`).
5. As a last resort, return an explicit ERROR `AnalystView` with a `FAILURE REASON`.

API errors go into `key_risks` and never into the rationale. Synthesis and the debate judge have
their own retry-and-salvage paths.

**Grounding gate:** a view with no successful tool call and no citation is marked
`grounded=False` and gets an `UNVERIFIED` risk. Failed tools add `DATA GAP`, and stale `as_of`
dates are flagged.

---

## 2. Package layout and layering

```
src/investment_firm/
  llm/         LLM access: config → models → backends → utils → costs → client
  core/        roster, planner, prompts/, agent, debate, vote, cross_check,
               orchestrator, consultant, portfolio_advisor, memory, schemas,
               events, errors, horizon, glossary, tools/
  data/        pure, network-free compute (risk, indicators, backtest, technicals,
               forecast, arima_garch, portfolio)
  interfaces/  cli.py, report/ (payload + HTML, no FastAPI), web/ (FastAPI + static UI)
  config/      firm.yaml, costs.yaml, endpoints.yaml (shipped as package data)
  endpoints.py loader for endpoints.yaml (https-only, IFA_ENDPOINTS_CONFIG override)
```

The package has 69 Python modules. Import rules:

- `llm/` never imports `core/`.
- `data/` never imports `core/` or `interfaces/`. This is enforced by `tests/test_data_layout.py`.
- `core/risk.py`, `core/indicators.py` and `core/technicals.py` are re-export shims over `data/`.
- Format conversion and model-family branching live **only** in `llm/`. `core/` always passes
  OpenAI-format structures.

---

## 3. LLM layer (`llm/`)

| Module | Role |
| --- | --- |
| `config.py` | Lazy env/.env accessors (never module constants) so tests can monkeypatch them. |
| `models.py` | Playground model lists, family helpers, `is_reasoning_model`, and the corpus of 53 chat + 2 embedding Databricks endpoints. |
| `backends.py` | Backend registry. **Databricks is the default**; the alternative is the Deutsche Börse AI Playground. Precedence: `set_backend()` → `IFA_LLM_BACKEND` → databricks. Also provides capability checks and `map_model`. |
| `databricks_backend.py` | Lazy `databricks-sdk` OpenAI adapter. Retries 408/409/429/5xx and timeouts with backoff, and recovers from `max_tokens` 400 errors. |
| `sanitize.py` | Balances tool-call/tool-result histories for strict Databricks endpoints. |
| `client.py` | Raw httpx Playground client. Hoists Claude system messages, converts to Anthropic tool format, injects web search, applies GPT JSON mode, and enforces a 4096 output floor for reasoning models. Also provides `stream_chat`. |
| `utils.py` | Format-agnostic `extract_text`, `extract_usage`, `extract_tool_calls`, citations, `finish_reason` and `is_truncated`. |
| `costs.py` | Backend-aware pricing from `costs.yaml` and the `RunTracker` (USD per direction, price source/basis/confidence, `would_exceed` + `reserve`/`release` budgeting). |

**Model mapping on Databricks:**
1. `databricks-*` names pass through unchanged.
2. Otherwise, `IFA_DBX_MODEL_MAP` (JSON) is checked.
3. Otherwise, the name is transformed mechanically (`claude-4.6-opus` → `databricks-claude-opus-4-6`).
4. The result is optionally checked against the live endpoint list.
5. If nothing matches, `IFA_DBX_DEFAULT_MODEL` is used.

Databricks has **no web search**. On the Playground, Claude gets the Anthropic web-search tool and
Gemini gets `web_search_options`; GPT and Kimi never get web search.

---

## 4. The firm: roster, profiles, prompts

[`config/firm.yaml`](src/investment_firm/config/firm.yaml) defines **27 roles** (13 core + 14 `optional: true`):

| Group | Roles |
| --- | --- |
| governance | cio, ic_chair, pm, compliance, devils_advocate |
| research | economist_short/medium/long, strategist, equity/credit/rates/technical/sentiment/news analysts, bull/bear researchers, fx_strategist |
| trading | rates_desk, equity_desk, swaps_desk, fx_desk |
| quant · risk · data | quant · market_risk, credit_risk, liquidity_risk · research_librarian |

**Profiles** map the tiers WORKER / SENIOR / AUTHORITY / HEAD to model seats:

| Profile | `run_token_budget` | Debate rounds | Web-search uses | CIO cross-check |
| --- | --- | --- | --- | --- |
| budget | 100k | 1 | 1 | no |
| balanced (default) | 300k | 2 | 3 | no |
| premium | 400k | 3 | 5 | **yes** |

All profiles set `fallback_on_error: true`.

**Seat rules:**
- Model names are Databricks-era logical names (e.g. `claude-5.5-opus`, `gemini-3.8-flash`, `gpt-5.6-terra`).
- `bull_researcher` and `bear_researcher` are pinned to `gpt-5.6-terra` and `claude-5.5-opus`.
- The librarian is pinned to the Claude family.

**Committee rules:**
- Tally rule: `weighted_majority_of_stance`, with the IC chair breaking ties.
- Vetoes: `compliance` and `market_risk`, each needing conviction ≥ 3.
- The CIO may override the vote.

**Prompts** ([`core/prompts/`](src/investment_firm/core/prompts)) are plain strings. A role body is
resolved in order: role body → department template → generic mandate. The JSON contract in
`prompts/base.py` is **frozen** because the agent parsers depend on it.

---

## 5. Tools and data

**Agent tools** ([`core/tools/`](src/investment_firm/core/tools)) are free and read-only. All URLs
come from `endpoints.yaml`.

- **16 data tools:**
  - Prices and indicators: `get_prices`, `get_indicators`, `compute_risk_metrics`, `run_backtest`, `run_strategy_backtest`.
  - Macro: `get_ecb_rate`, `get_worldbank_indicator`, `get_fred_series`.
  - Filings and fundamentals: `get_company_filing` (EDGAR), `get_av_overview`.
  - Sentiment and odds: `get_prediction_market_odds` (Kalshi → Manifold), `get_stocktwits_sentiment`, `get_reddit_sentiment`.
  - Keyless alt-data: `get_gov_contracts` (USAspending), `get_lobbying` (Senate LDA), `get_insider_trades` (EDGAR Form 4).
- **Optional:**
  - OpenBB (`.[openbb]`, AGPLv3): `get_yield_curve`, `get_options_summary`, `get_cpi`.
  - Forecast: `forecast_quantiles`. Uses TimesFM 2.5 when the `.[forecast]` extra is installed, otherwise a random-walk baseline. ARIMA and ARIMA-GARCH methods are also available.

**Pure compute** ([`data/`](src/investment_firm/data)):
- `risk.py`: VaR, Expected Shortfall, volatility, drawdown.
- `indicators.py`: a whitelisted stockstats catalogue. The same catalogue feeds the agents and the charts, so charts and agents always see identical indicators.
- `backtest.py`: four strategies with one-bar no-lookahead and trading costs.
- `forecast.py` and `arima_garch.py`: the baseline forecast cone and an ARMA(1,1)+GARCH(1,1) maximum-likelihood fit.
- `portfolio.py`: CSV/JSON parsing, equity curve with rebalancing, CAGR / Sharpe / Sortino / Calmar / VaR / ES / beta / TE / IR, diversification, strategy overlays.

---

## 6. Interfaces

**CLI** — `investment-firm "<question>" [--profile …] [--simple] [--horizon short|medium|long] [--chat] [--report PATH] [--stream]`.
It also offers `--models`, `--tokens`, `--smoke`, `--probe-websearch` and `--version`.

**Web** — FastAPI app (`uvicorn investment_firm.interfaces.web.app:app`) with a no-build static UI.

| Area | Endpoints |
| --- | --- |
| Meta | `GET /`, `/api/health`, `/api/profiles`, `/api/preview`, `GET/POST /api/backend` |
| Runs | `POST/GET /api/runs`, `GET /api/runs/{id}`, `…/events` (SSE), `POST …/chat` (consultant), `GET …/report.html` |
| Market | `GET /api/market/price-history`, `GET /api/market/forecast?method=timesfm\|arima\|arima_garch` |
| Portfolio | `POST /api/portfolio/analyze`, `GET /api/portfolio/{id}`, `…/report.html`, `POST …/suggest` (LLM advisor) |

**UI tabs:** Memo, Reasoning, Debate, Briefing, Sources, Costs, Consultant.

**UI features:**
- Interactive charts (vendored lightweight-charts) with indicator overlays, technical gauges and forecast cones.
- A portfolio panel with its own tabs.
- A horizon radio button.
- An LLM-backend dropdown.

Run registries are in-memory; portfolio analyses are capped at 50. Market data is cached in SQLite
under `.cache/investment_firm/`.

**Consultant** — a read-only quant Q&A agent over a finished run. It has a filtered tool
registry (≤ 4 steps), streams its final answer, and refuses trades and writes.

**Reports** — `interfaces/report/` renders self-contained HTML (no `<script>`, no remote assets,
inline SVG charts) for both committee runs and portfolio analyses.

---

## 7. Build, run, test

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[data,api,dev,databricks,openbb]"   # + ".[forecast]" for TimesFM (~1 GB torch)
copy .env.example .env      # Playground key / Databricks host+token
.venv\Scripts\python.exe -m uvicorn investment_firm.interfaces.web.app:app
.venv\Scripts\python.exe -m pytest -q        # offline only; live tests deselected via addopts
```

- **Tests:** 39 test files, **876 tests** (873 offline + 3 `live`).
  - Offline tests use the `FakeLLM` fixture in [`tests/conftest.py`](tests/conftest.py), which
    monkeypatches `llm.client.chat`. An autouse fixture pins the backend to `playground`.
  - `-m live` spends real tokens. Run it only on explicit request.
- **DBAG laptop notes:**
  - AppLocker blocks native binaries in user directories, so run tools as `python -m <tool>` (`black` works; the `ruff` binary does not).
  - Zscaler TLS inspection is the reason `AI_PLAYGROUND_VERIFY_SSL` defaults to `false`.

---

## 8. Conventions and guardrails

- No hardcoded URLs anywhere in `src/`. All URLs come from `config/endpoints.yaml`, and
  `tests/test_endpoints.py` greps for `https?://`. Scheme checks therefore use `urlsplit`.
- Config is read lazily (functions, not constants). Cost tests must call `costs.reload_costs()`.
- Agents always run in JSON mode, and the `JSON_CONTRACT` is frozen. Web citations become
  `Source` objects, deduplicated by URL, and links are rendered only after a scheme check.
- New UI code goes in `memo.js`, `portfolio.js`, `forecast.js` and `extras.css`, because `app.js`
  and `app.css` exceed the 800-line cap. These scripts load after `app.js`.
- Claude Code hooks block edits to `.env*` and auto-format edited `.py` files with black.
- Subagents in `.claude/agents/` include provenance-auditor, scope-compliance-guard and llm-cost-auditor.
- Larger changes are handed off as root-level plan files that follow the template in
  [planning.md](planning.md) and end with an "Execution status" checklist.

---

## 9. Repository map (outside `src/`)

| Path | Contents |
| --- | --- |
| [tests/](tests) | Offline pytest suite + `FakeLLM` fixture; live smoke test |
| [docs/](docs) | `ARCHITECTURE.md`, `examples/` (e.g. sample portfolio CSV) |
| [notebooks/backtest/](notebooks/backtest) | Research programme: `bt_*.py` helpers, per-theme notebooks (sma, timesfm, valuation, macro, ml, volatility, seasonality, …), `REGISTRY.md`/`registry.csv` trial registry, `PLAN*.md` |
| [scripts/](scripts) | Live probes (`probe_gemini_ws.py`, `probe_live_fixes.py`) |
| [prompts-models/](prompts-models) | Prompting analyses for Opus 5 / 5.5 and Fable 5 / 5.1 |
| [graphify-out/](graphify-out) | Knowledge graph of the codebase (`graphify query/path/explain`) |
| `planning*.md`, `handover.md`, `claude-fable-5.md` | Executor plans, session handover log, model-specific notes |
| `.claude/`, `.github/`, `.mcp.json` | Agent hooks/skills/subagents, Copilot instructions, MCP servers (context7, playwright) |

**Backtest research result** ([PLAN-stage2.md](notebooks/backtest/PLAN-stage2.md)):
- 34 registered trials were tested against a frozen primary metric with an SMA200 benchmark.
- **None of S01–S10 passed.** The closest was S10 (SMA200 + CAPE average).

---

## 10. Current status, known gaps, deferred work

**Done:**
- M0–M1.6: client, agents, tools, roster, planner, tests and web UI.
- Databricks backend with retries and model mapping.
- TradingAgents-style bull/bear debate, streaming and the consultant.
- Investment horizon, plain-language synthesis and HTML reports.
- Portfolio analytics, advisor and portfolio-aware runs.
- Seat fallbacks and truncation/JSON-repair hardening.
- **M2 committee vote + CIO cross-check.**
- TimesFM, ARIMA and GARCH forecasts.
- Keyless alt-data tools.
- Backtest research Stages 1–2.

**Test health (offline run, 2026-10-23): 859 passed, 14 failed.** The 2026-10-06 batch was
written without a shell and is now mostly verified. The failures have two root causes:

1. **`interfaces/report/html.py`** calls `_num(c.get('latency_s'), 1)` (line ~320), but `_num(value)`
   takes only one argument. This raises a `TypeError` in every committee HTML render (13 tests in
   `tests/test_report_html.py`, plus the CLI `--report` and `report.html` route).
2. **`tests/test_consultant.py::test_registry_is_exactly_the_readonly_subset`**: the consultant
   registry now also exposes the optional `forecast_quantiles`, and the test asserts the exact
   five-tool set.

**Known gaps and quirks:**
- The [README.md](README.md) status table is stale. It still lists M2 as "planned", and the intro
  still names the Playground as the main backend.
- About 60 files have uncommitted changes in the working tree.
- CI is not active. The workflow is staged in `.github/ci-placeholder.txt` and needs to move to `.github/workflows/ci.yml`.
- `max_parallel` exists in `firm.yaml` but is not read; analysts run sequentially.
- Field names for the alt-data tools (USAspending, Senate LDA, EDGAR full-text search) and the TimesFM API calls were written from memory and still need a live spot-check.
- The consultant system prompt lists 4 tools, but its registry exposes more.
- On Databricks there is no web search, so many views may be flagged `UNVERIFIED`.
- `gpt-6*` and `gpt-oss*` models are not yet classified as reasoning models, so they don't get the 4096 output floor.

**Deferred** (see [planning-forecast-altdata.md](planning-forecast-altdata.md)):
- (B) Extract a market-data package and route tools through the cache.
- (C) Split `datasources.py` into `providers/`.
- (F1–F3) Parallel analyst fan-out. This first needs thread-safe `RunTracker`/`RunMemory`.
- (E6) Forecast in the HTML report.
- M3: embeddings memory and post-mortems.