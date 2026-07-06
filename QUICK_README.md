# Quick README — investment-firm-agents

A buy-side investment firm simulated as a team of orchestrated LLM agents on the
Deutsche Börse AI Playground gateway. Analysts research an investment question
(with optional web search + market-data tools), senior roles challenge them, and
a Head of Investments issues a structured committee memo (stance, conviction,
risks, evidence, sources).

**Decision-support only.** This project never executes trades, never connects to
any brokerage or order system, and its output is not investment advice.

## Install (Windows, AppLocker-safe)

AppLocker blocks `pip.exe` shims — always go through `python.exe -m`:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[data,api,dev,databricks,openbb]"
```

Extras: `data` = yfinance/pandas (market data), `api` = FastAPI/uvicorn (web UI),
`dev` = pytest/jupyter, `embed` = embeddings memory (M3, not needed yet),
`databricks` = second LLM backend (databricks-sdk), `openbb` = extra market-data
tools — Treasury yield curve, options summary, monthly CPI (auto-enabled when
installed; AGPLv3, local/personal use). Drop any extra you don't need.

## Configure

Create `.env` at the repo root (never commit it):

```
AI_PLAYGROUND_API_KEY=<your key>
```

Committee runs spend tokens on the gateway. Previews, the market endpoint, and
the Charts panel are free.

### LLM backend: AI Playground (default) or Databricks

When the Playground token quota is exhausted, switch to Databricks model serving:

```bat
.venv\Scripts\python.exe -m pip install -e ".[databricks]"
databricks auth login --host https://<your-workspace-host>
```

Auth is CLI-profile/OAuth only (env `DATABRICKS_HOST`/`DATABRICKS_TOKEN` →
`~/.databrickscfg` → OAuth). No PATs, no keys in `.env`.

Switch backends either way:

- **Env**: `set IFA_LLM_BACKEND=databricks` (default `playground`).
- **Web UI**: the "LLM backend" dropdown in the run form
  (`GET/POST /api/backend`) — takes effect immediately for that server.

Model names stay logical (Playground-style) everywhere; on Databricks,
`claude-4.6-opus` maps mechanically to `databricks-claude-opus-4-6`. Override
with `IFA_DBX_MODEL_MAP` (JSON map) or `IFA_DBX_DEFAULT_MODEL` (fallback for
unmapped GPT/Gemini/etc. names).

**Caveat**: Databricks has **no web search** — agents ground via the data
tools only (yfinance/ECB/EDGAR/World Bank); the grounding gate and citations
stay intact, no fake web sources. Costs are tracked as raw tokens (unit-less
weight).

### Corporate TLS (Zscaler) for market data

Yahoo Finance fetches verify TLS by default. Behind Zscaler inspection choose one:

1. **Preferred — CA bundle** (verification stays on):
   `set REQUESTS_CA_BUNDLE=C:\Users\wn686\corp-ca.pem` (or `CURL_CA_BUNDLE`).
2. **Fallback — explicit opt-out**:
   `set INVESTMENT_FIRM_MARKET_VERIFY_SSL=false` (mirrors `AI_PLAYGROUND_VERIFY_SSL`).

Verification is never disabled silently — only when that env is explicitly false.
A CA bundle env always wins over the toggle.

## Run

### Web UI (uvicorn)

```bat
.venv\Scripts\python.exe -m uvicorn investment_firm.interfaces.web.app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 — Committee Preview (free), Run (spends tokens), and
the **Market Charts** panel (candlesticks + volume + SMA 20/50, research only,
not trade signals). Direct endpoint:

```
GET http://127.0.0.1:8000/api/market/price-history?ticker=AAPL&period=1y&interval=1d
```

Query params: `period` (1d…max), `interval` (1d|1wk|1mo), `force_refresh`,
`cache`, `ttl_seconds`. Responses are cached in SQLite
(`.cache/investment_firm/market_data.sqlite`, override with
`INVESTMENT_FIRM_MARKET_CACHE`).

### CLI committee runs (spend tokens)

```bat
.venv\Scripts\python.exe -m investment_firm.interfaces.cli "Should we increase EUR duration?"
.venv\Scripts\python.exe -m investment_firm.interfaces.cli --simple "Same question, 3 fixed analysts"
.venv\Scripts\python.exe -m investment_firm.interfaces.cli --profile premium "Bigger models"
```

### Tests

```bat
.venv\Scripts\python.exe -m pytest -q          & offline suite (no network, no tokens)
.venv\Scripts\python.exe -m pytest -m live     & opt-in: real gateway calls, spends tokens
```
