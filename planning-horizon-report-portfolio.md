# Investment Horizon, Plain-Language HTML Report & Portfolio Analytics — Implementation Plan

_Target repo: `investment-firm-agents`. Written for a cold-start executor LLM. All paths are relative to the repo root. Python package root: `src/investment_firm/`. Read `AGENTS.md` first — it is authoritative project memory._

## 0. Context

The web UI (`src/investment_firm/interfaces/web/static/index.html` + `app.js` + `charts.js`) lets a user type an investment question, run the multi-agent committee (`core/orchestrator.py::run_committee`) and read the result in 7 tabs (Memo / Reasoning / Debate / Briefing / Sources / Costs / Consultant). Today:

- There is **no notion of investment horizon**. The Market Charts panel defaults to `period=1y`, `interval=1d` (`index.html` `#chart-period` / `#chart-interval`); the agents get no horizon context.
- The final CIO result is a bare `(recommendation, summary)` tuple (`orchestrator._synthesize` / `_parse_synthesis` / `_salvage_synthesis`, prompt `_SYNTH_SYSTEM_TMPL`). The Memo tab shows only a badge plus a 3-5 sentence summary, often in trader jargon.
- The result can't be exported. The result dict that feeds every tab is built inline in `interfaces/web/runs.py::_run_worker` (≈ lines 105-215).
- There is **no portfolio support**. Single-ticker quant building blocks already exist and must be reused:
  - `data/risk.py`: `returns_from_prices`, `historical_var`, `parametric_var`, `expected_shortfall`, `annualized_vol`, `max_drawdown`, `risk_summary`. Positive numbers mean losses.
  - `data/backtest.py::run_strategy` (`STRATEGIES`: sma_crossover, macd_crossover, rsi_reversion, bollinger_reversion; one-bar shift, no lookahead).
  - `interfaces/web/market_data.py::get_price_history`, which provides yfinance prices with a SQLite cache and corporate SSL handling.

Goal: four workstreams.

- **A — Horizon selector.** Short / medium / long next to the question. It re-targets the Market Charts panel:
  - long → `max`/`1mo`
  - medium → `max`/`1wk`
  - short → unchanged `1y`/`1d`

  The horizon is also threaded through the API, into every prompt and onto the `Memo`.
- **B — Plain-language result + downloadable HTML report.** A richer CIO JSON contract (headline, summary, key reasons, main risks, what to watch, confidence) written for non-professionals. A self-contained HTML report covers every tab plus an auto-glossary and methodology, served at `GET /api/runs/{id}/report.html`.
- **C — Portfolio analytics.** The user uploads a portfolio (CSV/JSON) and clicks "Analyse portfolio — backtest + risk (free)". The app computes:
  - VaR, ES, volatility, max drawdown with dates, CAGR, Sharpe, Sortino and Calmar
  - beta, correlation and tracking error vs a benchmark
  - per-position contribution and concentration
  - buy-and-hold vs rebalanced backtests and rule-based strategy overlays

  It also gets its own downloadable HTML report. An optional token-spending "Ask for suggestions" button calls a CIO-style advisor seeded with the latest committee run as market context.
- **D — Tests, docs, CLI** (`--horizon`, `--report PATH`).

## 1. HARD CONSTRAINTS (do not violate)

1. **The analyst JSON output contract is FROZEN.** `core/prompts/base.py::JSON_CONTRACT` and the parsers in `core/agent.py` (`_extract_json_block`, `_salvage_fields`, `_to_view`, `_parse_or_none`) must not change. The horizon reaches analysts **only through the user message** (the framed question, §4A step 6), never by editing `JSON_CONTRACT` or `BASE_HEADER`. Only the **CIO synthesis** contract (`orchestrator._SYNTH_SYSTEM_TMPL`) changes in this plan. The debate judge contract (`{"stance","summary"}` in `core/prompts/debate.py::JUDGE_SYSTEM`) is unchanged.
2. **No URL literals in Python source.** `tests/test_endpoints.py::test_no_url_is_hardcoded_in_source` greps **every line of every `src/**/*.py`** for the regex `https?://`.
   - **Gotcha:** `url.startswith("https://")` or `("http://", "https://")` inside the report renderer FAILS that test.
   - Use `urllib.parse.urlsplit(url).scheme.lower() in {"http", "https"}`, or the regex literal `re.compile(r"^https?://", re.I)`. The literal text `https?://` does not match the test's pattern.
   - Static `.js` files are not scanned. `app.js` already uses `/^https?:\/\//i`.
   - Any new **external** URL goes in `src/investment_firm/config/endpoints.yaml` and is read via `investment_firm.endpoints.url(...)`. This plan needs none.
3. **Layering** (enforced by `tests/test_data_layout.py::test_data_package_does_not_import_core_or_interfaces`):
   - `src/investment_firm/data/` must never import `investment_firm.core` or `investment_firm.interfaces`. `data/portfolio.py` may import only stdlib, `data.risk`, `data.backtest` and `data.indicators`. pandas is allowed only lazily, inside the strategy-overlay function.
   - `llm/` never imports `core/`.
   - `core/` never branches on model family (`is_claude` / `is_gemini` …); it passes OpenAI-format messages only.
   - `interfaces/report/` must not import fastapi, so the CLI can use it without `.[api]`.
4. **No DOM HTML sinks in static JS.** `tests/test_web_market.py::TestChartsPanelStatic::test_charts_js_is_served_and_xss_safe` asserts `".innerHTML" not in` / `"insertAdjacentHTML" not in` `charts.js`. The same rule applies to `app.js` changes and the new `portfolio.js`, which gets the same test (§5).
   - All model/API text goes in via `textContent` / `createElement`, using the existing `el()`, `textBlock()`, `linkNode()`, `sourceItemNode()` helpers from `app.js`.
   - The existing `select.innerHTML = ''` / error-option lines in `app.js` (`loadProfiles`, `loadBackend`) are static strings. Don't add new ones; use `replaceChildren()`.
5. **Server-side HTML reports are XSS-safe.**
   - Every dynamic value goes through `html.escape(str(value), quote=True)`. No raw model text is interpolated into markup.
   - Links render as `<a href="...">` only when the scheme check of constraint 2 passes; otherwise they render as escaped plain text. Anchors get `rel="noopener noreferrer"`.
   - The report contains **no `<script>`**, no external CSS/fonts/images and no remote requests. CSS is inline in `<style>`; charts are inline `<svg>`.
6. **Decision-support only.**
   - Never add order execution, broker/exchange connectivity, or wording that instructs a trade. Do not write "execute", "place an order", "size the trade" or "buy now" in prompts, UI copy or reports.
   - The portfolio advisor describes *options and trade-offs* and never issues instructions.
   - `investment_firm.DISCLAIMER` must appear in every HTML report, every new API response (`"disclaimer"` key, like existing routes) and the portfolio panel UI.
7. **Config read lazily** via functions (env vars like `IFA_ADVISOR_MODEL` are read at call time, never as module constants), so tests can monkeypatch.
8. **Offline tests only.** Run `.venv\Scripts\python.exe -m pytest -q`. `live` is deselected by `addopts`. NEVER `-m live`, never `tests/test_smoke_live.py`, never a real CLI/web committee run, never real yfinance calls in tests (monkeypatch `interfaces.web.market_data.fetch_yfinance_price_history`).
9. **Tooling on this machine.** Format with `.venv\Scripts\python.exe -m black src tests`. The native ruff binary is AppLocker-blocked, so always use `python -m <tool>`. A Claude Code hook also auto-formats edited `.py` files.
10. **No git commits.** The user commits manually. Don't edit `.env*` (a hook blocks it).
11. **File size:** keep each file < 800 lines (target 200-400). If `app.js` (≈ 950 lines today) would exceed 800, put new UI code in `portfolio.js` / a new `report.js` rather than growing `app.js`.
12. **Every step keeps the suite green.** Run pytest after every numbered step in §4. If an existing test fails because of an intended contract change, update it exactly as §5 describes, and don't weaken unrelated assertions.

## 2. Current vs target

| Area | Current | Target |
|---|---|---|
| Horizon | none | `core/horizon.py::HORIZONS` (short/medium/long); radio group in the question form; `RunRequest.horizon`; `run_committee(horizon=...)`; framed question to every agent; `Memo.horizon` |
| Market Charts defaults | static `1y` / `1d` | follows the horizon: short `1y`/`1d`, medium `max`/`1wk`, long `max`/`1mo` (the user can still override the selects) |
| CIO output | `(recommendation, summary)` tuple, 3-5 sentences, jargon | `Synthesis` dataclass: recommendation, headline, summary, key_reasons, main_risks, what_to_watch, confidence; plain-language style rules |
| Memo schema | no horizon / structure fields | `Memo.horizon`, `headline`, `key_reasons`, `main_risks`, `what_to_watch`, `confidence` (all defaulted) |
| Result payload | dict built inline in `web/runs.py::_run_worker` | `interfaces/report/payload.py::build_run_result(memo, tracker, *, horizon)`, shared by web + CLI, plus `glossary`, `report_url`, `generated_at` |
| Export | none | `GET /api/runs/{id}/report.html` (attachment), "Download report (HTML)" button, CLI `--report PATH` |
| Glossary / methodology | none | `core/glossary.py::GLOSSARY`, `find_terms()`, `METHODOLOGY`; rendered in reports and the Memo tab |
| Portfolio | none | upload (CSV/JSON) → `POST /api/portfolio/analyze` → `data/portfolio.py::analyze_portfolio`; panel with tabs; `GET /api/portfolio/{id}/report.html`; optional `POST /api/portfolio/{id}/suggest` (spends tokens) |
| `data/backtest.run_strategy` | returns stats only | `return_curve=False` kwarg; when `True`, adds `equity` + `dates` keys (default output byte-identical) |

## 3. New / changed file layout

### New files

| File | Content |
|---|---|
| `src/investment_firm/core/horizon.py` | Pure strings/dataclass, no llm imports. `@dataclass(frozen=True) class Horizon: key, label, years_hint, chart_period, chart_interval, tool_lookback, portfolio_period, prompt_guidance`. `HORIZONS = {"short": ..., "medium": ..., "long": ...}`. `DEFAULT_HORIZON = "short"`. `HorizonError(ValueError)`. `resolve_horizon(name: Optional[str]) -> Horizon` (None/"" → default; unknown → `HorizonError`). `frame_question(question: str, horizon: str) -> str`. |
| `src/investment_firm/core/glossary.py` | `GLOSSARY: Dict[str, GlossaryEntry]` where `GlossaryEntry(term, aliases: tuple, plain: str, how_calculated: str)`. Terms: VaR, Expected Shortfall, max drawdown, annualised volatility, Sharpe ratio, Sortino ratio, Calmar ratio, CAGR, beta, correlation, tracking error, information ratio, SMA, EMA, RSI, MACD, Bollinger Bands, basis points, duration, credit spread, conviction, bull/bear case, rebalancing, buy-and-hold, benchmark, yield curve. `find_terms(*texts: str) -> List[GlossaryEntry]`: case-insensitive whole-word alias matching (`re.compile(r"\b" + re.escape(alias) + r"\b", re.I)`), deduplicated, in `GLOSSARY` order. `METHODOLOGY: List[Tuple[str, str]]` (title, plain explanation). Pure strings, no llm imports. |
| `src/investment_firm/data/portfolio.py` | Pure analytics (see §4C). stdlib + `data.risk` + `data.backtest`; pandas imported lazily only inside `strategy_overlays`. |
| `src/investment_firm/interfaces/report/__init__.py` | Re-exports `build_run_result`, `render_committee_report`, `render_portfolio_report`. |
| `src/investment_firm/interfaces/report/payload.py` | `build_run_result(memo, tracker, *, horizon="short", run_id="") -> dict`: the dict currently built in `web/runs.py::_run_worker`, moved here verbatim (including the `warnings` construction and `_FALLBACK_RISK`), plus new keys (§4B). No fastapi import. |
| `src/investment_firm/interfaces/report/_html.py` | Shared helpers: `_esc(v)`, `_link(url, label)`, `_page(title, body_html) -> str` (doctype, `<meta charset="utf-8">`, inline `<style>`), `_section(id, title, inner)`, `_table(headers, rows, num_cols=())`, `_badge(text, kind)`, `_list(items)`, `_svg_line(series: List[Tuple[str, float]], *, width=760, height=220, color, baseline=None, label) -> str` (inline polyline SVG with min/max/first/last axis labels; returns an escaped "(no data)" note for < 2 points), `_svg_multi_line(...)` for equity-vs-benchmark, `_pct(x, dp=2)`, `_num(x, dp=2)`, `_usd(x)`, `_glossary_section(entries)`, `_methodology_section()`, `_disclaimer_footer()`. |
| `src/investment_firm/interfaces/report/html.py` | `render_committee_report(result: dict) -> str` (§4B step 4). |
| `src/investment_firm/interfaces/report/portfolio_html.py` | `render_portfolio_report(entry: dict) -> str` (§4C step 6). |
| `src/investment_firm/interfaces/web/portfolio_data.py` | `load_portfolio_prices(tickers, period, *, benchmark) -> Dict[str, dict]` via `market_data.get_price_history(ticker, period, "1d")`; `payload_to_series(payload) -> List[Tuple[str, float]]`; `payload_to_ohlcv_frame(payload)` (same column construction as `market_data.attach_indicators`). |
| `src/investment_firm/interfaces/web/portfolio.py` | `APIRouter(prefix="/api/portfolio")`, in-memory `_analyses` registry + `threading.Lock`, routes (§4C step 4). |
| `src/investment_firm/core/portfolio_advisor.py` | `suggest(digest: dict, *, market_context: Optional[Memo], horizon: str, model: Optional[str], tracker: Optional[RunTracker]) -> dict` (§4C step 5). |
| `src/investment_firm/interfaces/web/static/portfolio.js` | Portfolio panel IIFE (§4C step 7). |
| `docs/examples/portfolio_sample.csv` | `ticker,weight` / `SPY,0.5` / `TLT,0.3` / `GLD,0.2` (not package data). |
| Tests | `tests/test_horizon.py`, `tests/test_glossary.py`, `tests/test_report_html.py`, `tests/test_portfolio_data.py`, `tests/test_web_portfolio.py` (§5). |

### Changed files

| File | Change |
|---|---|
| `interfaces/web/static/index.html` | horizon radio group; portfolio controls; download-report link; `#portfolio-panel`; `<script src="/static/portfolio.js">` **after** `app.js` and the chart library. |
| `interfaces/web/static/app.js` | `selectedHorizon()`, `ifa:horizon` event, horizon in run/preview requests, new `renderMemoTab`, download link, glossary block. |
| `interfaces/web/static/charts.js` | `HORIZON_CHART` map + `ifa:horizon` listener (inside the existing IIFE, because `loadChart` is IIFE-private). |
| `interfaces/web/static/app.css` | radio group, memo sections, portfolio panel, stat cards. |
| `interfaces/web/runs.py` | `RunRequest.horizon`; registry entry `horizon`; `_run_worker` calls `build_run_result`; `/report.html` route. |
| `interfaces/web/app.py` | `preview` gets a `horizon` query param; include the portfolio router; update the module docstring routes list. |
| `core/orchestrator.py` | `horizon` kwarg; framed question; `Synthesis` dataclass; new synthesis prompt; populate new Memo fields. |
| `core/schemas.py` | new `Memo` fields + `render()` lines. |
| `core/planner.py` | optional horizon hint line in the catalogue prompt (no signature change). |
| `core/debate.py` | **no code change needed.** It receives the framed question from `run_committee`. Verify only. |
| `interfaces/cli.py` | `--horizon`, `--report PATH`. |
| `data/backtest.py` | `run_strategy(..., return_curve: bool = False)`. |
| `pyproject.toml` | no change (no new dependencies). |

## 4. Ordered implementation steps

Run `.venv\Scripts\python.exe -m pytest -q` after **every** numbered sub-step. Work order: 4A → 4B → 4C → 4D.

### 4A — Horizon selector (GUI + API + prompts)

**A1. `core/horizon.py`** (new). Values:

| key | label | years_hint | chart_period | chart_interval | tool_lookback | portfolio_period |
|---|---|---|---|---|---|---|
| `short` | `Short term (≤ 1 year)` | `up to 1 year` | `1y` | `1d` | `1y` | `1y` |
| `medium` | `Medium term (1–3 years)` | `1 to 3 years` | `max` | `1wk` | `5y` | `5y` |
| `long` | `Long term (3+ years)` | `3 years or more` | `max` | `1mo` | `max` | `max` |

`prompt_guidance` (one or two sentences each, plain strings):
- short: "Focus on the next few weeks to 12 months: recent price action, momentum, upcoming data releases and events. Use daily data."
- medium: "Focus on the next 1–3 years: the economic cycle, earnings trends, interest-rate path and valuation. Prefer weekly data and multi-year history."
- long: "Focus on 3+ years: structural drivers (demographics, productivity, debt, competitive position), long-run valuation and full-history drawdowns. Prefer monthly data and the maximum available history; treat short-term noise as secondary."

`frame_question(question, horizon)` returns exactly:
```
{question}

Investment horizon: {label} ({years_hint}). {prompt_guidance} When you use price-based tools, prefer a lookback period of '{tool_lookback}'.
```
The literal prefix `Investment horizon: ` is a stable marker. Tests and the planner hint (A7) rely on it. `frame_question` with an unknown horizon raises `HorizonError`.

**A2. `index.html`.** Inside `#preview-form`, immediately after the question `<div class="field">…</textarea></div>`, add:
```html
<fieldset class="field field--horizon" id="horizon-group">
  <legend>Investment horizon</legend>
  <label class="radio-label"><input type="radio" name="horizon" value="short" checked /> <span>Short term (≤ 1 year)</span></label>
  <label class="radio-label"><input type="radio" name="horizon" value="medium" /> <span>Medium term (1–3 years)</span></label>
  <label class="radio-label"><input type="radio" name="horizon" value="long" /> <span>Long term (3+ years)</span></label>
</fieldset>
```
Radio, not checkbox, because the three options are mutually exclusive (decision §8).

**A3. `app.js`.**
- Add `function selectedHorizon() { const r = document.querySelector('input[name="horizon"]:checked'); return r ? r.value : 'short'; }`.
- In the `DOMContentLoaded` init, attach a `change` listener to every `input[name="horizon"]` that does `document.dispatchEvent(new CustomEvent('ifa:horizon', { detail: { horizon: selectedHorizon() } }))`.
- `runPreview`: append `&horizon=${encodeURIComponent(selectedHorizon())}` to the preview URL.
- `startRun`: the POST body becomes `{ question, profile: profile || null, simple, horizon: selectedHorizon() }`.
- `renderPreviewResult`: add a `Horizon` meta item from `data.horizon_label || data.horizon`.

**A4. `charts.js`.** Inside the existing IIFE:
```js
const HORIZON_CHART = {
  short:  { period: '1y',  interval: '1d'  },
  medium: { period: 'max', interval: '1wk' },
  long:   { period: 'max', interval: '1mo' },
};
function applyHorizon(h) {
  const cfg = HORIZON_CHART[h];
  if (!cfg) return;
  document.getElementById('chart-period').value = cfg.period;
  document.getElementById('chart-interval').value = cfg.interval;
  loadChart();
}
```
- In `initCharts()`, after the library check succeeds, register `document.addEventListener('ifa:horizon', (e) => applyHorizon(e.detail && e.detail.horizon));`.
- Don't register it when `LightweightCharts` is undefined (the early-return branch).
- Short leaves today's defaults (`1y`/`1d`) untouched. The user can still change the selects manually afterwards.
- Note: `period=max` with `interval=1d` is not used. Both the route regex (`web/market.py`) and `market_data._VALID_PERIODS/_VALID_INTERVALS` already accept `max`, `1wk` and `1mo`, so no backend change is needed.

**A5. `web/runs.py`.**
- `from typing import Literal`.
- `Horizon = Literal["short", "medium", "long"]`.
- `RunRequest.horizon: Horizon = "short"`. FastAPI returns 422 on any other value.
- `create_run`: store `"horizon": body.horizon` in the entry and pass it as a 5th thread arg.
- `_run_worker(run_id, question, profile, simple, horizon="short")` calls `run_committee(question, profile=profile, simple=simple, on_event=emit, horizon=horizon)`.
- `get_run` and `list_runs` include `"horizon": entry.get("horizon", "short")`.

**A6. `core/orchestrator.py::run_committee`.** Signature: `run_committee(question, *, profile=None, simple=False, tracker=None, on_event=None, horizon="short")`.
- At the top: `hz = resolve_horizon(horizon)` (import from `.horizon`) and `framed = frame_question(question, hz.key)`.
- Use `framed` (not `question`) in:
  - `_build_briefing(framed, ...)`
  - `plan_roles(framed, ...)`
  - every `agent.run(framed, ...)`
  - `run_debate(framed, ...)`
  - `_synthesize(framed, ...)`
- `RUN_STARTED` keeps `detail=question` and gets `data={"profile": profile_name, "horizon": hz.key}`.
- `Memo(question=question, horizon=hz.key, ...)`: the raw question, so UI and tests stay unchanged.
- `simple=True` also uses the framed question. It's cheap and it's what makes the `test_horizon` FakeLLM assertion possible.

**A7. `core/planner.py::plan_roles`.** No signature change. When building the planner user prompt:
- If `"Investment horizon: Long term" in question`, append one line: `"Hint: long horizon — prefer economist_long and strategist; technical and sentiment analysts add little."`
- If `"Investment horizon: Short term" in question`, append `"Hint: short horizon — technical, sentiment and news analysts are relevant."`
- These are guidance only: no forced roles, and the parse-failure fallback is unchanged (constrained by `tests/test_core_offline.py::TestPlanRoles` and `tests/test_prompts.py::test_planner_fallback_excludes_optional`).

**A8. `core/schemas.py::Memo`.** Add `horizon: str = Field(default="", description="short|medium|long")`. In `Memo.render()`, after the `Profile:` line, add `if self.horizon: lines.append(f"Horizon:  {self.horizon}")`. `tests/test_web_runs.py::TestRunChat` asserts `"RECOMMENDATION"` in the consultant context, which is unaffected.

**A9. `web/app.py::preview`.** Add a `horizon: str = Query(default="short", pattern=r"^(short|medium|long)$")` param. The response adds `"horizon": horizon, "horizon_label": HORIZONS[horizon].label`. No roster change.

**A10. `interfaces/cli.py`.** Add `parser.add_argument("--horizon", choices=["short", "medium", "long"], default="short", help="investment horizon framing for the committee")`. `cmd_run(..., horizon="short")` passes it to `run_committee(..., horizon=horizon)`. In `main()`, pass `horizon=args.horizon`.

### 4B — Plain-language memo + downloadable HTML report

**B1. `core/orchestrator.py`: richer, plain-language CIO contract.**

Add, near the top (`dataclasses` is already imported):
```python
@dataclasses.dataclass
class Synthesis:
    recommendation: str
    summary: str
    headline: str = ""
    key_reasons: List[str] = dataclasses.field(default_factory=list)
    main_risks: List[str] = dataclasses.field(default_factory=list)
    what_to_watch: List[str] = dataclasses.field(default_factory=list)
    confidence: int = 0  # 1..5; 0 = unknown / error / salvaged
```

Replace `_SYNTH_SYSTEM_TMPL`:
- Keep the first part verbatim: CIO identity, "Decision-support only — never advise executing orders", `{date}`, the training-data caveat and the `'unverified (training data)'` labeling rule.
- Append these style rules: "Write for an intelligent reader who is not a finance professional. Avoid trader jargon (e.g. long/short, bps, carry, duration, risk-on, overweight, spread widening); if a technical term is unavoidable, explain it in plain words in parentheses. Say what could go wrong in everyday money terms (e.g. 'a fall of around 20% would not be unusual'). Mention the investment horizon given in the question explicitly. Base every number on the briefing or the analyst views — do not invent figures."
- The JSON shape becomes (braces doubled because the template is `.format()`-ed):
```
{{"recommendation": "BUY|SELL|HOLD|AVOID", "headline": "one plain-English sentence", "summary": "3-5 plain-English sentences", "key_reasons": ["reason", "..."], "main_risks": ["risk in plain words", "..."], "what_to_watch": ["signal or event to monitor", "..."], "confidence": 1-5}}
```

Code changes:
- `_parse_synthesis(text) -> Optional[Synthesis]`:
  - same block extraction;
  - invalid rec → `HOLD` (unchanged);
  - list fields via `agent._clean_str_list` (import it alongside `_extract_json_block`), each capped at 6 items;
  - `confidence` via `int()` clamped 1..5, 0 on parse failure;
  - empty summary → `text.strip()[:600]` (unchanged rule).
- `_salvage_synthesis(text) -> Optional[Synthesis]`: same regexes, returns `Synthesis(rec, summary)` with empty lists, confidence 0. Optionally also regex-salvage `"headline"` with the same pattern as summary.
- `_synthesize(...) -> Synthesis`. Every current `return "ERROR", msg` becomes `return Synthesis("ERROR", msg)`. **Do not change** `_SYNTH_MAX_TOKENS = 2000`, the 2x retry cap, the budget pre-check, or `_SYNTH_RETRY_NUDGE` (its text must still contain `at most 5 sentences`, which `tests/test_orchestrator_synthesis.py::test_truncated_json_retried_with_double_cap_and_nudge` asserts).
- `run_committee`: `synth = _synthesize(...)`, then use `synth.recommendation` in the `SYNTHESIS_DONE` / `RUN_DONE` events and pass every field into `Memo(...)`.

Grep for other `_synthesize` / `_parse_synthesis` / `_salvage_synthesis` callers (`search: "_synthesize("`) and update them. Currently only `orchestrator.py` and `tests/test_orchestrator_synthesis.py` use them.

**B2. `core/schemas.py::Memo`.** Add the fields, all defaulted so existing fakes such as `tests/test_web_runs.py::_make_memo` keep working:
- `headline: str = ""`
- `key_reasons: List[str] = Field(default_factory=list)`
- `main_risks: List[str] = Field(default_factory=list)`
- `what_to_watch: List[str] = Field(default_factory=list)`
- `confidence: int = Field(default=0, ge=0, le=5)`

`render()` changes:
- After the `RECOMMENDATION` line, print `Headline: …` when set.
- After Summary, print `Why:`, `What could go wrong:` and `What to watch:` bullet blocks (`_clean_display_list`) when non-empty, and `Confidence: n/5` when > 0.

**B3. `interfaces/report/payload.py::build_run_result(memo, tracker, *, horizon="short", run_id="")`.**
- **Move** the whole `warnings` construction, the `call_records` list and the `result` dict out of `web/runs.py::_run_worker` **verbatim**. Keep every warning string byte-identical; `tests/test_web_runs.py::test_ungrounded_view_produces_warning` and `::test_error_view_produces_error_warning_and_field` assert the prefixes.
- Move `_FALLBACK_RISK` too and re-import it in `runs.py` if still referenced.
- Add keys:
  - `"horizon"`, `"horizon_label"` (from `core.horizon.HORIZONS`)
  - `"headline"`, `"key_reasons"`, `"main_risks"`, `"what_to_watch"`, `"confidence"`
  - `"generated_at"`: UTC ISO, seconds precision
  - `"run_id"`
  - `"report_url"`: `f"/api/runs/{run_id}/report.html"` when `run_id` else `""` (relative path, no scheme)
  - `"glossary"`: `[{"term", "plain", "how_calculated"}]` from `core.glossary.find_terms(memo.summary, memo.headline, *memo.key_reasons, *memo.main_risks, memo.briefing, memo.debate_summary, *(v.rationale for v in memo.views), *(r for v in memo.views for r in v.key_risks), *(t.text for t in memo.debate))`
  - `"stance_plain"`: `{"BULLISH": "Positive (expects prices to rise)", "BEARISH": "Negative (expects prices to fall)", "NEUTRAL": "Neutral (no strong view)", "ERROR": "Failed (no view produced)"}`
  - `"recommendation_plain"`: `{"BUY": "Favourable — the committee sees more upside than downside", "SELL": "Unfavourable — the committee sees more downside than upside", "HOLD": "Neutral — no strong reason to change exposure", "AVOID": "Unattractive — risks outweigh the potential reward", "ERROR": "No ruling — the final step failed"}[memo.recommendation]`. Wording is decision-support only, never an instruction.
- `web/runs.py::_run_worker` becomes `result = build_run_result(memo, tracker, horizon=horizon, run_id=run_id)`. Registry handling is unchanged.

**B4. `interfaces/report/html.py::render_committee_report(result) -> str`.** One self-contained page via `_html._page`. Section ids/headings in this exact order (tests assert the headings):

1. `cover`: "Investment Committee Report". Shows the question, horizon label, profile, `generated_at`, a recommendation badge + `recommendation_plain`, confidence as "n / 5" with ●○ dots, and the line "Final ruling by CIO (model)".
2. `plain`: **"In plain words"**, the headline (bold) + summary.
3. `why`: **"Why the committee thinks so"**, from `key_reasons`.
4. `risks`: **"What could go wrong"**, from `main_risks`.
5. `watch`: **"What to watch"**, from `what_to_watch`.
6. `specialists`: **"How each specialist saw it"**.
   - A summary table: Role | View (`stance_plain`) | Confidence (conviction/5) | Backed by live data? (Yes/No from `grounded`).
   - Then one card per view: rationale, key risks, evidence (each item linkified via `_link` if it contains an http(s) URL, using the regex from constraint 2), web sources.
   - ERROR views are shown with an explicit error box.
7. `debate`: **"Bull vs Bear debate"**, turns (speaker, model, text) + verdict with judge attribution. When `debate` is empty, the note "No debate was run (simple mode or debate disabled)."
8. `briefing`: **"Research briefing"**, `briefing` text in a `<pre class="wrap">` (escaped) + attribution.
9. `sources`: **"Sources"**, web sources (links) then other sources.
10. `warnings`: **"Warnings and data gaps"**.
11. `costs`: **"Cost of this analysis"**.
    - Headline: estimated USD (in/out), tokens / budget, LLM calls.
    - Table "By model": same columns as the Costs tab.
    - Table "Per call".
    - The cost note text from `app.js::renderCostsTab`.
12. `glossary`: **"Glossary"**, the auto `glossary` entries: term, plain meaning, how it is calculated.
13. `methodology`: **"How the numbers are calculated"**, from `core.glossary.METHODOLOGY`.
14. Footer: `DISCLAIMER`.

Rules:
- Every dynamic value goes through `_esc`.
- Missing keys degrade to "(not available)" (older result dicts may lack the new fields).
- Print-friendly CSS (`@media print`): avoid page breaks inside cards.
- Target < 400 lines.

**B5. `web/runs.py`: report route.**
```python
@router.get("/{run_id}/report.html")
def run_report(run_id: str) -> HTMLResponse:
```
- 404 when the run is unknown.
- 409 `"run is not finished; no report yet"` unless status is `done` with a result.
- Otherwise `HTMLResponse(render_committee_report(result), headers={"Content-Disposition": f'attachment; filename="ic-report-{run_id}.html"'})`.
- Import `HTMLResponse` from `fastapi.responses`.
- **Declare it before nothing that would shadow it.** The existing `/{run_id}/events` and `/{run_id}/chat` routes are distinct paths, so no ordering issue.

**B6. UI: `index.html` + `app.js`.**
- In `.results-header`, add `<a id="btn-download-report" class="btn btn--primary" hidden download>Download report (HTML)</a>`.
- In `pollRun`, on `done`: set `href = data.result.report_url || \`/api/runs/${runId}/report.html\`` and `hidden = false`. In `startRun`, re-hide it.
- Rewrite `renderMemoTab(result)`, using `textContent` only:
  - the header with the recommendation badge, the `recommendation_plain` text, a horizon badge (`horizon_label`) and confidence dots;
  - a `headline` `<h3>`;
  - an "In plain words" summary;
  - three titled bullet lists (only when non-empty);
  - attribution;
  - the question;
  - a collapsible `<details>` "Words used in this memo", showing `glossary` term + plain meaning.
- Reasoning tab: next to the stance badge, add a muted span with `stance_plain[stance]`; rename "Conviction n/5" to "Confidence n/5".

**B7. `interfaces/cli.py`.**
- Add `--report PATH` (`metavar="PATH"`).
- In `cmd_run(..., report_path=None)`, after printing:
```python
from ..interfaces.report import build_run_result, render_committee_report
Path(report_path).write_text(render_committee_report(build_run_result(memo, tracker, horizon=horizon)), encoding="utf-8")
print(f"[report] written to {report_path}")
```
- Wrap the write in `except OSError` → stderr message, return code 1.

### 4C — Portfolio upload, analytics, backtests, report, suggestion

**C1. `data/backtest.py::run_strategy`: expose the equity curve.**
- Add the keyword `return_curve: bool = False`.
- When `True`, add:
  - `"equity"`: the full `equity` list, rounded to 6 dp, length = `len(df)`;
  - `"dates"`: `[str(v)[:10] for v in df["Date"].tolist()]` if `"Date" in df.columns`, else `[str(i) for i in range(len(df))]`.
- When `False`, the output dict must be **identical** to today. `tests/test_strategy_backtest.py` and `core/tools/datasources.py::run_strategy_backtest` depend on it.

**C2. Input contract + `data/portfolio.py::parse_portfolio(text: str, fmt: str = "auto") -> Portfolio`.**

`@dataclass Position(ticker: str, weight: Optional[float] = None, quantity: Optional[float] = None, price: Optional[float] = None)`; `@dataclass Portfolio(positions: List[Position], mode: Literal["weight", "quantity"], warnings: List[str])`; `class PortfolioError(ValueError)`.

Accepted inputs (`fmt="auto"` → JSON if the stripped text starts with `{` or `[`, else CSV):
- CSV with header row, case-insensitive, `;` or `,` delimiter (sniff via `csv.Sniffer` with fallback `,`):
  - `ticker,weight`, where weight is either a fraction or a percent. If `sum > 1.5`, treat the values as percent and divide by 100, with a warning.
  - or `ticker,quantity[,price]`.
  - Extra columns are ignored, with a warning.
- JSON: `{"positions": [{"ticker": "SPY", "weight": 0.6}, ...]}` or a bare list of the same objects; `quantity` / `price` are allowed instead of `weight`.

Validation, each failure raising `PortfolioError` with a human message:
- 1–50 positions.
- Ticker matches `^[A-Za-z0-9.^=_-]{1,24}$` (copy the pattern; **do not import** `interfaces.web.market_data`, layering) and is upper-cased.
- Weights/quantities are finite and ≥ 0, and at least one is > 0.
- No mixing of weight and quantity modes.
- Duplicates are merged (summed) with a warning.
- Input text is capped at 100 KB.

`normalize_weights(portfolio, last_prices: Dict[str, float]) -> Dict[str, float]`:
- Weight mode: normalise to sum 1.0, with a warning if `abs(sum - 1) > 1e-6`.
- Quantity mode: `value_i = quantity_i * (price_i or last_prices[ticker])`, then normalise. A missing price raises `PortfolioError`.

**C3. `data/portfolio.py`: analytics (pure; raw fractions; positive VaR/ES/drawdown = loss; `TRADING_DAYS = 252`).**
- `align_closes(series: Dict[str, List[Tuple[str, float]]]) -> Tuple[List[str], Dict[str, List[float]], int]`: inner-join on dates (sorted ascending), returning `(dates, closes_by_ticker, dropped_count)`. Raise `PortfolioError` if fewer than 30 common dates remain.
- `portfolio_equity(dates, closes, weights, rebalance="none") -> Tuple[List[float], List[float], Dict[str, float]]`: start value 1.0.
  - `none` = buy-and-hold (weights drift);
  - `daily` = constant mix;
  - `monthly` = reset to target weights on the first date whose `YYYY-MM` differs from the previous date's.
  - Returns `(equity, daily_returns, final_weights)`.
- `drawdown_details(dates, equity) -> dict`: `{max_drawdown, peak_date, trough_date, recovery_date|None, duration_days, drawdown_series: List[float]}`. `max_drawdown` must equal `data.risk.max_drawdown(equity)`; reuse it and add the dates from the same peak-tracking walk.
- `performance_stats(dates, equity, returns, *, level=0.99, rf_annual=0.0, benchmark_returns=None) -> dict`:
  - `total_return = equity[-1] / equity[0] - 1`
  - `cagr = (1 + total_return) ** (252 / n_returns) - 1`
  - `ann_vol = data.risk.annualized_vol(returns)`
  - `sharpe = (cagr - rf_annual) / ann_vol` (None if vol = 0)
  - `downside_dev = sqrt(mean(min(r - rf_daily, 0)^2)) * sqrt(252)` with `rf_daily = (1 + rf_annual) ** (1/252) - 1`; `sortino = (cagr - rf_annual) / downside_dev` (None if 0)
  - `calmar = cagr / max_drawdown` (None if 0)
  - `hist_var_1d = data.risk.historical_var(returns, level)`, `param_var_1d = data.risk.parametric_var(...)`, `es_1d = data.risk.expected_shortfall(...)`
  - `var_10d_sqrt_scaled = hist_var_1d * sqrt(10)`, labelled as an approximation
  - `best_day`, `worst_day`, `pct_positive_days`
  - `skew`, `excess_kurtosis` (population moment formulas, stdlib)
  - `n_obs`, `level`, plus all `drawdown_details` keys except the series
  - If `benchmark_returns` (same length) is given:
    - `beta = cov(r, b) / var(b)`
    - `correlation`
    - `tracking_error = stdev(r - b) * sqrt(252)`
    - `information_ratio = (cagr - benchmark_cagr) / tracking_error`
    - `benchmark_cagr`, `excess_cagr`
- `position_stats(dates, closes, weights) -> List[dict]`, per ticker: `{ticker, weight, total_return, cagr, ann_vol, max_drawdown, contribution_to_return}`.
  - `contribution_to_return` = `w_i * total_return_i` for buy-and-hold. Document that it is a buy-and-hold approximation.
  - Sorted by weight descending.
- `diversification(weights, returns_by_ticker) -> dict`:
  - `hhi = Σ w²`, `effective_n = 1 / hhi`, `largest_weight`
  - `avg_pairwise_corr` (None for a single asset)
  - `correlation_matrix: {"tickers": [...], "values": [[...]]}`
- `rolling_vol(dates, returns, window=63) -> List[Tuple[str, float]]`, annualised.
- `strategy_overlays(ohlcv_frames: Dict[str, "DataFrame"], weights, strategies, *, cost_bps=0.0, level=0.99) -> List[dict]`:
  - Lazily `import pandas` (error → return `[]` + warning).
  - For each strategy in `data.backtest.STRATEGIES ∩ strategies`, for each ticker, call `run_strategy(df, strategy, cost_bps=cost_bps, level=level, return_curve=True)`.
  - Combine sleeves as `Σ w_i * equity_i` (buy-and-hold of strategy sleeves) on the common dates, and compute `performance_stats` on that curve.
  - Return `{strategy, rule, stats, equity: [(date, value)], per_ticker: [{ticker, total_return, n_trades, time_in_market}]}`.
  - A per-ticker `BacktestError` drops that strategy with a warning (never a crash).
- `analyze_portfolio(portfolio, series, *, benchmark_series=None, benchmark="SPY", ohlcv_frames=None, level=0.99, rf_annual=0.0, rebalance="none", cost_bps=0.0, strategies=None, horizon="short") -> dict` returns JSON-safe primitives only:
  - `positions`, `weights`
  - `window: {start, end, n_obs, dropped_dates}`, `as_of`
  - `stats` (for the chosen `rebalance`)
  - `rebalance_comparison: {none, monthly, daily, benchmark}` → each a stats subset `{total_return, cagr, ann_vol, sharpe, max_drawdown}`
  - `series: {equity, benchmark_equity, drawdown, rolling_vol}` as `[(date, value)]`, down-sampled to ≤ 600 points by even stride (always keep the first and last)
  - `position_stats`, `diversification`, `strategy_overlays`
  - `warnings`, `params: {level, rf_annual, rebalance, cost_bps, strategies, horizon, benchmark}`
  - The benchmark is aligned on the same dates. If the benchmark series is missing, add a warning and set benchmark-relative stats to None.

**C4. `interfaces/web/portfolio_data.py`.**
- `load_portfolio_prices(tickers: List[str], period: str, *, benchmark: Optional[str]) -> Tuple[Dict[str, dict], Optional[dict], List[str]]`: calls `market_data.get_price_history(t, period, "1d")` for every ticker. Access it through the module (`from . import market_data` then `market_data.get_price_history(...)`) so tests' monkeypatch of `market_data.fetch_yfinance_price_history` takes effect.
- A position failure raises `MarketDataProviderError(f"{ticker}: ...")`. A benchmark failure returns `None` plus a warning.
- `payload_to_series(payload) -> [(time, close)]`.
- `payload_to_ohlcv_frame(payload)`: same DataFrame construction as `market_data.attach_indicators` (`Date/Open/High/Low/Close/Volume`). Factor it out into a shared private helper in `market_data.py` if that is cleaner, keeping `attach_indicators` behaviour identical.

**C5. `interfaces/web/portfolio.py`: router `/api/portfolio`** (registered in `web/app.py` via `app.include_router`). Registry: `_lock = threading.Lock()`, `_analyses: Dict[str, dict]`, ids `uuid4().hex[:12]`, cap 50 entries (drop oldest).

```python
class AnalyzeRequest(BaseModel):
    portfolio_text: str = Field(..., max_length=100_000)
    format: Literal["auto", "csv", "json"] = "auto"
    horizon: Literal["short", "medium", "long"] = "short"
    period: Optional[Literal["6mo", "1y", "2y", "5y", "10y", "max"]] = None  # None → HORIZONS[horizon].portfolio_period
    benchmark: str = Field("SPY", pattern=r"^[A-Za-z0-9.^=_-]{1,24}$")
    var_level: float = Field(0.99, gt=0.5, lt=1.0)
    rf_annual: float = Field(0.0, ge=-0.05, le=0.25)
    rebalance: Literal["none", "monthly", "daily"] = "none"
    cost_bps: float = Field(0.0, ge=0, le=500)
    strategies: List[str] = Field(default_factory=lambda: sorted(STRATEGIES))

class SuggestRequest(BaseModel):
    run_id: Optional[str] = None
    model: Optional[str] = None
```

Routes:
- `POST /analyze`:
  - parse → load prices → `normalize_weights` (last closes) → `analyze_portfolio`.
  - `PortfolioError`, unknown strategy, `MarketDataValidationError` → 400. `MarketDataProviderError` → 502 (`detail` truncated to 120 chars, like `web/market.py`).
  - Returns `{analysis_id, analysis, display, report_url: f"/api/portfolio/{id}/report.html", disclaimer}`.
  - `display` is built by `_present(analysis)`: the same headline stats as `*_pct` rounded percent figures (like `core/tools/datasources.py`). It is used by the UI and the advisor digest so nobody misreads fractions.
  - This endpoint is **free**: no LLM call.
- `GET /{analysis_id}`: the stored entry (`analysis`, `display`, `suggestion` or null, `suggestion_cost` or null, `disclaimer`); 404 when unknown.
- `GET /{analysis_id}/report.html`: `HTMLResponse(render_portfolio_report(entry))` with `Content-Disposition: attachment; filename="portfolio-report-<id>.html"`; 404 when unknown.
- `POST /{analysis_id}/suggest` (**spends tokens**):
  - 404 for an unknown analysis.
  - If `run_id` is given, fetch the memo via a new helper `web/runs.py::completed_memo(run_id) -> Memo`: it raises `KeyError` → 404 and `RuntimeError` → 409 `"run is not finished"` and reads the registry under `_lock`.
  - Call `portfolio_advisor.suggest(build_digest(entry), market_context=memo, horizon=analysis.params.horizon, model=body.model, tracker=tracker)` with a fresh `RunTracker()`.
  - Store `suggestion` + `suggestion_cost = {"cost_usd": tracker.total_usd, "total_tokens": tracker.total_tokens, "by_model": tracker.by_model()}`.
  - Return both + the disclaimer.
- `build_digest(entry) -> dict`: compact, ≤ 8000 chars when JSON-dumped. It holds positions + weights, the `display` stats, the rebalance comparison, the top strategy overlays (name + cagr/maxDD/sharpe as pct), diversification (hhi, effective_n, avg corr), window and warnings. It never includes full series.

**C6. `core/portfolio_advisor.py`.**
- `DEFAULT_ADVISOR_MODEL = "claude-5.5-opus"`; `default_model()` reads `IFA_ADVISOR_MODEL` lazily.
- One `client.chat(model, messages, max_tokens=1500, json_mode=True)` call with OpenAI-format messages. `json_mode` is honoured only for GPT inside `llm/`; core never branches on family. Record usage with `tracker.record("portfolio_advisor", model, inp, out, elapsed)`.
- System prompt (plain string, `{date}` injected at call time):
  - "You are the CIO of a buy-side firm reviewing a client's portfolio. Decision-support only: never instruct anyone to buy, sell or execute anything — describe options, trade-offs and what each would change."
  - Plain-language rules (same as B1).
  - "Refer to the investment horizon explicitly."
  - "Use ONLY numbers present in the portfolio analytics digest and the market context; if something is missing, say so."
  - "If a market context (committee memo) is provided, relate your observations to it; otherwise say the view is based on the portfolio's own history only."
- Output contract: `{"assessment": "3-5 plain sentences", "strengths": ["..."], "weaknesses": ["..."], "ideas": [{"idea": "...", "why": "...", "type": "rebalance|diversify|hedge|reduce_risk|watch"}], "caveats": ["..."]}`.
- User message: `"Investment horizon: <label>\n\nPortfolio analytics digest (JSON):\n<digest>\n\nMarket context:\n<memo.render()[:6000] or '(none — no committee run selected)'>"`.
- Parse with `core.agent._extract_json_block` + `_clean_str_list`. An unknown idea `type` becomes `"watch"`. Cap 6 ideas / 6 items per list.
- Return `{"status": "ok", "model": model, ...fields}`.
- On API error (`is_completion_error`) or unparseable output, return `{"status": "error", "model": model, "error": "<api error message | no parseable JSON>", "raw": text[:400]}`. Never fabricate ideas.

**C7. `interfaces/report/portfolio_html.py::render_portfolio_report(entry) -> str`.** Headings (tests assert these):
1. **"Portfolio Analytics Report"** cover: positions table (ticker, weight %), window start–end, n_obs, benchmark, horizon, `as_of`, generated_at.
2. **"Key numbers in plain words"**. Each sentence is built from `display`:
   - "Over the period the portfolio grew by X% (Y% per year on average)."
   - "The worst fall from a peak was Z% (from <peak_date> to <trough_date>; recovered on <date> | not yet recovered)."
   - "On a typical bad day (1 in 100 at 99% confidence) you could lose about V% or more (VaR); on the worst 1% of days the average loss was E% (Expected Shortfall)."
   - "Return per unit of risk (Sharpe) was S."
   - Benchmark comparison.
3. **"Growth of 1 unit vs benchmark"**: `_svg_multi_line(equity, benchmark_equity)`.
4. **"Drawdowns"**: `_svg_line(drawdown, baseline=0)`.
5. **"Rolling volatility (3 months)"**: `_svg_line(rolling_vol)`.
6. **"Full statistics"**: a two-column table of every `stats` key with a human label + value (percent or ratio).
7. **"Positions"**: per-position table. **"Diversification"**: HHI, effective number of holdings, average correlation, and a correlation table with cells shaded by value (inline `style="background: rgba(...)"` computed from the number, never from text).
8. **"Rebalancing comparison"**: none / monthly / daily / benchmark table.
9. **"Strategy backtests"**: one row per overlay (rule description, CAGR, vol, max DD, Sharpe, trades), plus the note "Historical simulation only — rules are applied with a one-day delay to avoid look-ahead; past results do not predict future returns."
10. **"Suggestions"** (only if `entry["suggestion"]`): assessment, strengths, weaknesses, ideas (idea + why + type badge), caveats, plus the cost line "This section cost about $x (n tokens)". An `error` status shows an explicit error box.
11. **"Warnings"**.
12. **"Glossary"**: `find_terms` over the rendered labels + suggestion text. Always include VaR, Expected Shortfall, max drawdown, Sharpe, Sortino, Calmar, CAGR, beta, tracking error and rebalancing.
13. **"How the numbers are calculated"**: `METHODOLOGY`, which must cover:
    - historical VaR (empirical quantile with linear interpolation, as in `data/risk.py::_interpolate_quantile`)
    - parametric VaR `-(μ + zσ)`
    - ES = mean of returns at or below the VaR quantile
    - drawdown = peak-to-trough fall of the equity curve
    - CAGR, Sharpe `(CAGR − rf)/vol`, Sortino (downside deviation), Calmar `CAGR/maxDD`
    - beta `cov/var`, tracking error, information ratio
    - 252-day annualisation, √10 scaling caveat
    - buy-and-hold vs rebalancing, one-bar signal shift
    - data source yfinance via the local cache
14. Footer: DISCLAIMER.

**C8. UI.**

`index.html`: in `#preview-form`, after the horizon fieldset, add `<div class="field-row portfolio-controls" id="portfolio-controls">` containing:
- `<input type="file" id="portfolio-file" accept=".csv,.json,text/csv,application/json">`
- a help line "CSV `ticker,weight` (or `ticker,quantity`) or JSON — see docs/examples/portfolio_sample.csv"
- `<select id="portfolio-period">` (auto, 6mo, 1y, 2y, 5y, 10y, max; `auto` = horizon mapping, sent as `null`)
- `<input id="portfolio-benchmark" value="SPY" maxlength="24">`
- `<select id="portfolio-rebalance">` (none, monthly, daily)
- `<input type="number" id="portfolio-rf" value="0" step="0.25">` (risk-free % per year)
- four strategy checkboxes `name="portfolio-strategy"` (values = `STRATEGIES` keys, all checked)
- `<button type="button" id="btn-portfolio" class="btn btn--primary">Analyse portfolio — backtest + risk (free)</button>`

New `<section id="portfolio-panel" class="card" hidden>`, placed before `#results-panel`:
- header "Portfolio Analytics" + badge "Decision-support only"
- `#portfolio-status`
- `<a id="btn-portfolio-report" class="btn" hidden download>Download portfolio report (HTML)</a>`
- `<button id="btn-portfolio-suggest" class="btn btn--run" hidden>Ask for suggestions (spends tokens)</button>`
- tab bar `data-ptab` = overview | positions | backtests | charts | suggestion, with panels `#ptab-*`

`static/portfolio.js` (IIFE, `'use strict'`):
- Reuse the globals `fetchJson`, `el`, `textBlock` from app.js, plus `selectedHorizon()` (from A3). Read `_currentRunId` defensively via `typeof _currentRunId !== 'undefined' ? _currentRunId : null`; it's a top-level `let` in app.js, which is shared across classic scripts.
- Read the file with `FileReader.readAsText` (reject > 100 KB client-side).
- POST `/api/portfolio/analyze`.
- Render:
  - Overview: stat cards from `display` + plain-language sentences mirroring C7.2;
  - Positions: table + diversification;
  - Backtests: rebalance comparison + strategy table;
  - Charts: LightweightCharts line series for equity vs benchmark and drawdown (only if `LightweightCharts` is defined; else a text note).
- Suggest button: `window.confirm('This asks an LLM advisor and spends tokens. Proceed?')`, then POST `/suggest` with `run_id` = the current run id when the committee run status is done (otherwise `null`), and render the result in the Suggestion tab (status "error" → explicit error box).
- Listen to `ifa:horizon` to update the "auto" period hint text.
- **No `.innerHTML` / `insertAdjacentHTML`.**

`app.css`: `.field--horizon` (inline radio row), `.radio-label`, `.portfolio-controls`, `#portfolio-panel` tabs (reuse the `.tab-btn` styles), `.stat-cards` / `.stat-card`, `.memo-list`, `.confidence-dots`, `.badge--horizon`.

`docs/examples/portfolio_sample.csv`:
```
ticker,weight
SPY,0.5
TLT,0.3
GLD,0.2
```

### 4D — Tests, docs, CLI wiring

Write the tests in §5 alongside each sub-step above (test-first is fine), then do the docs in §6.

## 5. Test plan (all offline)

Command: `.venv\Scripts\python.exe -m pytest -q`. The full suite must be green after every sub-step. No network: price fetches are monkeypatched, LLM calls use `FakeLLM` from `tests/conftest.py`. The autouse fixture pins the playground backend.

### Existing tests that constrain this change (must pass; update only where noted)

- `tests/test_orchestrator_synthesis.py`: **update** for the `Synthesis` return type, keeping the same expected values. Each tuple comparison becomes field checks, e.g. `s = _run_synth(); assert (s.recommendation, s.summary) == ("BUY", "Moderate-conviction BUY.")`.
  - `TestSalvageSynthesis`: `is None` stays as is; tuple equality becomes `(out.recommendation, out.summary) == (...)`.
  - **Keep** every `llm.assert_call_count`, `max_tokens == 2000/4000`, `"at most 5 sentences"`, budget pre-check and reservation assertion unchanged.
  - `TestBudgetReservation` must still see exactly 4 calls in simple mode.
- `tests/test_web_runs.py`: **update** `_fake_run_committee`, `_fake_run_committee_error` and the inline `_fake_error_run` signatures to accept `horizon="short"`. That kwarg is now always passed, so a fake without it raises `TypeError` and the run ends in `error`. All existing assertions (warnings prefixes, cost fields, attribution, SSE, chat 409) must pass unchanged once `build_run_result` is a verbatim move.
- `tests/test_core_offline.py` (`run_committee(simple=True)` cases ≈ lines 400-470, 850-900) and `tests/test_events.py`: no assertions pin the user-message text (verified by grep). They must pass unchanged; the framed question only appends text. If one fails, inspect it — do not change `RUN_STARTED.detail` (still the raw question).
- `tests/test_strategy_backtest.py`: unchanged; add one `return_curve=True` case (below).
- `tests/test_web_market.py`: unchanged. `TestChartsPanelStatic` still passes (charts.js stays `.innerHTML`-free).
- `tests/test_web_offline.py::TestIndex`: add assertions for the new ids (below).
- `tests/test_endpoints.py::test_no_url_is_hardcoded_in_source`: guards constraint 2. Run it after writing `_html.py` / `html.py` / `portfolio_html.py`.
- `tests/test_data_layout.py`: guards constraint 3 for `data/portfolio.py`.
- `tests/test_prompts.py`, `tests/test_debate.py`: unchanged (analyst contract and debate prompts untouched).

### New tests

**`tests/test_horizon.py`**
- `HORIZONS` has exactly `short/medium/long`; chart mapping `short=(1y,1d)`, `medium=(max,1wk)`, `long=(max,1mo)`.
- `frame_question("Q?", "long")` starts with `"Q?"` and contains `"Investment horizon: Long term"`; an unknown horizon raises `HorizonError`; `resolve_horizon(None).key == "short"`.
- `run_committee("Q?", profile="budget", simple=True, horizon="long")` with `FakeLLM` (3 analyst JSON replies + 1 synthesis JSON):
  - every captured analyst user message contains `"Investment horizon: Long term"`;
  - `memo.question == "Q?"`;
  - `memo.horizon == "long"`.
- Planner hint: `plan_roles` with a framed long question → the captured planner prompt contains `"long horizon"`.
- Web (TestClient + the `test_web_runs` fake pattern):
  - `POST /api/runs {"question": "x", "horizon": "medium"}` → 202, and `GET` echoes `horizon == "medium"` and `result.horizon == "medium"`;
  - `horizon: "decade"` → 422;
  - `/api/preview?horizon=long` echoes `horizon_label`.
- Static:
  - `/` contains `name="horizon"` ×3 and `id="horizon-group"`;
  - `/static/charts.js` contains `ifa:horizon`, `'1wk'`, `'1mo'`;
  - `/static/app.js` contains `selectedHorizon` and has no new `.innerHTML` usages beyond the existing static ones (assert the count does not increase: record the current count in the test as a constant).

**`tests/test_glossary.py`**
- Every entry has non-empty `plain` and `how_calculated`.
- `find_terms("Our 99% VaR is 2%")` and `find_terms("value at risk")` both return the VaR entry.
- `find_terms("variance and evaluation")` does **not** return VaR (whole-word matching).
- Results are deduplicated and ordered.
- `METHODOLOGY` mentions "drawdown", "Sharpe" and "252".

**`tests/test_report_html.py`**
- Build a payload with `build_run_result(_make_memo(), _make_tracker(), horizon="long", run_id="abc")` (import the helpers from `tests/test_web_runs.py` or copy them).
- `render_committee_report(payload)`:
  - starts with `<!DOCTYPE html>`;
  - contains every §4B-B4 heading;
  - contains `DISCLAIMER`;
  - contains `"Long term"`;
  - contains `<script` **zero** times.
- XSS: put `<script>alert(1)</script>` in a view rationale and `javascript:alert(1)` as a web-source URL. The output contains `&lt;script&gt;`, never `<script>`, and has no `href="javascript:`.
- A result dict missing all new keys (simulate an old payload) still renders.
- Route:
  - after a done run, `GET /api/runs/{id}/report.html` → 200, `text/html`, `content-disposition` contains `attachment` and `ic-report-`;
  - unknown id → 404;
  - an error-state run → 409.
- `build_run_result` has the keys `glossary` (list), `report_url == "/api/runs/abc/report.html"` and `recommendation_plain`.
- CLI: `main(["Q?", "--simple", "--horizon", "long", "--report", str(tmp_path / "r.html")])` with `FakeLLM` (4 replies) writes a file containing "Investment Committee Report".

**`tests/test_portfolio_data.py`** (pure, no pandas except the overlay test → `pytest.importorskip("pandas")` / `"stockstats"`)
- `parse_portfolio`:
  - CSV weights (`,` and `;`);
  - percent weights (sum 100 → normalised, with a warning);
  - quantity CSV;
  - JSON dict and list forms;
  - duplicates merged with a warning.
- Errors: 0 positions, 51 positions, a negative weight, a bad ticker (`AAPL;DROP`), mixed modes, all-zero weights, malformed JSON → `PortfolioError`.
- `normalize_weights` in quantity mode uses last prices; a missing price → error.
- `align_closes` inner-joins and reports `dropped_count`; fewer than 30 common dates → error.
- `portfolio_equity`:
  - a single asset at weight 1 → the equity equals `price / price[0]` for every rebalance mode;
  - two assets with diverging paths → the `none` and `daily` final values differ;
  - `monthly` rebalances only at month boundaries (construct dates across 3 months and check the weights reset).
- `performance_stats` on a hand-built series with known values (e.g. constant +1%/day for 252 days → `cagr ≈ 1.01**252 - 1`, `ann_vol == 0`, `sharpe is None`); on an alternating series, VaR/ES/vol equal the direct `data.risk` calls (`pytest.approx`).
- `drawdown_details`: a known peak/trough/recovery on a constructed path (e.g. 1, 1.2, 0.9, 1.0, 1.25 → `max_drawdown == 0.25`, peak date index 1, trough 2, recovery 4); never recovered → `None`; `max_drawdown == data.risk.max_drawdown(equity)`.
- Benchmark = itself → `beta ≈ 1`, `correlation ≈ 1`, `tracking_error ≈ 0`.
- `diversification`: equal weights over 4 assets → `hhi == 0.25`, `effective_n == 4`.
- `analyze_portfolio` returns JSON-serialisable output (`json.dumps` succeeds) with all §4C-C3 keys; series ≤ 600 points.
- `strategy_overlays` (pandas + stockstats): monkeypatch `investment_firm.data.portfolio.run_strategy` (or the `data.backtest` reference it uses) with a spy and assert it is called with `return_curve=True`; one real run on a 300-bar seeded series returns `stats` and `equity`.
- `test_strategy_backtest.py` addition: `run_strategy(df, "sma_crossover", return_curve=True)` has `equity` and `dates` with `len == len(df)`; the `return_curve=False` keys are unchanged (`set(keys)` equality with the default call minus the two).

**`tests/test_web_portfolio.py`**
- Fixture like `test_web_market.py::market_client`:
  - set `INVESTMENT_FIRM_MARKET_CACHE` to `tmp_path`;
  - monkeypatch `market_data.fetch_yfinance_price_history` with a deterministic generator (`random.Random(hash-free seed derived from ticker via sum(map(ord, ticker)))`, 300 daily bars, business-day dates from 2025-01-02, OHLC around a random walk);
  - clear `portfolio._analyses`.
- `POST /api/portfolio/analyze` with `docs/examples/portfolio_sample.csv` contents → 200. It has `analysis_id`, `analysis.stats.sharpe`, `display.max_drawdown_pct`, `analysis.rebalance_comparison` keys `none/monthly/daily/benchmark`, `strategy_overlays` (if pandas/stockstats are installed; otherwise a warning) and `disclaimer`.
- `period` omitted + `horizon=long` → the fetch was called with period `max`.
- 400s: bad ticker, 51 positions, a negative weight, an unknown strategy. 422: `rebalance="weekly"`.
- Provider failure for one position → 502 with the ticker in `detail`. Benchmark failure → 200 + a warning.
- `GET /api/portfolio/{id}` → 200; unknown → 404.
- `GET /api/portfolio/{id}/report.html` → 200 attachment containing "Portfolio Analytics Report", "Key numbers in plain words", `<svg`, "How the numbers are calculated" and the DISCLAIMER, with no `<script`.
- `POST /suggest`:
  - with `FakeLLM([openai_text(valid_json)])` → `suggestion.status == "ok"`, the ideas parsed, an unknown idea type mapped to `watch`, `suggestion_cost.total_tokens > 0`; the captured system prompt contains "never instruct" and the user message contains "Investment horizon";
  - with `FakeLLM([openai_text("I think you should diversify.")])` → `status == "error"`, `"no parseable JSON"` in `error`, and no `ideas` key;
  - with `run_id` of a done run (the `test_web_runs` fake) → the user message contains `"RECOMMENDATION"`;
  - `run_id` of an errored run → 409; unknown `run_id` → 404.
- After `suggest`, the report contains the "Suggestions" section.
- Static: `/static/portfolio.js` → 200, no `.innerHTML`, no `insertAdjacentHTML`. `/` contains `id="portfolio-file"`, `id="btn-portfolio"`, `id="portfolio-panel"`, `/static/portfolio.js`, and the script order `app.js` < `portfolio.js`.

**`tests/test_web_offline.py::TestIndex`** (additions): `id="btn-download-report"`, `id="horizon-group"`, `id="btn-portfolio"`.

## 6. Docs & memory (do last, after the suite is green)

- **`README.md`**: add three sections.
  - **"Investment horizon"**: what the radio does to prompts and charts (short `1y`/daily, medium full history/weekly, long full history/monthly), plus the CLI `--horizon`.
  - **"Download the HTML report"**: the button, the `GET /api/runs/{id}/report.html` route, CLI `--report PATH`, and a list of the contents (every tab + glossary + methodology + disclaimer). Note that the file is self-contained, works offline and contains no scripts.
  - **"Portfolio analytics"**: the CSV/JSON format with the example file `docs/examples/portfolio_sample.csv`; the controls (period/auto, benchmark, rebalance, risk-free rate, strategies); which metrics are produced; that **analysis is free (no tokens)** while **"Ask for suggestions" spends tokens** (a single advisor call, optionally using the latest finished committee run as market context); in-memory storage (lost on server restart); decision-support only.
- **`docs/ARCHITECTURE.md`**:
  - add modules `core/horizon.py`, `core/glossary.py`, `core/portfolio_advisor.py`, `data/portfolio.py`, `interfaces/report/{payload,_html,html,portfolio_html}.py`, `interfaces/web/portfolio.py`, `interfaces/web/portfolio_data.py`, `static/portfolio.js`;
  - routes table rows: `GET /api/runs/{id}/report.html`, `POST /api/portfolio/analyze`, `GET /api/portfolio/{id}`, `GET /api/portfolio/{id}/report.html`, `POST /api/portfolio/{id}/suggest`;
  - an updated flow line: `question + horizon → frame_question → briefing → plan → analysts → debate → Synthesis → Memo → build_run_result → UI / HTML report`.
- **`AGENTS.md`**: use the project's memory mechanism (`save_note`) or edit the inventory sections. Add one inventory line per new module and these gotchas:
  - `_synthesize` returns a `Synthesis` dataclass, not a tuple;
  - `build_run_result` lives in `interfaces/report/payload.py` (`runs._run_worker` delegates);
  - horizon reaches agents only via `frame_question` (marker `Investment horizon: `), and `Memo.question` stays raw;
  - `run_strategy(return_curve=True)` adds `equity`/`dates`;
  - portfolio analyses live in an in-memory registry (`web/portfolio._analyses`, cap 50);
  - the report renderers must not contain URL literals (use `urlsplit`) because of `test_no_url_is_hardcoded_in_source`;
  - `portfolio.js` depends on app.js globals and must load after it.

  Also update the `orchestrator.py` and `web/runs.py` inventory lines (new kwarg, new route) and the `interfaces/` section.
- **`.claude/agents/web-ui-tester.md`**: add checklist items:
  - the horizon radio switches chart period/interval (long → max/1mo, medium → max/1wk, short → 1y/1d) and is sent with Run;
  - the Memo tab shows headline, three lists, horizon badge, confidence and glossary;
  - "Download report (HTML)" appears only after done and downloads an attachment;
  - portfolio upload with the sample CSV fills all five portfolio tabs;
  - the portfolio report downloads;
  - the suggest button shows a confirm dialog and renders ideas or an explicit error;
  - no console errors; no `innerHTML`.

## 7. Executor handoff

**Prerequisites.**
- The repo venv is at `.venv` (Windows). Deps are installed: `.venv\Scripts\python.exe -m pip install -e ".[data,api,dev]"`. pandas/stockstats/yfinance are needed only for the overlay tests, which skip gracefully otherwise.
- No network is needed or allowed in tests.
- Do NOT run live tests, a real committee run, `investment-firm "<question>"`, or a real portfolio analysis against Yahoo.

**Tooling.**
- Format: `.venv\Scripts\python.exe -m black src tests`.
- Test: `.venv\Scripts\python.exe -m pytest -q`.
- Always use `python -m <tool>` (AppLocker blocks native binaries). `jq` is not installed.
- No git commits; the user commits manually. Never edit `.env*`.

**Read before coding.**
- `AGENTS.md` (authoritative memory)
- `core/orchestrator.py` (whole file)
- `core/schemas.py`
- `core/agent.py` (`_extract_json_block`, `_clean_str_list`; do not modify)
- `core/planner.py`
- `data/risk.py`, `data/backtest.py`
- `interfaces/web/runs.py`, `interfaces/web/app.py`, `interfaces/web/market.py`, `interfaces/web/market_data.py`
- `interfaces/web/static/{index.html,app.js,charts.js,app.css}`
- `interfaces/cli.py`
- `tests/conftest.py` (`FakeLLM`, `openai_text`)
- `tests/test_web_runs.py`, `tests/test_web_market.py`, `tests/test_orchestrator_synthesis.py`, `tests/test_endpoints.py`, `tests/test_data_layout.py`

**Order.** 4A (A1→A10) → 4B (B1→B7) → 4C (C1→C8) → §5 tests (alongside each step) → §6 docs. Run pytest after every sub-step. If reality contradicts this plan (a file or line moved, a test asserts something unexpected), **stop and report** instead of improvising around a constraint.

**Optional subagents afterwards** (`.claude/agents/`):
- `scope-compliance-guard`: no execution language in the advisor prompt or UI copy.
- `security-reviewer`: report escaping and upload limits.
- `llm-cost-auditor`: the synthesis output grows to ~350-600 tokens within the unchanged 2000 cap; the advisor makes one 1500-cap call.
- `provenance-auditor`: the advisor must use only digest/memo numbers.
- `web-ui-tester`: the §6 checklist.

## 8. Open decisions (safe defaults chosen; deviate only with user sign-off)

| Decision | Default chosen | Why |
|---|---|---|
| Control type for horizon | **radio group** (the request said "checkbox") | short/medium/long are mutually exclusive; checkboxes would allow invalid combinations |
| Default horizon | `short` | keeps today's chart defaults (`1y`/`1d`) and every existing test unchanged |
| Chart mapping | short `1y`/`1d`, medium `max`/`1wk`, long `max`/`1mo` | as requested; the user can still override the selects |
| How the horizon reaches agents | appended to the question (`frame_question`) | keeps the frozen analyst `JSON_CONTRACT` / `BASE_HEADER` untouched |
| Portfolio period | `auto` = horizon mapping (short 1y, medium 5y, long max), user-overridable | matches the horizon while allowing a custom window |
| Risk-free rate | 0% p.a., user-settable | no network lookup needed; documented in the methodology |
| Benchmark | `SPY`, user-settable | common, always available on yfinance |
| Rebalance (headline stats) | `none` (buy-and-hold); all three modes are always shown in the comparison table | simplest to explain; the comparison shows the effect |
| Strategy overlays | all four `STRATEGIES` by default | reuses the existing, tested engine |
| Suggestion mechanism | **single advisor LLM call** (optionally seeded with the latest finished committee memo), not a full committee run | bounded, predictable token cost; a full committee run on a portfolio question remains possible via the normal Run button |
| Advisor model | `IFA_ADVISOR_MODEL` env, else `claude-5.5-opus` | mirrors the consultant default (`core/consultant.py`) |
| Report format | server-rendered static HTML, inline CSS + inline SVG, no JS | opens anywhere offline, prints well, no XSS surface |
| Storage | in-memory registries (runs + portfolio analyses, cap 50) | matches the existing `runs._registry`; persistence is out of scope |
| Synthesis token cap | unchanged at 2000 (retry 4000) | tests assert these values; the richer JSON fits |
| Contribution metric | buy-and-hold `w_i × return_i` | simple and explainable; labelled as an approximation |

## 9. Execution status

_Executed 2026-10-03. Final `pytest -q`: 709 passed, 3 deselected. Deviations: memo rendering lives in `static/memo.js` and new styles in `static/extras.css` (app.js/app.css already over the 800-line cap); the CIO JSON puts recommendation/headline/summary/confidence first and caps lists at 4 so a cut-off answer still salvages the ruling._

- [x] A1 — `core/horizon.py`
- [x] A2 — `index.html` horizon radio group
- [x] A3 — `app.js` `selectedHorizon` / `ifa:horizon` / request wiring
- [x] A4 — `charts.js` `HORIZON_CHART` + listener
- [x] A5 — `web/runs.py` `RunRequest.horizon` + registry/echo
- [x] A6 — `orchestrator.run_committee(horizon=...)` + framed question
- [x] A7 — `planner.py` horizon hint
- [x] A8 — `Memo.horizon` + render
- [x] A9 — `/api/preview?horizon=`
- [x] A10 — CLI `--horizon`
- [x] B1 — `Synthesis` dataclass + plain-language CIO contract
- [x] B2 — new `Memo` fields + render
- [x] B3 — `interfaces/report/payload.py::build_run_result` (verbatim move + new keys)
- [x] B4 — `interfaces/report/html.py` + `_html.py`
- [x] B5 — `GET /api/runs/{id}/report.html`
- [x] B6 — Memo tab rewrite + download button
- [x] B7 — CLI `--report PATH`
- [x] C1 — `run_strategy(return_curve=True)`
- [x] C2 — `parse_portfolio` / `normalize_weights`
- [x] C3 — `data/portfolio.py` analytics
- [x] C4 — `web/portfolio_data.py`
- [x] C5 — `web/portfolio.py` router + `runs.completed_memo`
- [x] C6 — `core/portfolio_advisor.py`
- [x] C7 — `interfaces/report/portfolio_html.py`
- [x] C8 — portfolio UI (`index.html`, `portfolio.js`, `extras.css`, sample CSV)
- [x] §5 — new test files + existing-test updates; full suite green
- [x] §6 — README, ARCHITECTURE, AGENTS.md, web-ui-tester checklist; black formatted
