---
name: run-offline-tests
description: How to run this repo's test suite safely without spending API tokens. Use whenever running tests.
user-invocable: false
---

# Running tests in investment-firm-agents

This repo splits tests into **offline** (free, default) and **live** (hit the
real AI Playground API and **spend tokens**).

## Rules

1. Always run tests with the project venv Python:
   ```bash
   .venv/Scripts/python.exe -m pytest -q
   ```
2. `pyproject.toml` sets `addopts = "-m 'not live'"`, so the plain command above
   is already offline-only. **Never** pass `-m live`, `-m ""`, `--override-ini`,
   or `-p no:cacheprovider` tricks that would re-enable live tests.
3. Only run live tests (`python -m pytest -m live`) if the user explicitly asks
   for them in this conversation, and confirm before running.
4. `tests/test_smoke_live.py` is the live smoke test — do not invoke it directly
   by path either.
5. Offline tests use the FakeLLM fixture in `tests/conftest.py`; if a test needs
   an LLM, extend that fixture rather than calling a real backend.
