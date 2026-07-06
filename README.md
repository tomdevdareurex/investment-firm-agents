# investment-firm-agents

A buy-side **investment firm simulated as a team of orchestrated LLM agents** — credit
and equity analysts, rates/FX/swaps desks, economists, a quant, a risk function,
compliance, a devil's advocate, a PM, and a CIO — that debate a question and produce a
structured **Investment Committee memo** with a recommendation.

It runs on the **Deutsche Börse AI Playground API** (one endpoint, many model families)
and doubles as a hands-on way to learn agent **orchestration** patterns.

> **Decision-support only.** This project produces analysis and a recommendation for a
> human to act on. It does **not** execute orders, connect to brokers/exchanges/wallets,
> or trade automatically. Nothing here is investment advice.

---

## Status

| Milestone | What it delivers | State |
| --- | --- | --- |
| **M0** | Repo scaffold, LLM client, cost tracking, smoke test, web-search probe | **done** |
| **M1** | `Agent`, schemas, orchestrator, tools, roster | **done** |
| **M1.5** | Free data layer (yfinance/ECB/EDGAR/World Bank), planner, memory, profiles | **done** |
| **M1.6** | Tests + FakeLLM fixture, preview web UI, ARCHITECTURE.md | **done (this change)** |
| M2 | Full committee vote, parallel fan-out, GUI "Run" wiring | planned |
| M3 | Embeddings memory + post-mortem, notebooks | planned |

---

## Setup (DBAG Windows work laptop)

This machine has corporate AppLocker + Zscaler. Run pip as a module (the `pip.exe` shim
is blocked) and use a project-local virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .           # core
.venv\Scripts\python.exe -m pip install -e ".[data]"   # data tools (yfinance etc.)
.venv\Scripts\python.exe -m pip install -e ".[api]"    # web UI (FastAPI + uvicorn)
.venv\Scripts\python.exe -m pip install -e ".[dev]"    # tests + notebooks
.venv\Scripts\python.exe -m pip install -e ".[databricks]"  # optional 2nd LLM backend
.venv\Scripts\python.exe -m pip install -e ".[openbb]"      # optional OpenBB tools (yield curve, options, CPI; AGPLv3)

copy .env.example .env   # then paste your AI Playground key
```

Get the key from **GET API KEY** on the
[DevPortal AI Playground](https://devportal.deutsche-boerse.de/ai-playground) page.

**Zscaler / SSL:** `AI_PLAYGROUND_VERIFY_SSL` defaults to `false` (Zscaler-friendly).
The first request of a session can take ~10 s (tunnel cold-start); the default timeout
covers it.

---

## Run a committee

```powershell
# Full agentic run (spends tokens — uses the default "balanced" profile)
investment-firm "Should we increase duration in the EUR rates book?"

# Cheaper: simple mode (3 fixed analysts, no planner/tools)
investment-firm "Is AAPL fairly valued?" --simple

# Premium profile (more powerful models)
investment-firm "What is the outlook for EM credit?" --profile premium

# Slow down between calls to stay under tokens-per-minute limits
$env:IFA_CALL_PAUSE = "2"
investment-firm "Assess EUR HY spread risk"
```

Available profiles: `budget` | `balanced` (default) | `premium`. Override the profile
globally with `IFA_PROFILE=budget` in `.env`.

---

## LLM backend switch (Playground ↔ Databricks)

Two interchangeable backends serve every LLM call; core code never knows which
one is active. Useful when the Playground monthly token quota is exhausted.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[databricks]"
databricks auth login --host https://<your-workspace-host>   # OAuth / CLI profile, no PATs

$env:IFA_LLM_BACKEND = "databricks"    # default: playground
investment-firm "Is AAPL fairly valued?" --simple
```

Or switch at runtime in the web UI ("LLM backend" dropdown, backed by
`GET/POST /api/backend`).

- **Model names stay logical** (Playground-style) in `firm.yaml`; on Databricks
  they map mechanically (`claude-4.6-opus` → `databricks-claude-opus-4-6`,
  `gpt-5.4` → `databricks-gpt-5-4`), validated against the live endpoint list.
  Overrides: `IFA_DBX_MODEL_MAP` (JSON) and `IFA_DBX_DEFAULT_MODEL` (fallback).
- **No web search on Databricks** — agents ground via the data tools only; the
  grounding gate and citation rules are unchanged (no fake web sources).
- Function tools work (OpenAI format, verified live); costs are tracked as raw
  tokens with a unit-less weight.

---

## Web UI

```powershell
.venv\Scripts\python.exe -m pip install -e ".[api]"
.venv\Scripts\python.exe -m uvicorn investment_firm.interfaces.web.app:app
# open http://127.0.0.1:8000
```

The **Preview (free)** button resolves which roles and models would run for your
question and profile — zero LLM calls, zero token spend.

The **Run (spends tokens)** button is now live. After a confirmation dialog it
POSTs to `/api/runs`, then polls every 3 seconds until the committee finishes.
Results are shown in five tabs:

- **Memo** — recommendation badge (BUY/SELL/HOLD/AVOID) and the CIO summary.
- **Reasoning** — one card per analyst showing role, model, stance, conviction,
  full rationale text, key risks list, and evidence/source items. This is the
  "explain the logic" view.
- **Briefing** — the research librarian's sourced briefing packet (full mode only;
  skipped in simple mode).
- **Sources** — deduplicated source list from the briefing and every analyst's
  evidence field.
- **Costs** — per-call token/cost table plus any warnings (JSON-fallback analysts,
  budget limit reached).

Runs respect `--profile` and `--simple` (passed via the UI controls) and the
`IFA_CALL_PAUSE` env variable slows inter-call pacing to stay under
tokens-per-minute limits.

### Market data cache

The web API now exposes chart-ready Yahoo Finance history:

```text
GET /api/market/price-history?ticker=AAPL&period=1y&interval=1d
```

Responses include OHLC and volume arrays suitable for charting, plus a `cache`
metadata block showing whether saved fetched data was used. The local SQLite
cache defaults to `.cache/investment_firm/market_data.sqlite` and is ignored by
git. Override it with `INVESTMENT_FIRM_MARKET_CACHE` for tests or a custom data
directory. Use `force_refresh=true` to bypass saved data, or `cache=false` to
disable reads/writes for one request.

This cache is for research UX, reproducibility, and avoiding repeated provider
calls. It must not be used for execution. Any separate execution system outside
this app would need independent real-time market-data validation, compliance
controls, and human approval.

---

## CLI (M0 utility commands)

```powershell
.venv\Scripts\python.exe -m investment_firm --models          # list available models
.venv\Scripts\python.exe -m investment_firm --tokens          # monthly token budget
.venv\Scripts\python.exe -m investment_firm --smoke           # end-to-end smoke (few tokens)
.venv\Scripts\python.exe -m investment_firm --probe-websearch gemini-2.5-flash
```

---

## Tests

```powershell
# Default — offline only (no network, no tokens):
.venv\Scripts\python.exe -m pytest

# Opt-in live smoke (spends a few tokens):
.venv\Scripts\python.exe -m pytest -m live
```

The `FakeLLM` fixture in `tests/conftest.py` monkeypatches `client.chat` with
scriptable canned responses so the full agent/orchestrator stack is testable offline.
241 offline tests pass; the live suite is opt-in.

Memo trust: analyst views carry a `grounded` flag (≥1 successful tool call or
real web citation required — otherwise an "UNVERIFIED" key risk is forced),
failed tools surface as "DATA GAP" risks, and real web-search source URLs
(Claude + Gemini citations) appear as clickable links in the web UI's Sources
tab and per-analyst cards.

---

## Web search (per-model capability — confirmed 2026-07-02)

| Family | `webSearch` | Used in committee runs | Notes |
| --- | --- | --- | --- |
| **Claude** | `true` | Yes | Native `web_search_20250305` tool merged alongside function tools. Grounds (live-verified). |
| **Gemini** chat | `true` | Yes | `web_search_options: {}` — grounds (live-verified). The old boolean flag was a no-op. |
| **GPT** | `false` | No | Not supported on this gateway. Dropped from budget/balanced WORKER tiers; JSON output enforced via `response_format` where GPT is still used (premium, pins). |
| **Kimi, o4-mini** | `false` | No | Not supported. |

Web search is enabled per-agent (research librarian and each analyst) when the
role's model is Claude or Gemini **and** the profile's `web_search_max_uses`
setting in `firm.yaml` is greater than 0. Setting it to 0 disables web search
entirely for that profile, regardless of model family.

Full confirmed findings table and probe instructions: see
[docs/ARCHITECTURE.md — Per-model web search](docs/ARCHITECTURE.md).

---

## Architecture

For a full description of the layer diagram, the run pipeline, firm.yaml contract,
Playground quirks, and testing philosophy, see
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

Quick layout:

```
src/investment_firm/
  llm/        config, models, utils, costs, client (no core knowledge)
  core/       roster, planner, agent, orchestrator, memory, schemas, tools
  interfaces/ cli.py, web/app.py + static/
  config/     firm.yaml  (roles / tiers / profiles / committee rules)
tests/        all offline by default; FakeLLM fixture; live marker opt-in
docs/         ARCHITECTURE.md
```

The package version and DISCLAIMER live in `src/investment_firm/__init__.py`.
Every memo carries the disclaimer; the CLI prints it before token-spending commands;
the web UI footer displays it from `GET /api/health`.
