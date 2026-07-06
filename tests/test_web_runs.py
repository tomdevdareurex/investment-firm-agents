"""Offline tests for POST/GET /api/runs — no network, no tokens.

run_committee is monkeypatched with a fake that builds a real Memo + RunTracker
from the actual schemas/costs classes so no LLM is ever called.
"""

from __future__ import annotations

import time
from typing import Tuple

import pytest

fastapi = pytest.importorskip(
    "fastapi", reason="fastapi not installed (run: pip install -e '.[api]')"
)
from fastapi.testclient import TestClient  # noqa: E402

import investment_firm  # noqa: E402
from investment_firm.core.schemas import (
    AnalystView,
    DebateTurn,
    Memo,
    Source,
)  # noqa: E402
from investment_firm.llm.costs import RunTracker  # noqa: E402

# ---------------------------------------------------------------------------
# Fake run_committee
# ---------------------------------------------------------------------------


def _make_memo(question: str = "Test question", profile: str = "balanced") -> Memo:
    views = [
        AnalystView(
            role="equity_analyst",
            model="gpt-4o-mini",
            stance="BULLISH",
            conviction=4,
            rationale="Strong earnings growth outlook.",
            key_risks=["valuation risk"],
            evidence=["S&P 500 P/E: 22x"],
            grounded=True,
            citations=[
                Source(
                    url="https://example.com/report",
                    title="Report",
                    origin="web:claude",
                )
            ],
        ),
        AnalystView(
            role="credit_analyst",
            model="gpt-4o-mini",
            stance="NEUTRAL",
            conviction=3,
            rationale="Spreads stable but elevated.",
            key_risks=["refinancing risk"],
            evidence=["IG spread: 120bps"],
        ),
    ]
    return Memo(
        question=question,
        profile=profile,
        recommendation="BUY",
        summary="Committee recommends BUY based on fundamental strength.",
        views=views,
        briefing="GDP growing at 2.5%. CPI at 3.1%.",
        sources=["ECB: rate 4.25%"],
        web_sources=[
            Source(
                url="https://example.com/report", title="Report", origin="web:claude"
            )
        ],
        debate=[
            DebateTurn(
                speaker="Senior Research Bull", text="Growth justifies the multiple."
            ),
            DebateTurn(
                speaker="Senior Research Bear", text="Valuation leaves no margin."
            ),
        ],
        debate_summary="BULLISH: the bull case is better supported on earnings.",
        synth_role="cio",
        synth_model="claude-4.8-opus",
        debate_judge_role="cio",
        debate_judge_model="claude-4.8-opus",
        disclaimer=investment_firm.DISCLAIMER,
    )


def _make_tracker() -> RunTracker:
    tracker = RunTracker(token_budget=60000)
    tracker.record("equity_analyst", "gpt-4o-mini", 500, 200, 1.2)
    tracker.record("credit_analyst", "gpt-4o-mini", 400, 180, 1.0)
    return tracker


def _fake_run_committee(
    question, *, profile=None, simple=False, tracker=None, on_event=None
) -> Tuple[Memo, RunTracker]:
    from investment_firm.core import events

    events.safe_emit(on_event, events.RUN_STARTED, detail=question)
    events.safe_emit(
        on_event, events.ANALYST_STARTED, agent="equity_analyst", model="gpt-4o-mini"
    )
    events.safe_emit(
        on_event,
        events.ANALYST_DONE,
        agent="equity_analyst",
        model="gpt-4o-mini",
        data={"stance": "BULLISH", "conviction": 4, "grounded": True},
    )
    memo = _make_memo(question=question, profile=profile or "balanced")
    t = _make_tracker()
    events.safe_emit(on_event, events.RUN_DONE, detail=memo.recommendation)
    return memo, t


def _fake_run_committee_error(
    question, *, profile=None, simple=False, tracker=None, on_event=None
):
    raise RuntimeError("Simulated orchestrator failure")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    """TestClient with run_committee monkeypatched to the happy-path fake."""
    monkeypatch.setattr(
        "investment_firm.interfaces.web.runs.run_committee",
        _fake_run_committee,
    )
    # Clear the registry between tests
    import investment_firm.interfaces.web.runs as runs_mod

    runs_mod._registry.clear()

    from investment_firm.interfaces.web.app import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def error_client(monkeypatch):
    """TestClient where run_committee always raises."""
    monkeypatch.setattr(
        "investment_firm.interfaces.web.runs.run_committee",
        _fake_run_committee_error,
    )
    import investment_firm.interfaces.web.runs as runs_mod

    runs_mod._registry.clear()

    from investment_firm.interfaces.web.app import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _wait_for_done(client, run_id: str, timeout: float = 5.0) -> dict:
    """Poll GET /api/runs/{run_id} until status in {done, error} or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.05)
    raise TimeoutError(f"Run {run_id} did not finish within {timeout}s")


# ---------------------------------------------------------------------------
# POST /api/runs — validation
# ---------------------------------------------------------------------------


class TestPostRunValidation:
    def test_empty_question_returns_400(self, client):
        resp = client.post("/api/runs", json={"question": ""})
        assert resp.status_code == 400
        assert "question" in resp.json()["detail"].lower()

    def test_whitespace_question_returns_400(self, client):
        resp = client.post("/api/runs", json={"question": "   "})
        assert resp.status_code == 400

    def test_unknown_profile_returns_400(self, client):
        resp = client.post(
            "/api/runs", json={"question": "Test?", "profile": "nonexistent_xyz"}
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data
        # Should mention available profiles
        assert any(p in data["detail"] for p in ("budget", "balanced", "Available"))

    def test_missing_body_returns_422(self, client):
        resp = client.post(
            "/api/runs", content=b"", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/runs — happy path
# ---------------------------------------------------------------------------


class TestPostRunHappy:
    def test_returns_202(self, client):
        resp = client.post("/api/runs", json={"question": "Is AAPL fairly valued?"})
        assert resp.status_code == 202

    def test_returns_run_id(self, client):
        resp = client.post("/api/runs", json={"question": "Is AAPL fairly valued?"})
        data = resp.json()
        assert "run_id" in data
        assert data["run_id"]

    def test_returns_status_queued_or_running(self, client):
        resp = client.post("/api/runs", json={"question": "Is AAPL fairly valued?"})
        data = resp.json()
        assert data["status"] in ("queued", "running")

    def test_response_includes_disclaimer(self, client):
        resp = client.post("/api/runs", json={"question": "EUR rates outlook?"})
        assert "disclaimer" in resp.json()

    def test_null_profile_is_accepted(self, client):
        resp = client.post("/api/runs", json={"question": "Outlook?", "profile": None})
        assert resp.status_code == 202

    def test_valid_named_profile_accepted(self, client):
        resp = client.post(
            "/api/runs", json={"question": "Outlook?", "profile": "budget"}
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /api/runs/{id} — polling
# ---------------------------------------------------------------------------


class TestGetRunById:
    def test_unknown_id_returns_404(self, client):
        resp = client.get("/api/runs/doesnotexist123")
        assert resp.status_code == 404

    def test_run_eventually_done(self, client):
        post = client.post("/api/runs", json={"question": "Should we buy EUR bonds?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert data["status"] == "done"

    def test_done_result_has_recommendation(self, client):
        post = client.post("/api/runs", json={"question": "Should we buy EUR bonds?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert "result" in data
        assert "recommendation" in data["result"]
        assert data["result"]["recommendation"] in ("BUY", "SELL", "HOLD", "AVOID")

    def test_done_result_has_views(self, client):
        post = client.post("/api/runs", json={"question": "Equity outlook?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        views = data["result"]["views"]
        assert isinstance(views, list)
        assert len(views) > 0
        view = views[0]
        assert "role" in view
        assert "model" in view
        assert "stance" in view
        assert "conviction" in view
        assert "rationale" in view
        assert "key_risks" in view
        assert "evidence" in view

    def test_done_result_has_sources(self, client):
        post = client.post("/api/runs", json={"question": "Credit outlook?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert "sources" in data["result"]
        assert isinstance(data["result"]["sources"], list)

    def test_done_result_has_web_sources_and_citations(self, client):
        post = client.post("/api/runs", json={"question": "Web sources?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        result = data["result"]
        assert result["web_sources"] == [
            {
                "url": "https://example.com/report",
                "title": "Report",
                "origin": "web:claude",
                "verified": True,
            }
        ]
        view = result["views"][0]
        assert view["grounded"] is True
        assert view["citations"][0]["url"] == "https://example.com/report"

    def test_result_includes_debate(self, client):
        post = client.post("/api/runs", json={"question": "Debate?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        result = data["result"]
        assert [t["speaker"] for t in result["debate"]] == [
            "Senior Research Bull",
            "Senior Research Bear",
        ]
        assert result["debate"][0]["text"] == "Growth justifies the multiple."
        assert result["debate_summary"].startswith("BULLISH")

    def test_result_includes_cio_attribution(self, client):
        post = client.post("/api/runs", json={"question": "Attribution?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        result = data["result"]
        assert result["synth_role"] == "cio"
        assert result["synth_model"] == "claude-4.8-opus"
        assert result["debate_judge_role"] == "cio"
        assert result["debate_judge_model"] == "claude-4.8-opus"

    def test_ungrounded_view_produces_warning(self, client):
        post = client.post("/api/runs", json={"question": "Grounding?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        # credit_analyst view in the fake memo has grounded=False (default)
        warnings = data["result"]["warnings"]
        assert any("credit_analyst" in w and "ungrounded" in w for w in warnings)

    def test_error_view_produces_error_warning_and_field(self, monkeypatch):
        """An ERROR-stance view yields a '<role>: ERROR — ...' warning + error key."""
        from investment_firm.core import errors as core_errors

        def _fake_error_run(
            question, *, profile=None, simple=False, tracker=None, on_event=None
        ):
            memo = _make_memo(question=question, profile=profile or "balanced")
            memo.views.append(
                core_errors.api_error_view("news_analyst", "gpt-4o-mini", "HTTP 500")
            )
            return memo, _make_tracker()

        monkeypatch.setattr(
            "investment_firm.interfaces.web.runs.run_committee", _fake_error_run
        )
        import investment_firm.interfaces.web.runs as runs_mod

        runs_mod._registry.clear()
        from investment_firm.interfaces.web.app import app

        with TestClient(app, raise_server_exceptions=True) as c:
            post = c.post("/api/runs", json={"question": "Error path?"})
            run_id = post.json()["run_id"]
            data = _wait_for_done(c, run_id)
        result = data["result"]
        warnings = result["warnings"]
        assert any(w.startswith("news_analyst: ERROR — ") for w in warnings)
        error_view = next(v for v in result["views"] if v["role"] == "news_analyst")
        assert error_view["stance"] == "ERROR"
        assert error_view["error"].startswith("API/completion failure")

    def test_view_payload_includes_error_field(self, client):
        post = client.post("/api/runs", json={"question": "Fields?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        for view in data["result"]["views"]:
            assert "error" in view

    def test_done_result_has_cost_summary(self, client):
        post = client.post("/api/runs", json={"question": "Rates view?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert "cost_summary" in data["result"]
        assert data["result"]["cost_summary"]

    def test_done_response_has_disclaimer(self, client):
        post = client.post("/api/runs", json={"question": "EM credit?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert "disclaimer" in data
        assert "Decision-support" in data["disclaimer"]

    def test_done_result_has_summary(self, client):
        post = client.post("/api/runs", json={"question": "Equity?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert "summary" in data["result"]
        assert data["result"]["summary"]


# ---------------------------------------------------------------------------
# GET /api/runs/{id} — error path
# ---------------------------------------------------------------------------


class TestGetRunError:
    def test_error_path_sets_status_error(self, error_client):
        post = error_client.post("/api/runs", json={"question": "Will this fail?"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(error_client, run_id)
        assert data["status"] == "error"

    def test_error_path_includes_message(self, error_client):
        post = error_client.post("/api/runs", json={"question": "Fail test"})
        run_id = post.json()["run_id"]
        data = _wait_for_done(error_client, run_id)
        assert "error" in data
        assert data["error"]  # non-empty error message

    def test_error_path_does_not_crash_app(self, error_client):
        """Server must remain healthy after a failed run."""
        post = error_client.post("/api/runs", json={"question": "Crash test"})
        run_id = post.json()["run_id"]
        _wait_for_done(error_client, run_id)
        health = error_client.get("/api/health")
        assert health.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/runs — list
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_returns_200(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_lists_posted_runs(self, client):
        client.post("/api/runs", json={"question": "List test A"})
        client.post("/api/runs", json={"question": "List test B"})
        data = client.get("/api/runs").json()
        assert "runs" in data
        assert len(data["runs"]) >= 2

    def test_list_entries_have_required_fields(self, client):
        client.post("/api/runs", json={"question": "Field check"})
        data = client.get("/api/runs").json()
        for entry in data["runs"]:
            assert "run_id" in entry
            assert "status" in entry
            assert "question" in entry
            assert "created_at" in entry

    def test_list_includes_disclaimer(self, client):
        data = client.get("/api/runs").json()
        assert "disclaimer" in data
        assert data["disclaimer"]


def _parse_sse(body: str) -> list:
    """Extract JSON payloads from step-event ``data:`` frames in an SSE body.

    Frames carrying an ``event:`` line (the terminal ``end`` frame, keep-alives)
    are skipped so only ordered step events are returned.
    """
    import json as _json

    out = []
    for frame in body.split("\n\n"):
        lines = frame.splitlines()
        if any(line.startswith("event:") for line in lines):
            continue
        for line in lines:
            if line.startswith("data: "):
                try:
                    out.append(_json.loads(line[len("data: ") :]))
                except ValueError:
                    pass
    return out


class TestRunEvents:
    def test_events_stream_yields_ordered_events(self, client):
        run_id = client.post("/api/runs", json={"question": "Stream?"}).json()["run_id"]
        _wait_for_done(client, run_id)
        resp = client.get(f"/api/runs/{run_id}/events")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        payloads = _parse_sse(resp.text)
        kinds = [p["kind"] for p in payloads]
        assert kinds[0] == "run_started"
        assert kinds[-1] == "run_done"
        assert "analyst_started" in kinds
        # seq is strictly increasing.
        seqs = [p["seq"] for p in payloads]
        assert seqs == sorted(seqs)
        assert "event: end" in resp.text

    def test_events_after_cursor_skips_earlier(self, client):
        run_id = client.post("/api/runs", json={"question": "Cursor?"}).json()["run_id"]
        _wait_for_done(client, run_id)
        full = _parse_sse(client.get(f"/api/runs/{run_id}/events").text)
        assert len(full) >= 2
        first_seq = full[0]["seq"]
        resp = client.get(f"/api/runs/{run_id}/events?after={first_seq}")
        payloads = _parse_sse(resp.text)
        assert all(p["seq"] > first_seq for p in payloads)
        assert len(payloads) == len(full) - 1

    def test_events_unknown_run_404(self, client):
        resp = client.get("/api/runs/deadbeef/events")
        assert resp.status_code == 404

    def test_poll_reports_event_count(self, client):
        run_id = client.post("/api/runs", json={"question": "Count?"}).json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert data["event_count"] >= 1


class TestRunChat:
    def test_chat_on_done_run_returns_answer(self, client, monkeypatch):
        from conftest import FakeLLM, openai_text

        run_id = client.post("/api/runs", json={"question": "Chat?"}).json()["run_id"]
        _wait_for_done(client, run_id)

        fake = FakeLLM([openai_text("The recommendation was BUY because of X.")])
        monkeypatch.setattr("investment_firm.llm.client.chat", fake)

        resp = client.post(
            f"/api/runs/{run_id}/chat",
            json={"message": "Explain the call", "model": "gpt-4.1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "BUY" in data["answer"]
        assert data["message_id"] == 1
        # The consultant's system prompt saw the run's memo recommendation.
        system_msg = fake.calls[0][1][0]["content"]
        assert "RECOMMENDATION" in system_msg.upper()

    def test_chat_empty_message_400(self, client):
        run_id = client.post("/api/runs", json={"question": "Chat?"}).json()["run_id"]
        _wait_for_done(client, run_id)
        resp = client.post(f"/api/runs/{run_id}/chat", json={"message": "  "})
        assert resp.status_code == 400

    def test_chat_unknown_run_404(self, client):
        resp = client.post("/api/runs/deadbeef/chat", json={"message": "hi"})
        assert resp.status_code == 404

    def test_chat_on_unfinished_run_409(self, error_client):
        run_id = error_client.post("/api/runs", json={"question": "boom"}).json()[
            "run_id"
        ]
        _wait_for_done(error_client, run_id)  # ends in error → not done
        resp = error_client.post(f"/api/runs/{run_id}/chat", json={"message": "hi"})
        assert resp.status_code == 409
