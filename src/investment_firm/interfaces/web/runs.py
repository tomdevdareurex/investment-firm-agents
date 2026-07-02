"""In-memory run registry and /api/runs endpoints.

Routes
------
POST /api/runs          Start a committee run (202 + run_id).
GET  /api/runs          List all runs (status + metadata only).
GET  /api/runs/{run_id} Poll a run; when done includes full result envelope.

The registry is a plain dict protected by a threading.Lock.
Runs are daemon threads so they die when the server exits; no persistence.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
except ImportError as _exc:  # pragma: no cover
    raise RuntimeError(
        "FastAPI not installed. Run:\n"
        "    .venv\\Scripts\\python.exe -m pip install -e \".[api]\""
    ) from _exc

import investment_firm
from investment_firm.core.orchestrator import run_committee
from investment_firm.core.roster import (
    RosterError,
    load_firm,
    profile_names,
    resolve_profile,
)

# ---------------------------------------------------------------------------
# Registry (in-memory, thread-safe)
# ---------------------------------------------------------------------------

_lock: threading.Lock = threading.Lock()
_registry: Dict[str, Dict[str, Any]] = {}

_FALLBACK_RISK = "model did not return structured JSON"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    question: str
    profile: Optional[str] = None
    simple: bool = False


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_worker(run_id: str, question: str, profile: Optional[str], simple: bool) -> None:
    """Execute run_committee in a daemon thread and store the result."""
    with _lock:
        _registry[run_id]["status"] = "running"

    try:
        memo, tracker = run_committee(question, profile=profile, simple=simple)

        # Build warnings list
        warnings: List[str] = []
        for view in memo.views:
            if _FALLBACK_RISK in view.key_risks or _FALLBACK_RISK in view.rationale:
                warnings.append(
                    f"{view.role}: model did not return structured JSON — "
                    "rationale contains raw text fallback."
                )
            for risk in view.key_risks:
                if risk.startswith("API error"):
                    warnings.append(f"{view.role}: API error — {risk}")
        if tracker.token_budget > 0 and tracker.total_tokens >= tracker.token_budget:
            warnings.append(
                f"Token budget reached or exceeded: "
                f"{tracker.total_tokens} / {tracker.token_budget} tokens used."
            )

        # Per-call cost records as structured list
        call_records = [
            {
                "agent": r.agent,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "cost_units": round(r.cost_units, 4),
                "latency_s": round(r.latency_s, 3),
            }
            for r in tracker.records
        ]

        result = {
            "recommendation": memo.recommendation,
            "summary": memo.summary,
            "profile": memo.profile,
            "question": memo.question,
            "briefing": memo.briefing,
            "views": [
                {
                    "role": v.role,
                    "model": v.model,
                    "stance": v.stance,
                    "conviction": v.conviction,
                    "rationale": v.rationale,
                    "key_risks": v.key_risks,
                    "evidence": v.evidence,
                }
                for v in memo.views
            ],
            "sources": memo.all_sources(),
            "cost_summary": tracker.render_summary(),
            "call_records": call_records,
            "warnings": warnings,
            "disclaimer": investment_firm.DISCLAIMER,
        }

        with _lock:
            _registry[run_id]["status"] = "done"
            _registry[run_id]["result"] = result

    except Exception as exc:  # noqa: BLE001
        with _lock:
            _registry[run_id]["status"] = "error"
            _registry[run_id]["error"] = str(exc)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", status_code=202)
def create_run(body: RunRequest) -> Dict[str, Any]:
    """Validate and enqueue a committee run; return run_id immediately (202)."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    firm = load_firm()
    available = profile_names(firm)
    if body.profile is not None:
        try:
            resolve_profile(body.profile, firm)
        except RosterError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"{exc}. Available profiles: {', '.join(available)}",
            ) from exc

    run_id = _new_id()
    entry: Dict[str, Any] = {
        "run_id": run_id,
        "status": "queued",
        "question": question,
        "profile": body.profile,
        "simple": body.simple,
        "created_at": _utcnow(),
        "result": None,
        "error": None,
    }
    with _lock:
        _registry[run_id] = entry

    thread = threading.Thread(
        target=_run_worker,
        args=(run_id, question, body.profile, body.simple),
        daemon=True,
        name=f"run-{run_id}",
    )
    thread.start()

    return {
        "run_id": run_id,
        "status": "queued",
        "disclaimer": investment_firm.DISCLAIMER,
    }


@router.get("")
def list_runs() -> Dict[str, Any]:
    """Return a list of all runs (metadata only, no results)."""
    with _lock:
        runs = [
            {
                "run_id": v["run_id"],
                "status": v["status"],
                "question": v["question"],
                "profile": v["profile"],
                "created_at": v["created_at"],
            }
            for v in _registry.values()
        ]
    return {"runs": runs, "disclaimer": investment_firm.DISCLAIMER}


@router.get("/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    """Poll a single run by id; includes result when status==done."""
    with _lock:
        entry = _registry.get(run_id)

    if entry is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")

    response: Dict[str, Any] = {
        "run_id": entry["run_id"],
        "status": entry["status"],
        "question": entry["question"],
        "profile": entry["profile"],
        "simple": entry["simple"],
        "created_at": entry["created_at"],
        "disclaimer": investment_firm.DISCLAIMER,
    }
    if entry["status"] == "done" and entry["result"] is not None:
        response["result"] = entry["result"]
    if entry["status"] == "error":
        response["error"] = entry["error"]
    return response
