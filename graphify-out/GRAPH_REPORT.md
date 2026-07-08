# Graph Report - .  (2026-07-07)

## Corpus Check
- 94 files · ~96,240 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2560 nodes · 5935 edges · 121 communities (74 shown, 47 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 766 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Agent Grounding & Errors
- Agent & Planner Core
- Risk Metrics
- Consultant REPL
- Lightweight-Charts Vendor
- test_client_offline.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- debate.py
- test_tools_format.py
- LLM Client
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_technicals.py
- Web Static app.js
- Lightweight-Charts Vendor
- Agent Tools & Datasources
- LLM Web Search & Chat
- base.py
- test_web_runs.py
- Lightweight-Charts Vendor
- Core Orchestration
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_altdata_tools.py
- Lightweight-Charts Vendor
- test_indicators.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- config.py
- cli.py
- backends.py
- utils.py
- test_core_offline.py
- test_core_offline.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- market_data.py
- test_web_offline.py
- test_openbb_tools.py
- Lightweight-Charts Vendor
- test_llm_backends.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_citations.py
- app.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- indicators.py
- market_data.py
- AGENTS.md
- charts.js
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_risk.py
- openbb_datasources.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_roster.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- databricks_backend.py
- test_web_market.py
- test_roster.py
- test_roster.py
- Lightweight-Charts Vendor
- test_web_market.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- sanitize.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- market.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_web_market.py
- test_citations.py
- Lightweight-Charts Vendor
- test_llm_backends.py
- test_roster.py
- AGENTS.md
- Lightweight-Charts Vendor
- test_core_offline.py
- test_llm_backends.py
- ARCHITECTURE.md
- events.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_web_backend.py
- Lightweight-Charts Vendor
- Lightweight-Charts Vendor
- test_altdata_tools.py
- Lightweight-Charts Vendor
- test_data_layout.py
- AGENTS.md
- .mcp.json
- orchestrator.py
- base.py
- Lightweight-Charts Vendor
- test_roster.py
- test_smoke_live.py
- test_openbb_tools.py
- app.py
- Lightweight-Charts Vendor
- test_llm_backends.py
- indicators.py
- risk.py
- technicals.py
- __init__.py
- __init__-PC9L06055.py
- __init__.py
- __init__.py
- pyproject.toml

## God Nodes (most connected - your core abstractions)
1. `vn` - 110 edges
2. `ToolError` - 82 edges
3. `f()` - 68 edges
4. `Agent` - 67 edges
5. `ToolRegistry` - 67 edges
6. `sn()` - 67 edges
7. `RunTracker` - 63 edges
8. `as()` - 57 edges
9. `AnalystView` - 54 edges
10. `yi` - 54 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `extract_text()`  [INFERRED]
  scripts/probe_gemini_ws.py → src/investment_firm/llm/utils.py
- `show()` --calls--> `extract_tool_calls()`  [INFERRED]
  scripts/probe_live_fixes.py → src/investment_firm/llm/utils.py
- `show()` --calls--> `get_error_message()`  [INFERRED]
  scripts/probe_live_fixes.py → src/investment_firm/llm/utils.py
- `show()` --calls--> `is_error()`  [INFERRED]
  scripts/probe_live_fixes.py → src/investment_firm/llm/utils.py
- `test_strip_fences_removes_markers()` --calls--> `_strip_fences()`  [INFERRED]
  tests/test_core_offline.py → src/investment_firm/core/agent.py

## Import Cycles
- 3-file cycle: `src/investment_firm/llm/__init__.py -> src/investment_firm/llm/client.py -> src/investment_firm/llm/databricks_backend.py -> src/investment_firm/llm/__init__.py`
- 3-file cycle: `src/investment_firm/llm/__init__.py -> src/investment_firm/llm/client.py -> src/investment_firm/llm/backends.py -> src/investment_firm/llm/__init__.py`
- 4-file cycle: `src/investment_firm/llm/__init__.py -> src/investment_firm/llm/client.py -> src/investment_firm/llm/databricks_backend.py -> src/investment_firm/llm/backends.py -> src/investment_firm/llm/__init__.py`

## Hyperedges (group relationships)
- **Committee Run Pipeline** — src_investment_firm_config_firm_roles, agents_orchestrator, agents_agent_loop, agents_tool_registry, readme_run_committee [EXTRACTED 1.00]
- **Web Run Experience** — docs_architecture_web_ui, src_investment_firm_interfaces_web_static_index_run_form, src_investment_firm_interfaces_web_static_index_results_tabs, docs_architecture_event_stream, src_investment_firm_interfaces_web_static_index_consultant_tab [EXTRACTED 1.00]
- **Agent Review Safety Net** — _claude_agents_llm_cost_auditor_token_cost_review, _claude_agents_provenance_auditor_provenance_guarantees, _claude_agents_scope_compliance_guard_scope_boundary_review, _claude_agents_security_reviewer_security_review, _claude_agents_silent_failure_hunter_silent_failure_review [EXTRACTED 1.00]

## Communities (121 total, 47 thin omitted)

### Community 0 - "Agent Grounding & Errors"
Cohesion: 0.04
Nodes (35): BaseModel, Enforce the freshness gate: flag ungrounded views and tool data gaps., api_error_view(), error_summary(), parse_error_view(), Shared error classifier for the committee pipeline.  Any analyst, debate, or syn, One-line, unmistakable description of a failed pipeline stage., Explicit ERROR view for a completion/API failure.      The raw provider message (+27 more)

### Community 1 - "Agent & Planner Core"
Cohesion: 0.07
Nodes (37): Agent, A single role-playing analyst that can use tools over a bounded loop., plan_roles(), Return an ordered list of role names to run, chosen by the planner model., fake_llm(), openai_text(), openai_tool_call(), Return a factory that creates a FakeLLM and patches client.chat.      Usage in a (+29 more)

### Community 2 - "Risk Metrics"
Cohesion: 0.05
Nodes (31): annualized_vol(), expected_shortfall(), historical_var(), _interpolate_quantile(), max_drawdown(), parametric_var(), Pure-Python quantitative risk metrics (stdlib only: math, statistics).  No numpy, Gaussian (parametric) Value-at-Risk.      Formula: ``-(mu + z_alpha * sigma)`` w (+23 more)

### Community 3 - "Consultant REPL"
Cohesion: 0.05
Nodes (44): _chunk_text(), Consultant, consultant_registry(), default_model(), EventSink, A read-only quant consultant scoped to a single completed run., Answer ``question`` from the run context, optionally streaming tokens., Emit the answer. Never re-generate an answer the loop already billed. (+36 more)

### Community 4 - "Lightweight-Charts Vendor"
Cohesion: 0.07
Nodes (6): d(), f(), pn, Ts(), un(), v()

### Community 5 - "test_client_offline.py"
Cohesion: 0.05
Nodes (48): main(), One-off probe: find the payload shape that actually grounds Gemini web search., get_error_message(), is_completion_error(), is_error(), True if the response looks like an API error payload.      Returns ``True`` fo, True if ``resp`` cannot be a valid chat completion.      Stricter than :func:`, Return a human-readable error message, or ``None`` if not an error.      When (+40 more)

### Community 8 - "debate.py"
Cohesion: 0.07
Nodes (31): DebateResult, _estimate_tokens(), _judge(), _pace(), EventSink, Bull vs bear investment debate (Phase 4).  A small state machine layered on th, Rough token estimate (~4 chars/token) for budget pre-reservation., Run one debate turn; return the turn, or ``None`` if the budget is spent. (+23 more)

### Community 9 - "test_tools_format.py"
Cohesion: 0.06
Nodes (23): assistant_message(), extract_tool_calls(), Return the OpenAI-style ``tool_calls`` list from a response, or ``[]``.      E, Return the raw assistant ``message`` dict suitable for appending to the conversa, test_assistant_message_list_returns_none(), test_extract_tool_calls_list_returns_empty(), _capture(), _FakeResponse (+15 more)

### Community 10 - "LLM Client"
Cohesion: 0.07
Nodes (45): Client, Messages, OpenAI, Response, _convert_messages_for_claude(), _convert_tools_for_claude(), embeddings(), get_openai_client() (+37 more)

### Community 12 - "Lightweight-Charts Vendor"
Cohesion: 0.07
Nodes (4): Et, R(), ut, yi

### Community 13 - "test_technicals.py"
Cohesion: 0.08
Nodes (27): _build_row(), format_number(), _frame(), _indicator_values(), _interp_pct(), _last(), _macd_control(), Any (+19 more)

### Community 14 - "Web Static app.js"
Cohesion: 0.12
Nodes (37): _appendFeedLine(), _appendLiveDebateTurn(), el(), _ensureFeed(), fetchJson(), formatElapsed(), linkNode(), loadBackend() (+29 more)

### Community 15 - "Lightweight-Charts Vendor"
Cohesion: 0.07
Nodes (17): ae(), b(), bs(), c(), ce(), de(), fe(), mt() (+9 more)

### Community 16 - "Agent Tools & Datasources"
Cohesion: 0.11
Nodes (36): Tool abstraction and registry for agent tool-calling (M1.5)., Raised when a tool cannot run (bad args, missing provider, fetch failure)., ToolError, _av_float(), get_av_overview(), get_company_filing(), get_ecb_rate(), get_fred_series() (+28 more)

### Community 17 - "LLM Web Search & Chat"
Cohesion: 0.08
Nodes (33): _apply_web_search(), ask(), chat(), _convert_tool_choice_for_claude(), Any, Convert an OpenAI tool_choice value to Anthropic format.      * ``"auto"``, Mutate ``payload`` to request web search according to the configured strategy., POST to ``/chat/completions`` and return the raw JSON response.      Works for (+25 more)

### Community 18 - "base.py"
Cohesion: 0.09
Nodes (18): A resolved role: which model it uses and its committee attributes., RoleSpec, A callable the model can invoke.      Attributes:         name: Function name, Return the OpenAI function-tool schema for this tool., A collection of tools the agent may use., Return the OpenAI tool-schema list to pass to ``client.chat(tools=...)``., Tool, ToolRegistry (+10 more)

### Community 19 - "test_web_runs.py"
Cohesion: 0.08
Nodes (14): client(), error_client(), _fake_run_committee_error(), _parse_sse(), Offline tests for POST/GET /api/runs — no network, no tokens.  run_committee is, TestClient with run_committee monkeypatched to the happy-path fake., TestClient where run_committee always raises., Poll GET /api/runs/{run_id} until status in {done, error} or timeout. (+6 more)

### Community 21 - "Core Orchestration"
Cohesion: 0.09
Nodes (23): Agentic analyst (M1.5): a tool-using, looping, stateful agent.  Unlike the M1 si, Step-event bus for live run visibility (Phase 5 / fable-5 Objective 2).  A tin, Core firm logic: roster, tools, memory, agents, planner, orchestrator (M1.5)., Lightweight memory/state for agents and a run (M1.5).  Two scopes:  * :class, _build_briefing(), _dedup_sources(), _pace(), EventSink (+15 more)

### Community 23 - "Lightweight-Charts Vendor"
Cohesion: 0.16
Nodes (6): an(), en(), hn(), ln(), rn(), tn()

### Community 25 - "test_altdata_tools.py"
Cohesion: 0.12
Nodes (11): _patch_get(), Offline tests for the alt-data vendor tools (FRED, Polymarket, StockTwits).  A, BTC → 404, BTC.X → 200; payload reports the resolved symbol., 404 on both plain and .X symbol → explicit unsupported-asset ToolError., Already-suffixed symbols fail with a plain HTTP error, no retry loop., _Resp, TestAlphaVantage, TestEdgar (+3 more)

### Community 26 - "Lightweight-Charts Vendor"
Cohesion: 0.11
Nodes (3): E(), es(), fs()

### Community 27 - "test_indicators.py"
Cohesion: 0.10
Nodes (11): DataFrame, _ohlcv(), Offline tests for the shared technical-indicator engine (no network).  Asserts, The get_indicators agent tool (yfinance mocked — no network)., Deterministic synthetic OHLCV frame (no randomness, no network)., TestCatalog, TestCompute, TestGetIndicatorsTool (+3 more)

### Community 28 - "Lightweight-Charts Vendor"
Cohesion: 0.08
Nodes (5): kn, L, ms(), st, yn

### Community 30 - "Lightweight-Charts Vendor"
Cohesion: 0.22
Nodes (6): gs(), ks(), ls(), Ss(), ws, xs()

### Community 31 - "config.py"
Cohesion: 0.08
Nodes (29): api_key(), base_url(), call_pause(), ConfigError, has_api_key(), llm_backend(), _load_dotenv(), _parse_verify_ssl() (+21 more)

### Community 32 - "cli.py"
Cohesion: 0.11
Nodes (25): ArgumentParser, investment_firm — a buy-side investment firm simulated as orchestrated LLM agent, build_parser(), cmd_models(), cmd_probe_websearch(), cmd_run(), cmd_smoke(), cmd_tokens() (+17 more)

### Community 33 - "backends.py"
Cohesion: 0.10
Nodes (28): RuntimeError, BackendCapabilities, BackendError, capabilities(), current_backend(), _databricks_default_model(), _databricks_model_map(), map_model() (+20 more)

### Community 34 - "utils.py"
Cohesion: 0.10
Nodes (23): main(), One-off live probe: verify Claude tool_choice conversion + Gemini web-search gro, show(), Read-only quant-consultant chat agent (fable-5 Objective 5).  A senior-quant-c, extract_text(), extract_usage(), format_usage(), model_name() (+15 more)

### Community 35 - "test_core_offline.py"
Cohesion: 0.12
Nodes (15): _extract_json_block(), Remove ```json ... ``` code fences some models add despite instructions., Return the first balanced ``{...}`` substring, or ``None``., Best-effort field extraction from truncated/unbalanced JSON.      Models occasio, _salvage_fields(), _strip_fences(), _synthesize(), _clean_json() (+7 more)

### Community 36 - "test_core_offline.py"
Cohesion: 0.11
Nodes (10): An agent's per-task working memory., Shared state threaded between agents during one run., Render the shared context an agent should see before acting., RunMemory, ScratchMemory, Verify per-agent web_search flag based on model family and profile setting., credit_analyst uses GPT in budget profile → web_search=False forwarded., TestOrchestratorWebSearch (+2 more)

### Community 37 - "Lightweight-Charts Vendor"
Cohesion: 0.10
Nodes (4): G, it, jt, xi

### Community 39 - "market_data.py"
Cohesion: 0.15
Nodes (23): Connection, _build_yfinance_session(), _cache_key(), _ensure_cache_table(), fetch_yfinance_price_history(), _finite_float(), _is_valid_ohlc_bar(), _is_valid_price_history_payload() (+15 more)

### Community 40 - "test_web_offline.py"
Cohesion: 0.08
Nodes (5): Offline tests for the FastAPI web interface — no network, no tokens.  Uses fasta, TestHealth, TestIndex, TestPreview, TestProfiles

### Community 41 - "test_openbb_tools.py"
Cohesion: 0.19
Nodes (11): get_options_summary(), Return an options-chain summary for ``ticker`` from Cboe (via OpenBB).      Summ, _clean_json(), _contract(), _obb_with_chains(), _obb_with_cpi(), Offline tests for the optional OpenBB data tools (no network, no openbb needed)., Minimal stand-in for an OpenBB pydantic result row. (+3 more)

### Community 42 - "Lightweight-Charts Vendor"
Cohesion: 0.11
Nodes (5): ci(), di(), gi(), le(), mi

### Community 44 - "Lightweight-Charts Vendor"
Cohesion: 0.13
Nodes (4): bn, ht(), ji, qi()

### Community 45 - "Lightweight-Charts Vendor"
Cohesion: 0.11
Nodes (3): pe(), qs(), ye()

### Community 47 - "test_citations.py"
Cohesion: 0.13
Nodes (12): EventSink, Return a 'stale as_of=<date>' note when a tool result is older than allowed., Run the agent loop and return a parsed :class:`AnalystView`., Emit the analyst_done step event summarizing the produced view., _staleness_note(), extract_citations(), has_web_evidence(), Return real web-search source citations as ``[{"url", "title", "origin"}, ...]`` (+4 more)

### Community 48 - "app.py"
Cohesion: 0.15
Nodes (20): _backend_payload(), BackendRequest, get_backend(), get_profiles(), health(), _load(), preview(), _preview_roles() (+12 more)

### Community 49 - "Lightweight-Charts Vendor"
Cohesion: 0.14
Nodes (3): ai, Cn, wt

### Community 50 - "Lightweight-Charts Vendor"
Cohesion: 0.17
Nodes (3): he, ne(), se()

### Community 51 - "indicators.py"
Cohesion: 0.18
Nodes (18): Names, compute(), IndicatorError, _is_missing(), _last_date(), latest_snapshot(), overlay_series(), Shared technical-indicator engine (stockstats).  One source of truth for BOTH (+10 more)

### Community 52 - "market_data.py"
Cohesion: 0.19
Nodes (15): CacheRecord, default_cache_path(), _epoch_to_iso(), get_price_history(), MarketDataValidationError, Path, Return chart-ready price history, using the SQLite cache when allowed.      Ar, Read a non-expired cache record, returning ``None`` on miss/corruption. (+7 more)

### Community 53 - "AGENTS.md"
Cohesion: 0.12
Nodes (18): Provenance Guarantees, Scope Boundary Review, Security Review, Silent Failure Review, Add Agent Role Checklist, Agent Observe-Think-Act Loop, Decision-Support Only Boundary, Investment Firm Agents (+10 more)

### Community 54 - "charts.js"
Cohesion: 0.23
Nodes (17): activeSubpanes(), applyLayout(), buildTechRow(), computeSMA(), destroyChart(), ensureChart(), initCharts(), loadChart() (+9 more)

### Community 55 - "Lightweight-Charts Vendor"
Cohesion: 0.12
Nodes (7): bi(), H, I, oi(), ui(), vi(), xt()

### Community 56 - "Lightweight-Charts Vendor"
Cohesion: 0.12
Nodes (4): ee(), gn, qn(), xn()

### Community 58 - "test_risk.py"
Cohesion: 0.19
Nodes (7): compute_risk_metrics(), default_data_tools(), Compute quantitative risk metrics for ``ticker`` using yfinance closing prices., Return the free read-only data tools (enabled set from firm.yaml defaults)., TestRegistration, Values should be ~100x the fraction equivalents., TestComputeRiskMetrics

### Community 59 - "openbb_datasources.py"
Cohesion: 0.15
Nodes (15): _dump(), get_cpi(), _get_obb(), get_yield_curve(), _option_rows(), _patch_static_imports(), Any, Normalize OpenBB options-chains results to a list of per-contract dicts.      Ha (+7 more)

### Community 60 - "Lightweight-Charts Vendor"
Cohesion: 0.17
Nodes (3): ii, N, q()

### Community 62 - "test_roster.py"
Cohesion: 0.16
Nodes (10): _config_path(), load_firm(), profile_names(), Path, Resolve the firm config path lazily (``IFA_FIRM_CONFIG`` env override wins)., Load and cache the parsed ``firm.yaml`` document., Return the available profile names (e.g. ``budget``/``balanced``/``premium``)., budget/balanced WORKER pools are Claude/Gemini only (web search capable). (+2 more)

### Community 65 - "Lightweight-Charts Vendor"
Cohesion: 0.16
Nodes (5): _(), ct, dt(), k(), u()

### Community 67 - "databricks_backend.py"
Cohesion: 0.20
Nodes (14): _available_endpoints(), chat(), DatabricksBackendError, _import_workspace_client(), _openai_client(), Any, Databricks model-serving backend adapter.  Databricks serving endpoints are Open, Raised when the Databricks SDK is missing or authentication fails. (+6 more)

### Community 68 - "test_web_market.py"
Cohesion: 0.22
Nodes (6): MonkeyPatch, _fake_history_payload(), market_client(), Any, Offline tests for market-data web endpoints — no network, no tokens., TestSslResolution

### Community 69 - "test_roster.py"
Cohesion: 0.20
Nodes (8): _pick_model(), Resolve roles to :class:`RoleSpec`s for the selected profile.      Args:, Choose a model from ``tier_models`` honouring a family hint, else round-robin., resolve_roles(), equity=claude, rates=gemini via family hints; credit's gpt hint falls back, sentiment/news/technical analysts load and resolve to a model everywhere., news_analyst pins Claude so it always resolves to a web-search-capable model., TestRealFirm

### Community 70 - "test_roster.py"
Cohesion: 0.24
Nodes (7): Raised when the firm configuration is missing or inconsistent., Return a valid profile name, falling back to the configured default.      Prec, resolve_profile(), RosterError, _tier_models(), TestResolveProfilePrecedence, TestRosterErrors

### Community 72 - "test_web_market.py"
Cohesion: 0.15
Nodes (7): Exception, MarketDataError, MarketDataProviderError, Base error for market-data operations., Raised when an upstream data provider cannot return usable data., TestChartsPanelStatic, TestIndicatorOverlays

### Community 76 - "sanitize.py"
Cohesion: 0.23
Nodes (12): _balance(), _call_ids(), _call_names(), _flatten(), OpenAI message-history sanitizer for strict chat backends (Databricks).  Databri, Rewrite tool exchanges as plain text for tool-free requests., Whitelist request-message keys, dropping response-echoed extras.      Drops ``No, Return a history safe to send to a strict OpenAI-compatible backend. (+4 more)

### Community 80 - "market.py"
Cohesion: 0.24
Nodes (10): available_indicators(), Return a copy of the indicator catalog (name -> description)., attach_indicators(), attach_technicals(), Return a copy of ``payload`` with chart-ready indicator overlays attached., Return a copy of ``payload`` with a technical-summary block attached.      Com, price_history(), Any (+2 more)

### Community 82 - "Lightweight-Charts Vendor"
Cohesion: 0.18
Nodes (5): bt(), In(), on, os(), ot()

### Community 84 - "test_citations.py"
Cohesion: 0.29
Nodes (4): _clean_str_list(), Normalise a model-provided list field into a clean ``list[str]``.      Models so, Salvage must not capture quoted strings after the key_risks array., TestCleanStrList

### Community 86 - "test_llm_backends.py"
Cohesion: 0.20
Nodes (9): _FakeOpenAIClient, Dangling tool_calls in a tools-present request get stub results., Retry-without-tools resends a tool exchange with no tools kwarg — must flatten., test_databricks_chat_flattens_tool_history_when_tools_absent(), test_databricks_chat_ignores_web_search(), test_databricks_chat_maps_model_name(), test_databricks_chat_passes_openai_tools_through(), test_databricks_chat_sanitizes_unbalanced_history() (+1 more)

### Community 87 - "test_roster.py"
Cohesion: 0.20
Nodes (5): Offline tests for core/roster.py — no network, no tokens.  Covers: - resolve_pro, Three WORKER roles should round-robin across the two WORKER models., WORKER and SENIOR tier counters should be independent., TestModelPin, TestTierRoundRobin

### Community 88 - "AGENTS.md"
Cohesion: 0.22
Nodes (9): Token Cost Review, Python Review, Core Layer, Databricks Backend, Interfaces Layer, LLM Layer, AI Playground Backend, Format Conversion Boundary (+1 more)

### Community 89 - "Lightweight-Charts Vendor"
Cohesion: 0.25
Nodes (3): fi(), pi(), wi()

### Community 90 - "test_core_offline.py"
Cohesion: 0.28
Nodes (5): _run_worker should emit warnings for API error risks., View with key_risk starting 'API error' → warning containing role and 'API error, Existing fallback risk check still works., Clean view produces no warnings., TestRunsWarnings

### Community 92 - "ARCHITECTURE.md"
Cohesion: 0.25
Nodes (8): FastAPI Review, Browser Smoke Test, Step Event Stream, Market Charts Panel, Web UI, Runtime Dependencies, Results Tabs, Run Form

### Community 93 - "events.py"
Cohesion: 0.29
Nodes (8): Any, EventSink, One coarse progress event in a committee run., Serialize a StepEvent to a JSON-safe dict for SSE / logging., Emit one event to ``on_event``; a no-op when ``on_event`` is ``None``.      An, safe_emit(), StepEvent, to_dict()

### Community 102 - "AGENTS.md"
Cohesion: 0.40
Nodes (5): Run Offline Tests Skill, FakeLLM Offline Fixture, Offline Tests Only, Agentic Method, Copilot Agent Rules

### Community 103 - ".mcp.json"
Cohesion: 0.40
Nodes (4): npx, context7, playwright, @playwright/mcp

### Community 104 - "orchestrator.py"
Cohesion: 0.40
Nodes (4): Return the first web-search-capable model in the profile's WORKER pool, if any., _web_capable_worker_model(), test_web_capable_worker_model_none_under_databricks(), test_web_capable_worker_model_playground()

### Community 105 - "base.py"
Cohesion: 0.50
Nodes (3): Any, Execute the tool, wrapping any failure in :class:`ToolError`., Run tool ``name`` with ``arguments`` and return a JSON string result.

### Community 107 - "test_roster.py"
Cohesion: 0.40
Nodes (3): analyst_c has family=claude; should get the claude model from the pool., If family hint matches nothing, fall back to round-robin., TestFamilyHint

### Community 110 - "app.py"
Cohesion: 0.67
Nodes (3): FileResponse, Serve the single-page UI., serve_index()

## Knowledge Gaps
- **26 isolated node(s):** `context7`, `npx`, `@playwright/mcp`, `investment-firm-agents`, `Interfaces Layer` (+21 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `c()` connect `Lightweight-Charts Vendor` to `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Web Static app.js`, `Lightweight-Charts Vendor`, `test_web_runs.py`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`?**
  _High betweenness centrality (0.187) - this node is a cross-community bridge._
- **Why does `TestGetRunById` connect `test_web_runs.py` to `Agent Grounding & Errors`, `debate.py`?**
  _High betweenness centrality (0.177) - this node is a cross-community bridge._
- **Why does `gn` connect `Lightweight-Charts Vendor` to `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`, `Lightweight-Charts Vendor`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Are the 56 inferred relationships involving `ToolError` (e.g. with `_Resp` and `TestAlphaVantage`) actually correct?**
  _`ToolError` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 36 inferred relationships involving `Agent` (e.g. with `ScratchMemory` and `RoleSpec`) actually correct?**
  _`Agent` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 42 inferred relationships involving `ToolRegistry` (e.g. with `.test_dispatch_returns_provenance()` and `TestCleanStrList`) actually correct?**
  _`ToolRegistry` has 42 INFERRED edges - model-reasoned connections that need verification._
- **What connects `context7`, `npx`, `@playwright/mcp` to the rest of the system?**
  _405 weakly-connected nodes found - possible documentation gaps or missing edges._