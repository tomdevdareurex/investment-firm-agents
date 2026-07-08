# Prompt Library & Lean Roster — Implementation Plan

_Target repo: `investment-firm-agents`. Written for a cold-start executor (GitHub Copilot). All paths relative to repo root. Python package root: `src/investment_firm/`._

## 0. Context

Every one of the 27 roster agents currently receives the **same generic system prompt** (`_SYSTEM_TEMPLATE` in `src/investment_firm/core/agent.py:48-69`), differing only by the one-line `mandate` from `src/investment_firm/config/firm.yaml`. This produces shallow, interchangeable analysis. The reference design is the TradingAgents repo (`C:\Users\wn686\OneDrive - Deutsche Börse AG\Desktop\REPOs\TradingAgents\tradingagents\agents` — READ-ONLY, never modify), where each department (analysts / researchers / risk_mgmt / managers / trader) has deep, role-specific prompts (~15-30 lines each) with tool guidance, cross-debate references, and explicit output framing.

Goal: a `core/prompts/` package with department-organized, role-aware prompts; a leaner default roster (rest marked `optional: true`); high-tier model pins for the debate researchers. `firm.yaml` stays the source of truth for roster, tiers, model routing, votes, veto; its `mandate` becomes human doc + planner-catalogue hint only — the prompt library supersedes it for the actual system prompt.

## 1. HARD CONSTRAINTS (do not violate)

1. **The analyst JSON output contract is FROZEN.** `Agent._parse` / `_salvage_fields` / `_to_view` (`core/agent.py:94-116, 431-467`) depend on it. Every analyst system prompt MUST end by instructing ONLY a JSON object of exactly:
   `{"stance": "BULLISH|BEARISH|NEUTRAL", "conviction": 1-5, "rationale": "...", "key_risks": ["..."], "evidence": ["source: datapoint"]}`
   Debate turns stay free-text; the debate judge keeps its `{"stance": "...", "summary": "..."}` JSON (parsed in `core/debate.py:_judge`).
2. **Preserve all guardrails in every prompt**: "decision-support only — never advise executing orders"; today's-date injection at call time; prefer tools/web search/briefing over training data; label unverifiable figures as `'unverified (training data)'`; "Refusing, disclaiming your role, or replying in prose is a failure".
3. **core/ stays format-agnostic**: never add model-family branching (`is_claude`/`is_gemini`) to `core/`. Prompts are plain Python strings. No imports from `investment_firm.llm` inside `core/prompts/`.
4. **Offline tests only**: run `.venv\Scripts\python.exe -m pytest -q`. NEVER `-m live`, never `tests/test_smoke_live.py`, never real CLI runs.
5. **Environment**: format with `.venv\Scripts\python.exe -m black src tests` (native ruff binary is AppLocker-blocked on this machine). Keep files <800 lines (target 200-400).
6. Do not modify the TradingAgents reference repo.

## 2. Current vs target architecture

| | Current | Target |
|---|---|---|
| Analyst system prompt | One `_SYSTEM_TEMPLATE` (agent.py) + `mandate` line | `core/prompts/` package: shared base header + role/department body + frozen JSON contract footer |
| Prompt selection | none | Fallback chain: role-specific body → department-generic body (by `RoleSpec.group`) → generic body (uses `mandate`) |
| Debate prompts | `_BULL_SYSTEM`/`_BEAR_SYSTEM`/`_JUDGE_SYSTEM` inline in `core/debate.py` | Moved to `core/prompts/debate.py`, enriched TradingAgents-style; `core/debate.py` imports them |
| Roster | 27 roles, 2 optional | 13 core + 14 `optional: true`; planner catalogue includes optional roles annotated, fallback uses core only |
| bull/bear models | `family:` hints (gpt / claude) | Explicit pins: `bull_researcher: model: gpt-5.5`, `bear_researcher: model: claude-4.8-opus` |

Prompt anatomy (every analyst): `BASE_HEADER(role, date)` + `BODY(role-specific)` + `JSON_CONTRACT`. The contract footer is appended by one `compose()` function so no body can accidentally drop it.

## 3. New package layout: `src/investment_firm/core/prompts/`

| File | Content |
|---|---|
| `__init__.py` | Public API: `system_prompt_for(spec: RoleSpec) -> str` (computes today's date, delegates to registry + compose); re-exports debate prompts. |
| `base.py` | `BASE_HEADER` (identity, decision-support guardrail, `{date}`, training-data/unverified-labeling rules), `JSON_CONTRACT` (frozen footer incl. "refusing is a failure" + exact JSON shape — plain string, NOT `.format()`-ed, so no `{{` escaping bugs), `GENERIC_BODY` (fallback body containing `Your mandate: {mandate}` — behavior-equivalent to today's template), `compose(role: str, body: str, *, date: str) -> str`. |
| `analysts.py` | Role-specific bodies: `EQUITY_BODY`, `CREDIT_BODY`, `RATES_BODY`, `TECHNICAL_BODY`, `SENTIMENT_BODY`, `NEWS_BODY`, `STRATEGIST_BODY`, `FX_STRATEGIST_BODY`. |
| `economists.py` | ONE horizon-parameterized `ECONOMIST_BODY` template + `HORIZONS: dict[str, dict]` for `economist_short/medium/long` + `economist_body(role_name) -> str` (mirrors TradingAgents `trader/trader.py` parameterization). |
| `trading.py` | ONE asset-class-parameterized `DESK_BODY` + `DESKS: dict[str, dict]` for `rates_desk/equity_desk/swaps_desk/fx_desk` + `desk_body(role_name) -> str`. |
| `risk.py` | `MARKET_RISK_BODY` (specific) + lens-parameterized `RISK_LENS_BODY` + `RISK_LENSES` for `credit_risk`/`liquidity_risk` + `risk_body(role_name)`. |
| `governance.py` | `PM_BODY`, `COMPLIANCE_BODY`, `DEVILS_ADVOCATE_BODY`, `IC_CHAIR_BODY` (short; these roles are optional/M2 but must not fall back to nothing meaningful). |
| `librarian.py` | `LIBRARIAN_BODY` — provenance-heavy briefing-builder body (tag source/as_of/trust, cross-check prices, data_gaps, never invent numbers). |
| `debate.py` | `BULL_LABEL = "Senior Research Bull"`, `BEAR_LABEL = "Senior Research Bear"`, enriched `BULL_SYSTEM`, `BEAR_SYSTEM`, `JUDGE_SYSTEM` (all with `{date}` placeholder; bull/bear are free-text prompts; judge keeps `{{"stance"...,"summary"...}}` JSON with escaped braces because it IS `.format()`-ed). |
| `registry.py` | `ROLE_BODIES: dict[str, str]` (all 27 roles, incl. parameterized expansions), `DEPARTMENT_BODIES: dict[str, str]` keyed by firm.yaml `group` (`research`, `trading`, `risk`, `governance`, `quant`, `data`), `body_for(spec: RoleSpec) -> str` implementing role → department → `GENERIC_BODY` fallback. |

Import direction: `prompts` imports only `..roster` (for `RoleSpec` typing) and stdlib. `core/agent.py` and `core/debate.py` import from `prompts`. No cycles (`roster.py` imports nothing from `agent`/`debate`/`prompts`).

### Prompt body content requirements (TradingAgents depth, ~15-30 lines each)

Every body: written in second person, states the analytical lens, names the exact tools to call (from the real registry in `core/tools/datasources.py` + `core/tools/openbb_datasources.py`: `get_prices`, `get_indicators`, `get_fred_series`, `get_ecb_rate`, `get_worldbank_indicator`, `get_company_filing`, `compute_risk_metrics`, `run_backtest`, `get_stocktwits_sentiment`, `get_reddit_sentiment`, `get_prediction_market_odds`, `get_av_overview`, plus optional `get_yield_curve`/`get_options_summary`/`get_cpi`), gives interpretation guidance and anti-redundancy warnings, and says how evidence maps into the `evidence` field. Never promise tools that may be absent without hedging ("if available"). Specific requirements:

- `TECHNICAL_BODY`: indicator taxonomy à la TradingAgents `market_analyst.py` — SMA/EMA (trend, lag caveat), MACD (crossovers/divergence), RSI (70/30 thresholds), Bollinger (breakout/reversion), ATR (vol sizing); "select complementary indicators, avoid redundancy"; ground every level in `get_indicators`/`get_prices` output — never eyeball or invent levels.
- `EQUITY_BODY`: fundamentals lens — valuation vs growth, earnings quality, competitive position; `get_company_filing` (EDGAR) + `get_av_overview` + `get_prices`; distinguish company-specific vs market-wide drivers.
- `CREDIT_BODY`: IG vs HY, spread direction, issuer default & refinancing risk, rates sensitivity of credit; `get_prices` on credit ETF proxies (hedged), `get_fred_series` for spreads if available.
- `RATES_BODY`: curve shape/steepeners/duration; `get_yield_curve` (if available), `get_ecb_rate`, `get_fred_series`; connect policy path to the question.
- `SENTIMENT_BODY`: retail/social read via `get_stocktwits_sentiment` + `get_reddit_sentiment`; report bullish/bearish/mixed WITH sample counts; explicit noise disclaimer (sentiment is weak, contrarian at extremes); cap conviction ≤3 unless corroborated.
- `NEWS_BODY`: recent news + macro releases via web search + `get_fred_series`/`get_ecb_rate`; event → transmission channel → likely market impact; must always answer in the JSON schema (keep the current mandate's anti-refusal emphasis).
- `STRATEGIST_BODY`: cross-asset synthesis of macro into tilts; relative value framing.
- `FX_STRATEGIST_BODY`: rate differentials, terms of trade, positioning; `get_prices` on FX pairs, `get_ecb_rate`/`get_fred_series`.
- `ECONOMIST_BODY` params per horizon: `horizon_label` ("0-3 months"/"3-12 months"/"1 year+ structural"), `focus` (nowcasts & front-end pricing / cyclical turn & policy path / demographics, debt, productivity), `tools_hint` (e.g. short: `get_fred_series` high-frequency; long: `get_worldbank_indicator`, `get_cpi`).
- `DESK_BODY` params per desk: `asset_class`, `liquidity_metrics` wording (e.g. equities: ADV/spread; rates: on/off-the-run, futures depth; swaps: clearing/margin; FX: session liquidity). Desk lens = execution feasibility + flow color, explicitly NOT thesis.
- `MARKET_RISK_BODY`: MUST instruct calling `compute_risk_metrics` (VaR/ES/vol/drawdown, positive=loss convention) and citing exact figures; scenario/stress framing; sizing language (as analysis, not orders).
- `RISK_LENS_BODY` params: credit_risk (issuer/counterparty default, downgrade cascades) / liquidity_risk (exit feasibility vs ADV, gap risk, crowdedness).
- `LIBRARIAN_BODY`: keep every provenance behavior from the current yaml mandate (source/as_of/trust tagging, price cross-check, data_gaps) — the provenance-auditor subagent checks this.
- Debate `BULL_SYSTEM`/`BEAR_SYSTEM` (free-text output, NOT the JSON contract): keep every phrase the tests assert — labels "Senior Research Bull"/"Senior Research Bear", the example "[equity_analyst]" role-label reference, `{date}`, 'unverified (training data)', "2-4 tight paragraphs". Enrich à la TradingAgents researchers: argue growth/competitive-advantage/positive-indicators (bull) vs risks/weakness/negative-indicators (bear); "critically analyze the opponent's last argument with specific data — rebut, don't just list"; reference colleagues by role.
- `JUDGE_SYSTEM`: keep the frozen `{{"stance": "BULLISH|BEARISH|NEUTRAL", "summary": ...}}` contract; add research-manager judging criteria (commit to a side when evidence warrants; NEUTRAL only when genuinely balanced; weigh evidence quality over rhetoric).

## 4. Target roster (27 roles: 13 core / 14 optional)

`RoleSpec` already has `optional: bool = False` (`core/roster.py:83`, parsed at `:155`) — no roster.py schema change needed.

| Role | Group | Tier / routing | Prompt strategy | Core? |
|---|---|---|---|---|
| cio | governance | HEAD | n/a (synthesis + judge prompts live in orchestrator/debate, unchanged this round) | **core** |
| ic_chair | governance | HEAD | governance body | optional (tally unenforced until M2) |
| pm | governance | AUTHORITY | `PM_BODY` | optional (no PM step in pipeline yet) |
| compliance | governance | SENIOR | `COMPLIANCE_BODY` | optional (veto unenforced until M2) |
| devils_advocate | governance | AUTHORITY | `DEVILS_ADVOCATE_BODY` | optional |
| economist_short | research | WORKER, family gpt | shared `ECONOMIST_BODY` (horizon=0-3m) | optional |
| economist_medium | research | WORKER, family gemini | shared `ECONOMIST_BODY` (3-12m) | **core** |
| economist_long | research | WORKER, family claude | shared `ECONOMIST_BODY` (1y+) | optional |
| strategist | research | SENIOR | `STRATEGIST_BODY` | **core** |
| equity_analyst | research | WORKER, family claude | `EQUITY_BODY` | **core** |
| credit_analyst | research | WORKER, family gpt | `CREDIT_BODY` | **core** |
| rates_analyst | research | WORKER, family gemini | `RATES_BODY` | **core** |
| technical_analyst | research | WORKER | `TECHNICAL_BODY` | **core** |
| sentiment_analyst | research | WORKER | `SENTIMENT_BODY` | **core** |
| news_analyst | research | WORKER, family claude | `NEWS_BODY` | **core** |
| bull_researcher | research | SENIOR → **pin `model: gpt-5.5`** | `prompts/debate.BULL_SYSTEM` | **core** |
| bear_researcher | research | SENIOR → **pin `model: claude-4.8-opus`** | `prompts/debate.BEAR_SYSTEM` | **core** |
| fx_strategist | research | WORKER | `FX_STRATEGIST_BODY` | optional (already) |
| rates_desk / equity_desk / swaps_desk / fx_desk | trading | WORKER | shared `DESK_BODY` (asset-class param) | all optional |
| quant | quant | SENIOR | department-generic (quant lens via `DEPARTMENT_BODIES["quant"]`: factor/systematic framing, `run_backtest` + `compute_risk_metrics`) | optional |
| market_risk | risk | AUTHORITY | `MARKET_RISK_BODY` | **core** |
| credit_risk | risk | WORKER | shared `RISK_LENS_BODY` | optional |
| liquidity_risk | risk | WORKER | shared `RISK_LENS_BODY` | optional |
| research_librarian | data | WORKER, family claude | `LIBRARIAN_BODY` | **core** |

Merge justifications: the 3 economists differ only by horizon → one parameterized prompt (roles kept for planner horizon selection, only medium in the default lean set). The 4 desks differ only by asset class and are pure execution-feasibility color, not thesis → one parameterized prompt, all optional (they're not even in today's `CANDIDATE_ANALYSTS`). credit_risk/liquidity_risk are narrow lenses of the risk department → one parameterized prompt, optional; market_risk keeps a specific body because it's the veto-holding, `compute_risk_metrics`-driven authority. Governance roles stay defined (the `committee:` section of firm.yaml references them for M2) but optional since votes/veto/tally are unenforced.

Note on the model pins: **gpt-5.5 currently appears only in the `premium` profile's AUTHORITY tier list** (`firm.yaml` profiles), so a family hint could never select it under budget/balanced — an explicit `model:` pin is required. Both pins are deliberate high-tier debate upgrades that override the profile (never gpt-4.x for the bull; claude-4.8-opus for the bear). `resolve_roles` already honors `model:` before any tier/family logic (`core/roster.py:136-137`).

Planner-facing candidate sets (in `core/orchestrator.py`):
- `CANDIDATE_ANALYSTS` (core, 9): `equity_analyst, credit_analyst, rates_analyst, technical_analyst, sentiment_analyst, news_analyst, economist_medium, strategist, market_risk` (drops `economist_short`, `economist_long` from today's list of 11).
- NEW `OPTIONAL_ANALYSTS` (6): `economist_short, economist_long, fx_strategist, quant, credit_risk, liquidity_risk`.
- Planner catalogue = core + optional (optional lines annotated `"(optional — include only if the question clearly needs it)"`). Parse-failure fallback = core only (never stall, never fan out to 15 agents).

## 5. Ordered implementation steps

Each step keeps the suite green; run `.venv\Scripts\python.exe -m pytest -q` after every step.

1. **Create `src/investment_firm/core/prompts/base.py`.** Add `BASE_HEADER` (contains `{role}`, `{date}`; text: buy-side identity, "decision-support only — never advise executing orders", "Today's date is {date}.", training-data caveat, `'unverified (training data)'` labeling rule — lift wording from current `_SYSTEM_TEMPLATE` lines `core/agent.py:49-54`), `JSON_CONTRACT` (plain str, never `.format()`-ed: tool-usage guidance + quantitative-evidence line + "a stance is committee analysis, not a buy/sell recommendation" + "Refusing... is a failure" + exact JSON shape from `core/agent.py:55-68`, written with single braces), `GENERIC_BODY = "Your mandate: {mandate}\n"`, and `compose(role, body, *, date) -> str` = `BASE_HEADER.format(role=role, date=date) + "\n" + body.rstrip() + "\n\n" + JSON_CONTRACT`.
2. **Create body modules**: `analysts.py`, `economists.py`, `trading.py`, `risk.py`, `governance.py`, `librarian.py` per section 3 content requirements. Pure string constants + tiny param dicts + `*_body(role_name)` helpers. No I/O, no LLM imports.
3. **Create `core/prompts/debate.py`** with `BULL_LABEL`, `BEAR_LABEL`, `BULL_SYSTEM`, `BEAR_SYSTEM`, `JUDGE_SYSTEM` (enriched per section 3; preserve test-asserted phrases; judge JSON braces escaped `{{ }}` because it is `.format(date=...)`-ed).
4. **Create `core/prompts/registry.py`**: build `ROLE_BODIES` mapping all 27 role names → body strings (parameterized ones pre-expanded via `economist_body`/`desk_body`/`risk_body`); `DEPARTMENT_BODIES` for groups `research`/`trading`/`risk`/`governance`/`quant`/`data` (short generic department lenses); `body_for(spec)`: `ROLE_BODIES.get(spec.name)` → `DEPARTMENT_BODIES.get(spec.group)` → `GENERIC_BODY.format(mandate=spec.mandate)`. Note: only the generic fallback consumes `mandate`.
5. **Create `core/prompts/__init__.py`**: `system_prompt_for(spec: RoleSpec) -> str` = `compose(spec.name, body_for(spec), date=datetime.date.today().isoformat())`; re-export `BULL_LABEL, BEAR_LABEL, BULL_SYSTEM, BEAR_SYSTEM, JUDGE_SYSTEM`.
6. **Wire `core/agent.py`**: replace the `system_prompt` property body (`agent.py:186-192`) with `return system_prompt_for(self.spec)` (import `from .prompts import system_prompt_for`); DELETE `_SYSTEM_TEMPLATE` (grep first: `_SYSTEM_TEMPLATE` must have no other references — `core/debate.py` imports only `_extract_json_block` from agent). Everything else in agent.py untouched.
7. **Wire `core/debate.py`**: delete inline `_BULL_SYSTEM`/`_BEAR_SYSTEM`/`_JUDGE_SYSTEM` and the local `BULL_LABEL`/`BEAR_LABEL` definitions; replace with `from .prompts.debate import BULL_LABEL, BEAR_LABEL, BULL_SYSTEM, BEAR_SYSTEM, JUDGE_SYSTEM`; update the usage sites (`debate.py:175` and `:236`) to the new names. `BULL_LABEL`/`BEAR_LABEL` remain importable from `core.debate` (tests rely on it).
8. **Edit `src/investment_firm/config/firm.yaml`**: (a) `bull_researcher`: replace `family: gpt` with `model: gpt-5.5` + comment `# deliberate high-tier debate pin overriding profile; gpt-5.5 only exists in premium tier lists, hence explicit pin — never gpt-4.x`; (b) `bear_researcher`: replace `family: claude` with `model: claude-4.8-opus` + analogous comment; (c) add `optional: true` to: `ic_chair, pm, compliance, devils_advocate, economist_short, economist_long, quant, rates_desk, equity_desk, swaps_desk, credit_risk, liquidity_risk` (`fx_strategist`, `fx_desk` already have it). Keep every `mandate:` (now planner-hint/doc only).
9. **Edit `core/orchestrator.py`**: shrink `CANDIDATE_ANALYSTS` (line 46) to the 9 core names; add `OPTIONAL_ANALYSTS` list (6 names) below it; at the plan step (line ~251) resolve `CANDIDATE_ANALYSTS + OPTIONAL_ANALYSTS` and pass all specs to `plan_roles`. `simple=True` path (line 255, fixed `equity/credit/rates` trio) unchanged.
10. **Edit `core/planner.py`**: in `plan_roles`, annotate optional candidates in the catalogue line: `f"- {c.name}{' (optional — include only if the question clearly needs it)' if c.optional else ''}: {c.mandate}"`; change the parse-failure fallback (line 65) to `core = [c.name for c in candidates if not c.optional]; return core or [c.name for c in candidates]`. Signature unchanged.
11. **Update tests** (see section 6) + add `tests/test_prompts.py`.
12. **Format & docs**: `.venv\Scripts\python.exe -m black src tests`; update the AGENTS.md module inventory (add `core/prompts/`, note roster/pin changes); run `graphify update .` if the graphify CLI is available.

## 6. Test plan

Existing tests that constrain/verify (they must PASS unchanged if section-3 phrase preservation is honored):
- `tests/test_core_offline.py::test_system_prompt_contains_today` (~line 697), `::test_system_prompt_date_in_captured_call` (~703), `::test_system_prompt_requires_unverified_labeling` (~721) — satisfied by `BASE_HEADER` keeping the date + `'unverified (training data)'` phrases.
- `tests/test_debate.py::test_labels_and_prompt_carry_analyst_reasoning` (~172-200) — asserts `BULL_LABEL == "Senior Research Bull"`, `BEAR_LABEL == "Senior Research Bear"`, `"Senior Research Bull"` and `"[equity_analyst]"` in the captured bull system message. Keep those literals in `BULL_SYSTEM`/`BEAR_SYSTEM`.
- `tests/test_roster.py::test_resolve_all_candidate_analysts` (~241), `::test_cognitive_diversity_equity_credit_rates` (~248), `::test_new_analyst_roles_resolve_in_all_profiles` (~268) — still pass: the shrunk `CANDIDATE_ANALYSTS` all resolve; equity/credit/rates family hints unchanged; technical/sentiment/news stay core with `votes: true, vote_weight: 1`. If any assert the exact old candidate-list contents (verify at execution time), update expectations to the new 9-name list.
- `tests/test_core_offline.py::TestPlanRoles` (~479-517) — mock candidates default `optional=False`, so the new fallback returns them all; unchanged. Add one NEW case (here or in test_prompts): a candidate list containing one `optional=True` spec + unparseable plan → fallback excludes the optional role.
- `tests/test_web_offline.py::test_simple_true_has_fixed_analysts`, `::test_simple_false_includes_librarian`; `tests/test_web_runs.py` attribution tests; `tests/test_consultant.py::test_system_prompt_forbids_writes_and_trades` — unaffected (role names, simple-mode list, librarian/cio attribution, and `core/consultant.py` are untouched).

New `tests/test_prompts.py` (offline, no FakeLLM needed — pure string assertions):
1. `test_every_role_prompt_carries_frozen_contract` — for every role name in `load_firm()["roles"]`, resolve via `resolve_roles([name], profile="balanced")` and assert `system_prompt_for(spec)` contains `'"stance": "BULLISH|BEARISH|NEUTRAL"'`, `'"conviction"'`, `'"key_risks"'`, `'"evidence"'`, `"decision-support"`, today's ISO date, and `"unverified (training data)"`.
2. `test_role_specific_bodies_selected` — technical prompt mentions `get_indicators` and `RSI`; sentiment mentions `get_stocktwits_sentiment`; news mentions web search; market_risk mentions `compute_risk_metrics`; librarian mentions data_gaps/source tagging.
3. `test_economists_share_parameterized_prompt` — the three economist prompts are identical after removing their horizon-specific parameter strings; each contains its own horizon label.
4. `test_desks_share_parameterized_prompt` — same property for the 4 desks; each names its asset class.
5. `test_fallback_chain` — a synthetic `RoleSpec(name="unknown_role", group="risk", ...)` gets `DEPARTMENT_BODIES["risk"]`; `group="nonexistent"` gets the generic body containing its `mandate` text.
6. `test_debate_prompts_frozen_bits` — `BULL_SYSTEM` contains `"Senior Research Bull"` and `"[equity_analyst]"`; `JUDGE_SYSTEM.format(date="2026-01-01")` contains `'"stance"'` and `'"summary"'` and the date.
7. `test_bull_bear_model_pins` — `resolve_roles(["bull_researcher", "bear_researcher"], profile="budget")` yields `gpt-5.5` / `claude-4.8-opus` (pin overrides every profile).
8. `test_optional_flags` — every role in `OPTIONAL_ANALYSTS` + the governance/desk/risk optional set resolves with `optional=True`; every name in `CANDIDATE_ANALYSTS` resolves with `optional=False`.

Command (offline only): `.venv\Scripts\python.exe -m pytest -q` — full suite must be green. Optionally run the project subagents afterwards: provenance-auditor (librarian prompt keeps provenance rules), llm-cost-auditor (prompt bodies grow input tokens ~3-8x per analyst; the leaner default roster offsets this — flag if catalogue bloat appears in the planner prompt), scope-compliance-guard (no execution language in desk prompts).

## 7. Executor handoff

Prerequisites: repo venv at `.venv` (Windows), deps installed (`pip install -e .[dev]` already done); no network needed; do NOT run live tests or real runs. Format via `.venv\Scripts\python.exe -m black src tests` (AppLocker blocks native binaries — always invoke tools as `python -m <tool>`). No git commits — the user commits manually.

Read before coding: `AGENTS.md` (conventions + "Rules for coding agents"), `core/agent.py` (frozen parsers), `core/debate.py`, `core/roster.py`, `core/planner.py`, `core/orchestrator.py:40-70` and `:245-320`, `src/investment_firm/config/firm.yaml`, and the TradingAgents prompts for tone/depth (read-only): `analysts/market_analyst.py`, `researchers/bull_researcher.py`, `risk_mgmt/*.py`, `managers/*.py`, `trader/trader.py`.

Open decisions (safe defaults chosen; deviate only with user sign-off):
- CIO synthesis prompt (`_SYNTH_SYSTEM_TMPL`) and the librarian task prompt in `orchestrator.py` are NOT moved this round (keeps the diff focused); moving them into `prompts/governance.py`/`librarian.py` is a natural follow-up.
- Exact prose of each body is the executor's to write within the section-3 requirements; keep each body 15-30 lines, hedge optional tools with "if available".
- `quant` uses the department-generic quant body rather than a specific one (it's optional and rarely activated); upgrade later if used.
- Token budget: keep prompt bodies under ~350 words each so WORKER-tier runs don't blow `run_token_budget` (60k in the budget profile).

---

## Execution status (2026-07-08)

All 12 steps executed by Claude Code; full offline suite green (`455 passed, 3 deselected`). No git commits made (per instruction).

- [x] Step 1 — `core/prompts/base.py` (BASE_HEADER, frozen JSON_CONTRACT, GENERIC_BODY, compose)
- [x] Step 2 — body modules: `analysts.py`, `economists.py`, `trading.py`, `risk.py`, `governance.py`, `librarian.py`
- [x] Step 3 — `core/prompts/debate.py` (labels + enriched bull/bear/judge + seat bodies)
- [x] Step 4 — `core/prompts/registry.py` (ROLE_BODIES 26 roles; quant deliberately falls to DEPARTMENT_BODIES["quant"]; body_for fallback chain)
- [x] Step 5 — `core/prompts/__init__.py` (`system_prompt_for`, debate re-exports)
- [x] Step 6 — `core/agent.py` wired to `system_prompt_for`; `_SYSTEM_TEMPLATE` deleted
- [x] Step 7 — `core/debate.py` imports labels/prompts from `prompts.debate`; inline prompts deleted; labels still importable from `core.debate`
- [x] Step 8 — `firm.yaml`: bull pin `model: gpt-5.5`, bear pin `model: claude-4.8-opus`; `optional: true` added to ic_chair, pm, compliance, devils_advocate, economist_short, economist_long, quant, rates_desk, equity_desk, swaps_desk, credit_risk, liquidity_risk
- [x] Step 9 — `orchestrator.py`: CANDIDATE_ANALYSTS → 9 core; OPTIONAL_ANALYSTS (6) added; planner resolves core + optional
- [x] Step 10 — `planner.py`: optional-annotated catalogue; parse-failure fallback = non-optional core only
- [x] Step 11 — `tests/test_prompts.py` added (9 tests incl. planner optional-fallback); no existing tests needed changes
- [x] Step 12 — black formatted (7 files); AGENTS.md inventory updated; graphify CLI not on PATH (skipped)
