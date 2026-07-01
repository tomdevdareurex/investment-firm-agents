# investment-firm-agents

A buy-side **investment firm simulated as a team of orchestrated LLM agents** — credit
and equity analysts, rates/FX/swaps desks, economists, a quant, a risk function,
compliance, a devil's advocate, a PM, and a CIO — that debate a question and produce a
structured **Investment Committee memo** with a recommendation.

It runs on the **Deutsche Börse AI Playground API** (one endpoint, many model families)
and doubles as a hands-on way to learn agent **orchestration** patterns.

> ⚠️ **Decision-support only.** This project produces analysis and a recommendation for a
> human to act on. It does **not** execute orders, connect to brokers/exchanges/wallets,
> or trade automatically. Nothing here is investment advice.

---

## Status: M0 (scaffold + LLM client + web-search probe)

The build proceeds in gated milestones; each runs and is tested before the next.

| Milestone | What it delivers | State |
| --- | --- | --- |
| **M0** | Repo scaffold, self-contained LLM client, cost tracking, smoke test, web-search probe | **in progress** |
| M1 | Base `Agent`, schemas, 3 analysts, sequential orchestrator → single-asset memo | planned |
| M1.5 | Free data layer (yfinance/ECB/EDGAR/World Bank), provenance, SOURCES table | planned |
| M2 | Full committee, parallel fan-out, router, budget profiles wired to the CLI | planned |
| M3 | Embeddings memory + post-mortem, notebooks, FastAPI surface | planned |

---

## Setup (DBAG Windows work laptop)

This machine has corporate AppLocker + Zscaler. Two rules matter:

- **Run pip as a module** (the `pip.exe` shim is blocked): `python -m pip ...`
- **Use `.venv`** (project-local virtual environment).

```powershell
# From the repo root
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .        # core (M0)
# later milestones add extras:
# .venv\Scripts\python.exe -m pip install -e ".[data]"   # M1.5
# .venv\Scripts\python.exe -m pip install -e ".[dev]"    # tests + notebooks

# Configure your key
copy .env.example .env        # then edit .env and paste your AI Playground key
```

Get the key from the **GET API KEY** button on the
[DevPortal AI Playground](https://devportal.deutsche-boerse.de/ai-playground) page.
(You can reuse the same key as the `AI-devs-playground` repo.)

### Zscaler / SSL

Corporate TLS inspection breaks normal verification, so `AI_PLAYGROUND_VERIFY_SSL`
defaults to `false`. For real verification, point it at your corporate CA bundle, e.g.
`C:\Users\wn686\corp-ca.pem`. The **first** request of a session can take ~10s (Zscaler
tunnel cold-start); the default timeout of 60s covers it.

---

## M0 usage

```powershell
# No tokens spent — connectivity + budget:
.venv\Scripts\python.exe -m investment_firm --models     # list available models
.venv\Scripts\python.exe -m investment_firm --tokens     # monthly token usage {used,total}

# Spends a few tokens — end-to-end smoke (one cheap gpt-4o-mini call):
.venv\Scripts\python.exe -m investment_firm --smoke

# Web-search probe (see below):
.venv\Scripts\python.exe -m investment_firm --probe-websearch gpt-5.5
```

Run the offline tests (no network, no tokens):

```powershell
.venv\Scripts\python.exe -m pytest
# opt-in live smoke (spends a few tokens):
.venv\Scripts\python.exe -m pytest -m live
```

---

## Web search (per-model capability — partially confirmed)

Web search is **not universal**: the `/ai/models` endpoint advertises a per-model
`webSearch` boolean, and only some families support it. The DevPortal UI shows the
`webSearch` toggle for every model, but that is just saved UI state — the backend gates
the capability per model and rejects the flag where it is unsupported.

**Confirmed (M0, via `/ai/models` capability flags + live probes):**

| Family | `webSearch` | Notes |
| --- | --- | --- |
| **Claude** (4.5 Haiku → 4.8 Opus, Sonnet) | `true` | Supported. Client uses the native `web_search_20250305` tool. |
| **Gemini** chat (2.5 / 3 / 3.1 / 3.5) | `true` | Supported. Generic flag **accepted**; grounding freshness still unconfirmed (see below). |
| **GPT** (4.1, 4o-mini, 5.4, 5.5, 5-mini, 5-nano) | `false` | **Not supported.** Sending the flag returns `Unknown parameter: 'web_search'`. |
| **Kimi K2.6, o4-mini** | `false` | Not supported. |
| Image models (Nano Banana *) | `false` | Not applicable. |

The remaining open question is only the **wire format / grounding** for the supported
models, not *which* models — that is now settled by the capability flag:

- **Hypothesis A — generic flag.** A top-level `web_search: true` is accepted by Gemini
  (no error, normal `choices` response). What is **not** yet proven is that the returned
  text is actually *grounded/current*: a probe on `gemini-2.5-flash` returned a stale
  answer while `usage.total` exceeded `input+output` (hinting a search ran but wasn't
  reflected in the text). Confirm with the F12 capture before relying on it.
- **Hypothesis B — per-provider tool.** Claude needs the Anthropic
  `web_search_20250305` tool (known-good, what the client uses in `auto` mode).

### How this client is wired (and how to confirm)

`IFA_WEBSEARCH_MODE` controls the strategy (default **`auto`**):

| Mode | Behaviour |
| --- | --- |
| `auto` *(default)* | Claude → native `web_search_20250305` tool (known-good); every other model → the generic flag (the path under test). |
| `generic` | **All** models → the generic flag. Set this to validate hypothesis A end-to-end. |
| `anthropic` | Always the Anthropic tool (Claude only). |

The generic flag key is `IFA_WEBSEARCH_FLAG` (default `web_search`).

**To confirm the wire format (the M0 probe):**

1. Open the DevPortal Playground, press **F12 → Network**.
2. Pick a **web-search-capable** model (`webSearch: true`, e.g. **Gemini 2.5 Flash** or a
   Claude model — *not* GPT, which is `webSearch: false`), toggle **web search ON**, and
   send a prompt that forces a search (e.g. *"What was the latest ECB rate decision?"*).
3. Click the `/chat/completions` request → **Payload**. Look at the JSON body:
   - top-level `"web_search": true` / `"webSearch": true` → **hypothesis A**. Set
     `IFA_WEBSEARCH_FLAG` to that exact key and `IFA_WEBSEARCH_MODE=generic`.
   - a `"tools": [...]` block → **hypothesis B**. Keep `auto`; per-provider specs get
     added as they're confirmed.
4. Record the finding in the table below.

> `.venv\Scripts\python.exe -m investment_firm --probe-websearch <model>` sends one
> search-requiring prompt and prints the raw response shape to help you compare. It first
> checks the model's `webSearch` flag and skips unsupported models (e.g. GPT) without
> spending a call.

### Confirmed findings

| Date | Model | Mode | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-06-25 | gpt-5.5 | generic | ❌ unsupported | `webSearch: false`; API returns `Unknown parameter: 'web_search'`. GPT family has no web search here. |
| 2026-06-25 | gemini-2.5-flash | generic | ⚠️ flag accepted | Generic `web_search` flag accepted (normal response), but answer was stale; grounding freshness unconfirmed — needs F12 cross-check. |
| 2026-06-25 | (all families) | — | ✅ capability mapped | `/ai/models` `webSearch` flag: Claude + Gemini chat = `true`; GPT, Kimi, o4-mini, image models = `false`. |

---

## Architecture deep dive

### Package layout (src layout)

`pyproject.toml` declares a **src layout** (`[tool.setuptools.packages.find] where = ["src"]`),
the console script `investment-firm = investment_firm.interfaces.cli:main`, and an
`addopts = "-m 'not live'"` pytest default so live (token-spending) tests are opt-in.

```
investment-firm-agents/
  pyproject.toml            # packaging, console script, pytest config, extras (data/embed/api/dev)
  src/investment_firm/
    __init__.py             # __version__ = "0.1.0", DISCLAIMER string (decision-support only)
    __main__.py             # enables `python -m investment_firm` → cli.main()
    llm/
      config.py             # lazy env/.env accessors (loaded once at import)
      models.py             # static model-name lists by family + helpers (is_claude/...)
      utils.py              # format-agnostic response parsing + PlaygroundError
      client.py             # the Playground HTTP client (chat/ask/stream/embeddings/list_models)
      costs.py              # relative cost weights + RunTracker (per-run usage/budget)
    interfaces/
      cli.py                # M0 CLI: --models/--tokens/--smoke/--probe-websearch/--version
    config/
      firm.yaml             # roster + tiers + budget profiles + committee rules (consumed M1+)
  tests/
    test_client_offline.py  # offline unit tests (monkeypatched, no network)
    test_smoke_live.py      # opt-in live smoke (marked `live`, skips without a key)
```

(Later milestones add `core/` — agents, schemas, orchestrator, patterns, datasources —
plus `notebooks/` and `examples/`.)

### The `llm` layer (the only working code at M0)

Everything today is a thin, **format-agnostic** wrapper around the single AI Playground
endpoint. The dependency order is `config → models → utils → costs → client`, with the
CLI sitting on top:

- **`config.py`** — all configuration is read **lazily through functions**
  (`api_key()`, `base_url()`, `verify_ssl()`, `timeout()`, `profile()`,
  `websearch_mode()`, `websearch_flag()`), never as module constants, so tests can
  monkeypatch the environment and the process can be reconfigured at runtime. `.env` is
  auto-loaded once at import by walking up from the file to the repo root
  (`_load_dotenv`). `verify_ssl()` returns `False`/`True`/a CA-bundle path and defaults
  to **`False`** for Zscaler; the urllib3 `InsecureRequestWarning` is silenced once at
  import when verification is off. `require_api_key()` raises `ConfigError` and treats the
  `paste-your-key-here` placeholder as missing.

- **`models.py`** — static name lists per family (`CLAUDE_MODELS`, `GEMINI_MODELS`,
  `GPT_MODELS`, `OTHER_MODELS`, `EMBEDDING_MODELS`) that *mirror the docs*; the live
  source of truth is `/ai/models`. Defaults: `DEFAULT_CHAT_MODEL = "gpt-4o-mini"`,
  `DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"`, `DEFAULT_MAX_TOKENS = 16000`.
  Helpers `is_claude/is_gemini/is_gpt/family` drive the per-family branching elsewhere.

- **`utils.py`** — hides the OpenAI-vs-Anthropic response shape difference. `/chat/completions`
  is a passthrough: GPT/Gemini/Kimi return `choices[].message.content`, Claude returns
  `content[].text`. `extract_text` reads both (and content-part lists), `extract_usage`
  normalises `prompt/completion_tokens` (OpenAI) and `input/output_tokens` (Anthropic)
  into `(input, output, total)`, and `is_error`/`get_error_message` detect both the
  Anthropic (`type == "error"`) and OpenAI (`error` dict) error envelopes. `PlaygroundError`
  is the shared exception.

- **`client.py`** — two transport strategies on purpose:
  - **`chat()` / `ask()`** use a **raw `httpx` POST** to `/chat/completions` and return
    the *raw JSON*, so they work uniformly for every model format. `chat()` auto-injects
    `max_tokens` (default 16000) **only for Claude** because Anthropic requires it, and
    **omits `temperature` unless explicitly set** (some models reject non-default values).
    Provider-specific keys go through `extra=`.
  - **`stream_chat()` / `embeddings()`** use the **official `openai` library**
    (`get_openai_client()` points it at the Playground base URL with the same SSL/timeout
    config) — convenient, but assume OpenAI-format models.
  - Capability/usage endpoints: `list_models()` (`GET /ai/models`),
    `model_capabilities()` / `supports_websearch()` (read the per-model `webSearch` flag),
    and `get_token_usage()` (`GET /ai/tokens` → `{used, total}`).
  - `_apply_web_search()` implements the three web-search modes described above
    (`auto`/`generic`/`anthropic`): Claude → native `web_search_20250305` tool, others →
    a generic top-level flag.

- **`costs.py`** — `COST_WEIGHTS` are **rough, unit-less** weights per 1,000 tokens,
  loosely anchored to `gpt-4o-mini ≈ 0.2`, with per-family fallbacks; *nothing depends on
  them being exact*. `estimate_cost()` = `weight * (input+output) / 1000`. `RunTracker`
  accumulates `CallRecord`s for one run, can enforce a `token_budget` via
  `would_exceed()`, and renders a per-agent + total table (`render_summary()`).

### The CLI (`interfaces/cli.py`)

`argparse`-based with one subcommand-flag each; `main()` dispatches and maps exceptions to
exit codes (`ConfigError → 2`, `PlaygroundError → 1`). A positional `question` is a **stub
until M2** (it just prints guidance). The disclaimer from `investment_firm.DISCLAIMER` is
printed before any token-spending command.

| Flag | Command | Spends tokens? |
| --- | --- | --- |
| `--models` | `cmd_models` — list `/ai/models` names | no |
| `--tokens` | `cmd_tokens` — print `{used, total}` from `/ai/tokens` | no |
| `--smoke` | `cmd_smoke` — list models → check budget → one cheap `gpt-4o-mini` call, tracked by `RunTracker` | yes (a few) |
| `--probe-websearch MODEL` | `cmd_probe_websearch` — gate on `supports_websearch` (skip + exit 2 if false), else send one search prompt and dump the raw shape | yes, unless skipped |
| `--version` | print version | no |

## How a run works (workflow)

### M0 — what runs today

The only end-to-end path is the **smoke test** (`investment-firm --smoke`):

```
cli.main()
  → cmd_smoke()
      1. client.list_models()        # GET /ai/models  (connectivity)
      2. client.get_token_usage()    # GET /ai/tokens   (budget)
      3. client.chat("gpt-4o-mini", [...], max_tokens=20)   # one cheap call
           → _httpx_client() POST /chat/completions
           → utils.extract_text / extract_usage
           → RunTracker.record(...) → render_summary()
```

Each API-calling command flows the same way: `config` resolves the key/URL/SSL/timeout
lazily, `client` builds the payload (with the Claude `max_tokens` / web-search nuances),
`utils` parses whatever shape comes back, and `costs` tallies usage. There is **no agent,
orchestrator, or committee code yet** — those arrive at M1+.

### M1+ — the intended firm workflow (configured in `firm.yaml`, not yet coded)

`config/firm.yaml` already encodes the target design so the orchestrator can be built on
top of it without code changes to add/retune roles:

1. **Roles → tiers → models.** Every role has a `tier`
   (`WORKER`/`SENIOR`/`AUTHORITY`/`HEAD`). A selected **profile** (`budget`/`balanced`/
   `premium`, chosen by `IFA_PROFILE`, default `balanced`) resolves each tier to a concrete
   model list; roles sharing a tier are assigned round-robin for **cognitive diversity**,
   with an optional `family:` hint (e.g. equity=Claude, credit=GPT, rates=Gemini) or a
   per-role `model:`/`tier:` override. Profiles also carry `web_search_max_uses`,
   `max_parallel`, `run_token_budget`, and `cio_cross_check`.
2. **Briefing packet.** The `research_librarian` (group `data`) builds **one shared,
   provenance-tagged** packet from free structured sources (yfinance/ECB/EDGAR/World Bank),
   qualitative web research, and user context — tagging every datapoint with
   source/as_of/trust, cross-checking prices, and flagging `data_gaps` instead of inventing
   numbers (`provenance.trust_order` ranks user_context > edgar > market_data > web_research
   > model_prior).
3. **Research & desks debate.** Economists (short/medium/long), strategist, equity/credit/
   rates/(FX) analysts form theses; trading desks assess execution feasibility (not thesis);
   the quant adds factor signals; risk (market/credit/liquidity) sizes and can veto.
4. **Committee vote.** Voting members are roles with `votes: true`, weighted by
   `vote_weight`; the `ic_chair` tallies `weighted_majority_of_stance` and breaks ties.
   `veto_roles: [compliance, market_risk]` can force reject/modify.
5. **CIO ruling.** The `cio` (tier `HEAD`) issues the final approve/modify/reject + sizing
   + monitoring triggers and **may override the vote** with documented rationale
   (`cio_can_override_vote: true`; in `premium`, cross-checked by gpt-5.5).
6. **Output.** A structured Investment Committee memo with a recommendation and a SOURCES
   table — **decision-support only; no orders are ever executed.**

> No code reads `firm.yaml` yet (M0); the milestones table above tracks when each layer
> (orchestrator, data, committee) lands.

## The firm (target roster — built out M1→M2)

Governance: **CIO** (final ruling), **PM** (sized proposal), **IC chair** (weighted vote),
**Compliance** (hard limits / veto), **Devil's Advocate** (counter-case).
Research: **3 economists** (short/medium/long), **cross-asset strategist**, **equity**,
**credit**, **rates**, optional **FX**.
Desks: **rates / equity / swaps / FX** (execution feasibility, not thesis).
Quant: **quant** (factors). Risk: **market** (VaR/stress, veto), **credit**, **liquidity**.
Data: **Research Librarian** (one shared, provenance-tagged briefing packet).

Roles map to **tiers** (`WORKER/SENIOR/AUTHORITY/HEAD`); a selected **profile**
(`budget/balanced/premium`) resolves each tier to a concrete model at runtime, so you can
switch the whole firm between cheap and premium with one flag. See
[src/investment_firm/config/firm.yaml](src/investment_firm/config/firm.yaml).
