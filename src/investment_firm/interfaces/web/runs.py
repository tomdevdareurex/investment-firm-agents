"""In-memory run registry and /api/runs endpoints.

Routes
------
POST /api/runs          Start a committee run (202 + run_id).
GET  /api/runs          List all runs (status + metadata only).
GET  /api/runs/{run_id} Poll a run; when done includes full result envelope.
GET  /api/runs/{run_id}/report.html  Download the self-contained HTML report.

The registry is a plain dict protected by a threading.Lock.
Runs are daemon threads so they die when the server exits; no persistence.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Literal, Optional

try:
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import HTMLResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError as _exc:  # pragma: no cover
    raise RuntimeError(
        "FastAPI not installed. Run:\n"
        '    .venv\\Scripts\\python.exe -m pip install -e ".[api]"'
    ) from _exc

import investment_firm
from investment_firm.core import events
from investment_firm.core.orchestrator import run_committee
from investment_firm.core.roster import (
    RosterError,
    load_firm,
    profile_names,
    resolve_profile,
)
from investment_firm.core.schemas import Memo
from investment_firm.interfaces.report import build_run_result, render_committee_report
from investment_firm.interfaces.report.payload import _FALLBACK_RISK  # noqa: F401

# ---------------------------------------------------------------------------
# Registry (in-memory, thread-safe)
# ---------------------------------------------------------------------------

_lock: threading.Lock = threading.Lock()
_registry: Dict[str, Dict[str, Any]] = {}

# Max step events retained per run (seq stays monotonic even after trimming).
_EVENT_CAP = 2000


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
    horizon: Literal["short", "medium", "long"] = "short"


class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


def _make_emit(run_id: str):
    """Return an ``on_event`` sink that buffers step events on the registry entry."""

    def _emit(event: events.StepEvent) -> None:
        with _lock:
            entry = _registry.get(run_id)
            if entry is None:
                return
            entry["event_seq"] += 1
            payload = events.to_dict(event)
            payload["seq"] = entry["event_seq"]
            buf = entry["events"]
            buf.append(payload)
            if len(buf) > _EVENT_CAP:
                del buf[0]

    return _emit


def _run_worker(
    run_id: str,
    question: str,
    profile: Optional[str],
    simple: bool,
    horizon: str = "short",
) -> None:
    """Execute run_committee in a daemon thread and store the result."""
    with _lock:
        _registry[run_id]["status"] = "running"

    emit = _make_emit(run_id)
    try:
        memo, tracker = run_committee(
            question, profile=profile, simple=simple, on_event=emit, horizon=horizon
        )
        result = build_run_result(memo, tracker, horizon=horizon, run_id=run_id)

        with _lock:
            _registry[run_id]["status"] = "done"
            _registry[run_id]["result"] = result
            _registry[run_id]["memo"] = memo

    except Exception as exc:  # noqa: BLE001
        events.safe_emit(emit, events.RUN_ERROR, detail=str(exc))
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
        "horizon": body.horizon,
        "created_at": _utcnow(),
        "result": None,
        "error": None,
        "events": [],
        "event_seq": 0,
        "memo": None,
        "chat_history": [],
    }
    with _lock:
        _registry[run_id] = entry

    thread = threading.Thread(
        target=_run_worker,
        args=(run_id, question, body.profile, body.simple, body.horizon),
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
                "horizon": v.get("horizon", "short"),
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
        "horizon": entry.get("horizon", "short"),
        "created_at": entry["created_at"],
        "event_count": entry.get("event_seq", 0),
        "disclaimer": investment_firm.DISCLAIMER,
    }
    if entry["status"] == "done" and entry["result"] is not None:
        response["result"] = entry["result"]
    if entry["status"] == "error":
        response["error"] = entry["error"]
    return response


def completed_memo(run_id: str) -> Memo:
    """Return the memo of a finished run (``KeyError`` unknown, ``RuntimeError`` unfinished)."""
    with _lock:
        entry = _registry.get(run_id)
        if entry is None:
            raise KeyError(run_id)
        if entry["status"] != "done" or entry.get("memo") is None:
            raise RuntimeError("run is not finished")
        return entry["memo"]


@router.get("/{run_id}/report.html")
def run_report(run_id: str) -> HTMLResponse:
    """Download the self-contained HTML report of a finished run."""
    with _lock:
        entry = _registry.get(run_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
        result = entry.get("result")
        if entry["status"] != "done" or result is None:
            raise HTTPException(
                status_code=409, detail="run is not finished; no report yet"
            )
    return HTMLResponse(
        render_committee_report(result),
        headers={
            "Content-Disposition": f'attachment; filename="ic-report-{run_id}.html"'
        },
    )


def _event_generator(run_id: str, after: int) -> Iterator[str]:
    """Yield SSE frames for a run's step events until it reaches a terminal state.

    A plain sync generator: FastAPI runs it in a threadpool, which bridges the
    daemon-thread producer to the async response. Emits ``data:`` frames for each
    new event (seq-ordered), a final ``event: end`` frame, and periodic keep-alive
    comments while idle.
    """
    cursor = after
    idle = 0
    while True:
        with _lock:
            entry = _registry.get(run_id)
            if entry is None:
                yield f"event: end\ndata: {json.dumps({'status': 'missing'})}\n\n"
                return
            new = [e for e in entry["events"] if e["seq"] > cursor]
            status = entry["status"]
        if new:
            idle = 0
            for ev in new:
                cursor = ev["seq"]
                yield f"data: {json.dumps(ev)}\n\n"
        if status in ("done", "error"):
            # Flush anything that landed after the last snapshot, then terminate.
            with _lock:
                entry = _registry.get(run_id)
                remaining = (
                    [e for e in entry["events"] if e["seq"] > cursor] if entry else []
                )
            for ev in remaining:
                cursor = ev["seq"]
                yield f"data: {json.dumps(ev)}\n\n"
            yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
            return
        idle += 1
        if idle % 30 == 0:
            yield ": keep-alive\n\n"
        time.sleep(0.5)


@router.get("/{run_id}/events")
def stream_events(run_id: str, after: int = 0) -> StreamingResponse:
    """Server-Sent Events stream of a run's coarse step events (seq > ``after``)."""
    with _lock:
        exists = run_id in _registry
    if not exists:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return StreamingResponse(
        _event_generator(run_id, after), media_type="text/event-stream"
    )


@router.post("/{run_id}/chat")
def chat_with_run(run_id: str, body: ChatRequest) -> Dict[str, Any]:
    """Ask the read-only quant consultant about a completed run.

    The consultant is analysis-only: a read-only tool subset, no write/order
    capability, scoped to this run's memo + step events. Runs synchronously
    (a bounded call) and also appends chat step events to the run's buffer so a
    concurrent SSE reader can observe them.
    """
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be empty")

    with _lock:
        entry = _registry.get(run_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
        if entry["status"] != "done" or entry.get("memo") is None:
            raise HTTPException(
                status_code=409, detail="run is not finished; cannot chat yet"
            )
        memo = entry["memo"]
        events_log = list(entry["events"])
        history = list(entry["chat_history"])

    # Import here so the web layer stays importable without the consultant deps.
    from investment_firm.core.consultant import Consultant, RunContext

    context = RunContext(memo, events_log)
    consultant = Consultant(context, model=body.model or None)
    emit = _make_emit(run_id)
    answer = consultant.ask(message, history=history, on_event=emit, stream=False)

    with _lock:
        entry = _registry.get(run_id)
        message_id = 0
        if entry is not None:
            entry["chat_history"].append({"role": "user", "content": message})
            entry["chat_history"].append({"role": "assistant", "content": answer})
            message_id = len(entry["chat_history"]) // 2

    return {
        "run_id": run_id,
        "message_id": message_id,
        "answer": answer,
        "model": consultant.model,
        "disclaimer": investment_firm.DISCLAIMER,
    }
