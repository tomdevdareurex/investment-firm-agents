"""Offline tests for the /api/backend endpoints and the UI backend switch."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from investment_firm.interfaces.web.app import app  # noqa: E402
from investment_firm.llm import backends  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_backend_state(monkeypatch):
    monkeypatch.delenv("IFA_LLM_BACKEND", raising=False)
    backends.reset_backend()
    yield
    backends.reset_backend()


@pytest.fixture()
def client_app():
    return TestClient(app)


def test_get_backend_defaults_to_playground(client_app):
    resp = client_app.get("/api/backend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "playground"
    assert set(data["available"]) == {"playground", "databricks"}
    assert data["capabilities"]["web_search"] is True
    assert data["capabilities"]["tools"] is True
    assert "note" not in data


def test_post_backend_switches_to_databricks(client_app):
    resp = client_app.post("/api/backend", json={"backend": "databricks"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "databricks"
    assert data["capabilities"]["web_search"] is False
    assert "data tools" in data["note"]

    # GET reflects the switch
    follow = client_app.get("/api/backend").json()
    assert follow["backend"] == "databricks"


def test_post_backend_unknown_returns_400(client_app):
    resp = client_app.post("/api/backend", json={"backend": "bedrock"})
    assert resp.status_code == 400
    assert "Unknown LLM backend" in resp.json()["detail"]
    # active backend unchanged
    assert client_app.get("/api/backend").json()["backend"] == "playground"


def test_index_contains_backend_selector(client_app):
    html = client_app.get("/").text
    assert 'id="backend"' in html
    assert 'id="backend-note"' in html
