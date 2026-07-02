# Architecture

A new developer should understand the repo from this document in ~10 minutes.

---

## Layer diagram

```
config/firm.yaml
      │
      ▼
llm/
  config.py      lazy env/.env accessors (no module constants)
      │
  models.py      static model-name lists + family helpers
      │
  utils.py       format-agnostic parsing (OpenAI + Anthropic shapes)
      │
  costs.py       COST_WEIGHTS, estimate_cost, RunTracker
      │
  client.py      raw httpx POST to /chat/completions (returns raw JSON)

core/
  roster.py      firm.yaml reader → RoleSpec (profile + tier → model)
      │
  planner.py     LLM call: pick which analysts to run + order
      │
  agent.py       tool-using observe-think-act loop → AnalystView
      │
  orchestrator.py   briefing → plan → analysts → CIO synthesis → Memo

interfaces/
  cli.py         argparse CLI (M0 + committee run)
  web/app.py     FastAPI preview UI (zero LLM calls for GET /api/preview)
```

Dependency direction: each layer imports only from layers above or from the
same level. The `llm/` layer has no knowledge of `core/`; `core/` depends on
`llm/` but not on `interfaces/`.

---

## The run pipeline

```
run_committee(question, profile, simple)
  │
  ├─ 1. Briefing (full mode only)
  │      research_librarian Agent uses data tools (yfinance / ECB / EDGAR /
  │      World Bank / compute_risk_metrics: VaR, Expected Shortfall, vol,
  │      drawdown) → provenance-tagged briefing text stored in RunMemory.
  │      TOKENS SPENT HERE.
  │
  ├─ 2. Plan (full mode only)
  │      CIO (planner) selects and orders CANDIDATE_ANALYSTS.
  │      Falls back to all candidates if model returns unparseable JSON.
  │      TOKENS SPENT HERE.
  │
  ├─ 3. Analysts  (loop)
  │      Each Agent runs its observe-think-act loop (max_steps bounded).
  │      May call data tools (and web search, if eligible) in each step.
  │      Later agents see the briefing + earlier colleagues' findings
  │      via RunMemory.context_for().
  │      TOKENS SPENT HERE (the bulk of the run).
  │
  │      Resilience ladder (Agent.run):
  │        (a) API error payload → remembered; if tools were active, retry once
  │            without tools. Persistent errors produce a fallback AnalystView
  │            with key_risks=["API error: <msg>"] — error never surfaces as
  │            rationale text.
  │        (b) max_steps exhausted while model is still tool-calling (no text) →
  │            one bounded finalization call without tools ("Stop calling tools.
  │            Answer now with ONLY the JSON object.").
  │        (c) Budget exhausted mid-loop → agent stops early, emits fallback view.
  │
  └─ 4. CIO synthesis
         Receives briefing + all AnalystViews → returns recommendation + summary.
         TOKENS SPENT HERE.
         → Memo returned to caller.
```

**simple=True** skips steps 1 and 2 and runs a fixed set of three analysts
(equity / credit / rates) with no tools. Useful for dry runs.

### Token budgeting

`profile_setting("run_token_budget")` in `firm.yaml` (e.g. 60 000 for
`budget`, 150 000 for `balanced`) is loaded once and passed to `RunTracker`.
Before each LLM call, `tracker.would_exceed(max_tokens)` is checked; if the
budget is exhausted the agent stops early and emits a fallback view rather
than crashing. The web preview (`GET /api/preview`) reports
`run_token_budget` without spending any tokens.

---

## firm.yaml contract

```yaml
default_profile: balanced

profiles:
  budget:
    WORKER:    [model, ...]    # tier → model list (round-robin)
    SENIOR:    [...]
    AUTHORITY: [...]
    HEAD:      [...]
    run_token_budget: 60000    # hard ceiling across the whole run
    web_search_max_uses: 1     # max data-tool/web-search calls per agent
    max_parallel: 3
    cio_cross_check: false

roles:
  equity_analyst:
    group: research
    tier: WORKER
    family: claude             # optional hint → picks the claude model from the tier pool
    mandate: Fundamental equity view.
    votes: true                # M2 — not yet enforced
    vote_weight: 1             # M2 — not yet enforced
  market_risk:
    tier: AUTHORITY
    veto: true                 # M2 — not yet enforced
```

**Tier assignment.** Roles sharing a tier get models round-robin for
cognitive diversity. A `family:` hint (e.g. `claude`) makes selection
deterministic — it picks the first model of that family from the tier pool,
falling back to round-robin if none matches. An explicit `model:` pin
bypasses the profile entirely.

**votes / veto** are stored in `RoleSpec` but not enforced until M2.

---

## AI Playground quirks

### Claude system-message hoist

The Playground Claude endpoint rejects a `system` *message* in the `messages`
array. `client.chat` auto-hoists any leading system message(s) to a top-level
`payload["system"]` field for Claude models before POSTing.

### Anthropic tool-calling format conversion

`client.chat` converts OpenAI-format tool parameters to Anthropic format
transparently, so `core/agent.py` stays format-agnostic across all model families.
Conversion happens entirely inside `llm/client.py` and `llm/utils.py`.

| Concern | OpenAI format | Anthropic format | Where converted |
|---------|--------------|-----------------|-----------------|
| Tool schemas | `{"type":"function","function":{name,description,parameters}}` | `{name,description,input_schema}` | `_convert_tools_for_claude` |
| `tool_choice` | `"auto"` / `"required"`/`"any"` / `"none"` | `{"type":"auto"}` / `{"type":"any"}` / omitted | `_convert_tool_choice_for_claude` |
| Tool result messages | `role:"tool"` with `tool_call_id` | `role:"user"` with `tool_result` content block (consecutive runs merged) | `_convert_messages_for_claude` |
| Assistant tool calls | `tool_calls` list | `tool_use` content blocks | `_convert_messages_for_claude` |
| Parsing responses | — | `tool_use` blocks parsed by `utils.extract_tool_calls`; normalized to OpenAI-style `tool_calls` | `llm/utils.py` |

### GPT JSON mode

`Agent.run` passes `json_mode=True` on every call. For GPT-family models
`client.chat` adds `response_format: {"type": "json_object"}` (OpenAI JSON
mode; requires the word "JSON" in the prompt, which the agent system prompt
provides). Other families ignore the flag and rely on prompt discipline plus
the parse cascade. gpt-4o-mini was removed from the budget/balanced WORKER
tiers (no web search on this gateway); GPT models remain in SENIOR+ tiers.

### Gemini JSON fences and truncation

Gemini often wraps JSON responses in ` ```json ... ``` ` code fences despite
explicit instructions not to. `agent._strip_fences()` removes them. Gemini
can also truncate mid-JSON at the token cap; `agent._salvage_fields()` then
regex-extracts the scalar fields (`stance`, `conviction`, `rationale`) before
the plain-text fallback kicks in. Default agent `max_tokens` is 1 200.

### Per-model web search — confirmed findings

| Date | Model | Mode | Result | Notes |
|------|-------|------|--------|-------|
| 2026-06-25 | gpt-5.5 | generic | unsupported | `webSearch: false`; API rejects flag. |
| 2026-06-25 | gemini-2.5-flash | generic | flag accepted | Answer was stale; grounding freshness unconfirmed. |
| 2026-06-25 | (all families) | — | capability mapped | `/ai/models` `webSearch`: Claude + Gemini = `true`; GPT, Kimi, o4-mini = `false`. |
| 2026-07-02 | claude-4.5-haiku | function tools + `tool_choice="auto"` | works | OpenAI→Anthropic conversion confirmed live (`tool_use` returned). |
| 2026-07-02 | claude-4.5-haiku | native web_search tool | GROUNDS | Returned current ECB deposit rate 2.25% (effective 2026-06-17). |
| 2026-07-02 | gemini-2.5-flash | `web_search: true` / `webSearch: true` flags | accepted, NOT grounding | Stale answer identical to no-web-search control. |
| 2026-07-02 | gemini-2.5-flash | `web_search_options: {}` | GROUNDS | Returned current ECB deposit rate 2.25% (effective 2026-06-17). |

`IFA_WEBSEARCH_MODE=auto` (default): Claude → native `web_search_20250305`
tool appended **alongside** function tools (not overwriting them); Gemini and
others → `web_search_options: {}` (OpenAI-style; confirmed grounding
2026-07-02). Setting `IFA_WEBSEARCH_FLAG` to a non-default key falls back to
the legacy boolean-flag behavior (escape hatch for gateway changes).
Probe scripts: `scripts/probe_live_fixes.py`, `scripts/probe_gemini_ws.py`.

**Web search in committee runs.** The orchestrator enables web search for the
research librarian and each analyst agent when two conditions are both true:
(1) the role's assigned model is Claude (`is_claude`) or Gemini (`is_gemini`),
and (2) `web_search_max_uses` in the active profile (`firm.yaml`) is > 0. GPT
and Kimi models never receive the web-search flag. Simple-mode runs skip web
search entirely. Setting `web_search_max_uses: 0` in a profile disables it for
all roles regardless of model family.

---

## Web UI surface

```
GET  /                   Serves static/index.html (no tokens)
GET  /api/health         {"version": ..., "disclaimer": ...}
GET  /api/profiles       {profiles: {budget: {WORKER: [...], ...}, ...}}
GET  /api/preview        {profile, simple, run_token_budget, roles, disclaimer}
                         — uses ONLY roster functions, zero LLM/API calls
POST /api/runs           Start a committee run; returns {run_id, status} (202)
GET  /api/runs           List all runs: [{run_id, status, question, profile, created_at}]
GET  /api/runs/{run_id}  Poll a run; includes result envelope when status==done:
                           {recommendation, summary, profile, question, briefing,
                            views, sources, cost_summary, call_records, warnings,
                            disclaimer}
```

**Run registry**: in-memory `dict` protected by `threading.Lock`; runs execute
as daemon threads so they die when the server exits. No persistence — registry
resets on server restart. `run_id` is a 12-hex-char `uuid4` fragment.

**Warnings** in the result envelope: analyst cards where `key_risks` contains
`"model did not return structured JSON"` (the agent.py JSON-fallback sentinel)
or begins with `"API error:"` (the resilience-ladder error sentinel) are flagged
in the web UI Costs/Warnings tab; a budget warning is appended if
`tracker.total_tokens >= token_budget`.

The preview endpoint (`/api/preview`) is the zero-token UX hook; the `/api/runs`
endpoints wire the full committee pipeline into the browser.

Quick-start:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[api]"
.venv\Scripts\python.exe -m uvicorn investment_firm.interfaces.web.app:app
# open http://127.0.0.1:8000
```

---

## Testing philosophy

**Offline by default.** `pytest addopts = "-m 'not live'"` deselects any test
marked `@pytest.mark.live`. The default suite is pure Python with no network.

**FakeLLM fixture** (`tests/conftest.py`). A scriptable monkeypatch for
`investment_firm.llm.client.chat`. Tests build a queue of canned responses
(OpenAI text, Anthropic text, OpenAI tool-call shape) and assert that the
right number of LLM calls were made in the right order. This lets the entire
agent/orchestrator/planner stack be tested offline.

```
tests/
  conftest.py              FakeLLM fixture + response builder helpers
  test_client_offline.py   llm/ layer (response parsing, payload construction)
  test_core_offline.py     agent parsing, tool registry, memory, run_committee
  test_roster.py           resolve_profile, round-robin, family hints, errors
  test_web_offline.py      FastAPI routes via TestClient (no network)
  test_smoke_live.py       opt-in live smoke (@pytest.mark.live)
```

Run live tests explicitly: `.venv\Scripts\python.exe -m pytest -m live`
(spends a few tokens on `gpt-4o-mini`).

---

## Safety

**Decision-support only.** The codebase produces analysis memos for a human to
review. No order execution, no broker/exchange/wallet connections anywhere.

**Disclaimer enforcement points:**
1. `investment_firm.DISCLAIMER` is the single source of truth (defined in
   `src/investment_firm/__init__.py`).
2. CLI prints it before any token-spending command.
3. `Memo.disclaimer` carries it in every generated memo.
4. `GET /api/health` and `GET /api/preview` return it in the JSON so the UI
   footer always renders the current string from the package.

**Secrets.** API key is never committed; loaded from `AI_PLAYGROUND_API_KEY`
env / `.env`. `require_api_key()` raises `ConfigError` if missing or if the
placeholder `paste-your-key-here` is detected.
