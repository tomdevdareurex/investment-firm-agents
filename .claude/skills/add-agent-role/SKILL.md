---
name: add-agent-role
description: Checklist for adding a new agent role (analyst, desk, risk, etc.) to the firm roster.
---

# Add a new agent role

Adding a role (e.g. a new desk or analyst) touches config, roster code, and
tests. Follow this checklist:

## 1. Config — `src/investment_firm/config/firm.yaml`

Add the role under the `roles:` section. Required: `tier` (one of `WORKER`,
`SENIOR`, `AUTHORITY`, `HEAD`). Optional: `family` (deterministic model
assignment), `model` / `tier` overrides, `votes`, `vote_weight`, `veto`,
`optional`.

## 2. Roster wiring — `src/investment_firm/core/roster.py`

Check whether the role needs code (system prompt, tools, special behavior) or
is fully config-driven. Follow the pattern of the most similar existing role.

## 3. Schemas — `src/investment_firm/core/schemas.py`

Only if the role produces a new structured output type; otherwise reuse the
existing analyst/desk schema.

## 4. Orchestrator — `src/investment_firm/core/orchestrator.py`

Verify the role is picked up in the debate/committee flow (fan-out, vote
collection). Most roles need no changes here.

## 5. Tests

- Extend `tests/test_roster.py`: role loads, resolves to a model in every
  profile (budget/balanced/premium), vote settings honored.
- Run offline tests only: `.venv/Scripts/python.exe -m pytest -q`
  (never `-m live` — those spend tokens).

## 6. Docs

Mention the new role in `README.md` roster description and
`docs/ARCHITECTURE.md` if it changes the committee flow.
