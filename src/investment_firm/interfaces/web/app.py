"""FastAPI application for the investment-firm-agents web UI.

Routes
------
GET /                  Serves static/index.html (no tokens).
GET /api/health        {"version": ..., "disclaimer": ...}
GET /api/profiles      Profile names + per-tier model lists.
GET /api/preview       Resolved roles, run_token_budget, profile, disclaimer.
                       Uses ONLY roster functions — zero LLM/API calls.
POST /api/runs         Start a committee run (202); returns run_id.
GET  /api/runs         List all runs (status + metadata).
GET  /api/runs/{id}    Poll a run; result included when status==done.

Run::

    .venv\\Scripts\\python.exe -m uvicorn investment_firm.interfaces.web.app:app

Requires the ``.[api]`` extra (fastapi + uvicorn).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError as _exc:  # pragma: no cover
    raise RuntimeError(
        "FastAPI not installed. Run:\n"
        "    .venv\\Scripts\\python.exe -m pip install -e \".[api]\""
    ) from _exc

import investment_firm
from investment_firm.core.orchestrator import (
    CANDIDATE_ANALYSTS,
    LIBRARIAN_ROLE,
    SYNTH_ROLE,
)
from investment_firm.core.roster import (
    RosterError,
    load_firm,
    profile_names,
    profile_setting,
    resolve_profile,
    resolve_roles,
)

from investment_firm.llm import backends as _backends

from investment_firm.interfaces.web.market import router as _market_router
from investment_firm.interfaces.web.runs import router as _runs_router

_STATIC = Path(__file__).parent / "static"

app = FastAPI(
    title="Investment-Firm Agents — Preview UI",
    description=(
        "Decision-support only. Produces analysis memos for human review. "
        "Never executes orders."
    ),
    version=investment_firm.__version__,
)

# Serve CSS/JS from static/
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# Runs sub-router (POST /api/runs, GET /api/runs, GET /api/runs/{run_id})
app.include_router(_runs_router)

# Market-data sub-router (GET /api/market/price-history)
app.include_router(_market_router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load() -> dict:
    """Load firm.yaml (cached by lru_cache in roster)."""
    return load_firm()


def _tier_models_for_profile(profile_name: str, firm: dict) -> Dict[str, List[str]]:
    """Return {tier: [model, ...]} for a profile."""
    profile_cfg = firm.get("profiles", {}).get(profile_name, {})
    tiers = ["WORKER", "SENIOR", "AUTHORITY", "HEAD"]
    return {
        t: list(profile_cfg.get(t, []))
        for t in tiers
        if profile_cfg.get(t)
    }


def _preview_roles(profile_name: str, simple: bool) -> List[Dict[str, str]]:
    """Return role preview dicts for the given profile and mode.

    simple=True  → fixed analyst list (equity/credit/rates) + CIO synthesis.
    simple=False → candidate analysts + librarian + CIO.
    """
    if simple:
        role_names = ["equity_analyst", "credit_analyst", "rates_analyst", SYNTH_ROLE]
    else:
        role_names = list(CANDIDATE_ANALYSTS) + [LIBRARIAN_ROLE, SYNTH_ROLE]

    # Deduplicate while preserving order (SYNTH_ROLE may appear in candidates).
    seen: list = []
    for r in role_names:
        if r not in seen:
            seen.append(r)

    specs = resolve_roles(seen, profile=profile_name)
    return [
        {
            "name": spec.name,
            "tier": spec.tier,
            "model": spec.model,
            "mandate": spec.mandate,
        }
        for spec in specs.values()
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    """Serve the single-page UI."""
    index = _STATIC / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index), media_type="text/html")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    """Version and disclaimer — no tokens spent."""
    return {
        "version": investment_firm.__version__,
        "disclaimer": investment_firm.DISCLAIMER,
    }


class BackendRequest(BaseModel):
    backend: str


def _backend_payload(name: str) -> Dict[str, Any]:
    caps = _backends.capabilities(name)
    payload: Dict[str, Any] = {
        "backend": name,
        "label": caps.label,
        "available": list(_backends.BACKENDS),
        "capabilities": {
            "web_search": caps.supports_web_search,
            "tools": caps.supports_tools,
        },
    }
    if not caps.supports_web_search:
        payload["note"] = (
            "No web search on this backend — analysts ground via data tools only."
        )
    return payload


@app.get("/api/backend")
def get_backend() -> Dict[str, Any]:
    """Current LLM backend + capabilities — no tokens, no network."""
    return _backend_payload(_backends.current_backend())


@app.post("/api/backend")
def set_backend(body: BackendRequest) -> Dict[str, Any]:
    """Switch the active LLM backend for this server process (runtime override)."""
    try:
        name = _backends.set_backend(body.backend)
    except _backends.BackendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _backend_payload(name)


@app.get("/api/profiles")
def get_profiles() -> Dict[str, Any]:
    """Available profiles with their per-tier model lists."""
    firm = _load()
    names = profile_names(firm)
    result: Dict[str, Any] = {}
    for name in names:
        result[name] = _tier_models_for_profile(name, firm)
    return {"profiles": result}


@app.get("/api/preview")
def preview(
    question: str = Query(default="", description="The investment question (optional for preview)."),
    profile: Optional[str] = Query(default=None, description="Profile name (default: yaml default)."),
    simple: bool = Query(default=False, description="Use simple fixed-analyst mode."),
) -> Dict[str, Any]:
    """Preview which roles/models would run — zero API/LLM calls.

    Returns resolved roles (name, tier, model, mandate), the run_token_budget
    for the selected profile, the profile name used, and the disclaimer.

    Raises HTTP 400 for unknown profiles.
    """
    firm = _load()
    try:
        profile_name = resolve_profile(profile, firm)
    except RosterError as exc:
        available = ", ".join(profile_names(firm))
        raise HTTPException(
            status_code=400,
            detail=f"{exc}. Available profiles: {available}",
        ) from exc

    roles = _preview_roles(profile_name, simple=simple)
    budget = int(profile_setting("run_token_budget", 0, profile=profile_name, firm=firm) or 0)

    return {
        "profile": profile_name,
        "simple": simple,
        "run_token_budget": budget,
        "roles": roles,
        "disclaimer": investment_firm.DISCLAIMER,
    }
