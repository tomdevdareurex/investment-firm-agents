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

Quick path (everything except the heavy `forecast` extra):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[data,api,dev,databricks,openbb]"
copy .env.example .env   # then paste your AI Playground key
```

Or pick extras one by one:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .           # core
.venv\Scripts\python.exe -m pip install -e ".[data]"   # data tools (yfinance etc.)
.venv\Scripts\python.exe -m pip install -e ".[api]"    # web UI (FastAPI + uvicorn)
.venv\Scripts\python.exe -m pip install -e ".[dev]"    # tests + notebooks
.venv\Scripts\python.exe -m pip install -e ".[databricks]"  # optional 2nd LLM backend
.venv\Scripts\python.exe -m pip install -e ".[openbb]"      # optional OpenBB tools (yield curve, options, CPI; AGPLv3)
.venv\Scripts\python.exe -m pip install -e ".[forecast]"    # optional TimesFM 2.5 price forecast (CPU torch, ~1 GB)

copy .env.example .env   # then paste your AI Playground key
```

The `forecast` extra pulls in `torch`; on a CPU-only laptop install the CPU wheel
first to avoid the CUDA download:
`.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu`
then the extra. Without it the web forecast endpoint still answers with the
random-walk baseline cone only (`is_model: false`), and the `forecast_quantiles`
tool is not advertised to the agents.

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

$env:IFA_LLM_BACKEND = "databricks"    # default: databricks ("playground" needs Playground-served models in firm.yaml)
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
Results are shown in tabs:

- **Memo** — recommendation badge (BUY/SELL/HOLD/AVOID), the plain-language CIO
  summary, the committee vote table and (premium profile) the CIO second opinion.
- **Reasoning** — one card per analyst showing role, model, stance, conviction,
  full rationale text, key risks list, and evidence/source items. This is the
  "explain the logic" view.
- **Briefing** — the research librarian's sourced briefing packet (full mode only;
  skipped in simple mode).
- **Sources** — deduplicated source list from the briefing and every analyst's
  evidence field.
- **Costs** — per-call token/cost table plus any warnings (JSON-fallback analysts,
  budget limit reached).

Below the form, the **Market Charts** panel plots cached yfinance candles with
indicator overlays and a technical summary; **Force refresh** bypasses the price
cache, **Forecast cone** overlays the TimesFM / baseline quantile cone (see
[Forecast cone](#forecast-cone-timesfm-optional)).

Runs respect `--profile` and `--simple` (passed via the UI controls) and the
`IFA_CALL_PAUSE` env variable slows inter-call pacing to stay under
tokens-per-minute limits.

### Investment horizon

The **Investment horizon** radio next to the question (short / medium / long)
does two things:

- It re-targets the Market Charts panel: short = `1y` of daily bars, medium =
  full history in weekly bars, long = full history in monthly bars. You can still
  change the period/interval selects afterwards.
- It is sent with **Run** and appended to the question every agent sees
  ("Investment horizon: Long term (3+ years) … prefer monthly data …"), so the
  analysts, debate and CIO frame their views for that horizon. The memo shows the
  horizon as a badge.

CLI: `investment-firm "<question>" --horizon long` (default `short`).

### Download the HTML report

When a run finishes, **Download report (HTML)** appears next to the result
header (`GET /api/runs/{id}/report.html`). From the CLI use
`--report PATH`, e.g. `investment-firm "<question>" --report ic-report.html`.

The report contains every tab: the plain-language memo (headline, summary, why,
what could go wrong, what to watch, confidence), each specialist's view, the
bull/bear debate, the research briefing, sources, warnings and costs, followed by
a glossary of the jargon actually used and a "How the numbers are calculated"
section. It is one self-contained file: inline CSS and SVG, **no scripts**, no
remote assets, so it opens offline and prints cleanly.

### Portfolio analytics

Upload a portfolio under **Portfolio (optional)** in the question form and click
**Analyse portfolio — backtest + risk (free)**. Accepted formats (max 50
positions, 100 KB):

- CSV `ticker,weight` (fractions or percent) or `ticker,quantity[,price]` — see
  [docs/examples/portfolio_sample.csv](docs/examples/portfolio_sample.csv);
  `,` or `;` delimiters.
- JSON `{"positions": [{"ticker": "SPY", "weight": 0.6}, …]}` or a bare list.

Controls: history window (`auto` follows the horizon: 1y / 5y / max), benchmark
(default `SPY`), rebalancing (none / monthly / daily), risk-free rate and which
rule-based strategies to backtest.

The analysis is **free (no tokens)**: prices come from the cached yfinance
endpoint and everything is computed locally — total return, CAGR, volatility,
historical/parametric VaR, Expected Shortfall, maximum drawdown with dates,
Sharpe, Sortino, Calmar, beta / correlation / tracking error vs the benchmark,
per-position contribution, concentration and correlations, buy-and-hold vs
rebalanced comparison, and strategy overlays. A separate portfolio HTML report
can be downloaded.

**Ask for suggestions (spends tokens)** makes a single advisor LLM call
(`IFA_ADVISOR_MODEL`, default `claude-5.5-opus`) over a compact digest of the
analysis, optionally using the latest finished committee run as market context.
It describes options and trade-offs only — decision-support, never an
instruction to trade. Analyses live in memory and are lost on server restart.

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

### Forecast cone (TimesFM, optional)

```text
GET /api/market/forecast?ticker=AAPL&period=1y&horizon_days=20
```

Returns median (`q50`) + 10/90 % quantile paths (`q10`/`q90`) for the next
`horizon_days` business days (1–60), with `dates`, `last_close`, `as_of` and a
`summary` (end-of-horizon median % and 10–90 % range). With the `forecast` extra
installed the cone comes from Google TimesFM 2.5 200M (Apache-2.0 weights,
loaded lazily on first call) and `is_model` is `true`; the historical-volatility
random-walk baseline is always included for comparison and is all you get
without the extra. `/api/health` reports `forecast_available`.

In the Market Charts panel tick **Forecast cone** to overlay it on the current
chart as dashed lines anchored at the last close. The badge next to the label
shows the engine (**TimesFM** or **baseline**); the horizon radio sets the
length (short = 20, medium/long = 60 business days); only the `1d` interval is
supported because forecast dates are business days. This is separate from
**Force refresh**, which just bypasses the price cache and re-downloads candles.
When TimesFM is installed the same numbers reach analysts and the consultant
through the `forecast_quantiles` tool. A quantile cone is a statistical range,
not a prediction or a trade signal — treat it as one more input to the memo.

#### ARIMA(1,1,1) and ARIMA-GARCH(1,1) cones

```text
GET /api/market/forecast?ticker=^GSPC&horizon_days=20&method=arima
GET /api/market/forecast?ticker=^GSPC&horizon_days=20&method=arima_garch
```

`method` is `timesfm` (default, the cone above), `arima` or `arima_garch`. Both
econometric methods fit an ARMA(1,1) to log returns `r_t = Δlog P_t`, i.e. an
ARIMA(1,1,1) on the log price, by Gaussian maximum likelihood (numpy + scipy,
`.[data]` extra, no network):

* mean `r_t = μ + φ r_{t-1} + θ ε_{t-1} + ε_t`
* variance: constant `σ²` for `arima`; for `arima_garch`
  `σ²_t = ω + α ε²_{t-1} + β σ²_{t-1}` (GARCH(1,1), fitted jointly with the mean,
  `α + β < 1`).

The cone is Gaussian on the log price: the k-step variance of the cumulative
return is `Σ Ψ²_{k-i} E[σ²_{T+i}]` (ARMA ψ-weights), so with GARCH it starts at
today's conditional volatility and decays towards the unconditional level. The
payload adds `model_params` (μ in % per bar, φ, θ, and σ or ω/α/β/persistence),
`fit` (log-likelihood, AIC, BIC, n, converged, `warnings`) and `step_vol_pct`
(forecast one-bar volatility per step). `fit.warnings` flags weakly identified
ARMA terms (φ ≈ -θ, common on index returns) and IGARCH fits (α + β at the
bound, e.g. weekly data spanning the 2020 crash — no unconditional vol is
reported then and the cone keeps widening). In the Market Charts panel tick **ARIMA(1,1,1)**
for the orange cone; tick **+ GARCH(1,1)** to switch its error variance to
GARCH (this also ticks ARIMA; unticking ARIMA clears GARCH). It is independent
of the blue **Forecast cone** so the two can be compared.

### Free alt-data tools (keyless)

Three read-only tools were added as substitutes for paid congressional/lobbying
data vendors, all backed by primary government sources with no API key:

| Tool | Source | What it returns |
| --- | --- | --- |
| `get_gov_contracts` | USAspending.gov | Recent federal awards to a recipient name |
| `get_lobbying` | Senate LDA | Quarterly lobbying filings for a client/registrant |
| `get_insider_trades` | SEC EDGAR full-text search | Recent Form 4 filings for a ticker/company |

### Committee vote and CIO second opinion

After the debate the orchestrator tallies a weighted stance vote across the
analyst views (`core/vote.py`; weights/veto from `firm.yaml`, risk veto needs
conviction ≥ `committee.veto_min_conviction`). The tally is shown in the memo and
handed to the CIO as context, not as a binding rule. On the `premium` profile
(`cio_cross_check: true`) a second model from a different family reviews the CIO
ruling and the memo shows whether it agrees, plus up to three concerns — advisory
only.

### Evaluated and skipped

- **QuiverQuant** — paid API (USD 30–250/month) and the ToS forbids scraping;
  replaced by the free primary sources above. Live congressional trades have no
  free feed and remain out of scope.
- **liquid.trade** — leveraged-perps DEX aggregator; only a trade-scoped OAuth
  MCP / Discord-gated REST exists. No free data API, and connecting would cross
  the hard "no broker/exchange connectivity" boundary.
- **TimesFM 3.0 weights** — non-commercial licence; the 2.5 Apache-2.0 weights
  are used instead.

### Research notebooks

The notebooks live under `notebooks/backtest/<strategy>/` and share their data loading,
backtest engine and statistics through [notebooks/backtest/bt_common.py](notebooks/backtest/bt_common.py).
They need the `.[data,dev]` extras (plotly is in `dev`), cache Yahoo data under `.cache/notebooks/`,
are research only and spend no LLM tokens.

[notebooks/backtest/sma/sma_trend_backtest.ipynb](notebooks/backtest/sma/sma_trend_backtest.ipynb) backtests a
price-vs-SMA timing rule on SPY. The rule holds SPY when the close is above its
SMA and T-bills (`^IRX` accrual, or the `BIL` ETF) otherwise. `REBALANCE` limits checks to the
last close of each week, month, quarter or year (`daily` = every close). Each signal is decided at
the close and filled at the next open, and the notebook reports per-switch costs, the
look-ahead variant for comparison, a window/cost sweep and crisis sub-periods.

[notebooks/backtest/sma/sma200_regime_analysis.ipynb](notebooks/backtest/sma/sma200_regime_analysis.ipynb) asks *why* the
SMA200/monthly version works. Using the same timing, it tests whether the regime predicts the next
month's excess return over T-bills (t-test, Newey-West, block bootstrap), across sub-periods back to
1934 (S&P 500 price from Yahoo plus Shiller dividends before 1988, `^SP500TR` after; FRED `TB3MS`
T-bills before 1960). It also breaks down where the Sharpe gain comes from and runs a placebo test.

[notebooks/backtest/timesfm/timesfm_forecast_backtest.ipynb](notebooks/backtest/timesfm/timesfm_forecast_backtest.ipynb)
asks TimesFM 2.5 (through the app's `forecast_tools` loader) for SPY's return distribution to the next
month-end at every month-end since 1997, using only data up to that close. It scores the forecasts first
(hit rate vs always-up, rank IC, decile calibration, pinball-loss skill vs a random walk and ARIMA) and
then backtests four rules (median above T-bills, probability threshold, left-tail filter, median plus
SMA200) on the same engine against SMA200, ARIMA, momentum and a random-timing placebo. It splits the
results at the model's release date because TimesFM may have seen S&P 500 history in pre-training.
It needs the `forecast` extra; the first run computes ~350 TimesFM and ARIMA forecasts on CPU (~25 min)
and caches them under `.cache/notebooks/timesfm/`.

A structured strategy search lives next to these notebooks: [PLAN.md](notebooks/backtest/PLAN.md)
(Stage 1: frozen success metric, dev 1934-89 / validation 1990-2009 / holdout 2010+ on a long S&P 500
total-return proxy, shared `bt_*` modules with tests in `notebooks/backtest/checks/`) and
[PLAN-stage2.md](notebooks/backtest/PLAN-stage2.md) (Stage 2: S02-S10, one folder per family:
`macro/`, `volatility/`, `trend/`, `seasonality/`, `fundamentals/` (SEC EDGAR), `ml/`, `ensemble/`).
Every strategy passes a truncation look-ahead test before backtesting, chooses its variant on the
development period only, and every variant is logged in
[registry.csv](notebooks/backtest/registry.csv) / [REGISTRY.md](notebooks/backtest/REGISTRY.md) for the
deflated-Sharpe trial count. Result so far: none of the ten ideas beats SMA200 monthly under the frozen
criteria. Each notebook is generated by its `build_sXX.py` (`--execute` runs it).

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
