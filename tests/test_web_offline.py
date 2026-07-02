"""Offline tests for the FastAPI web interface — no network, no tokens.

Uses fastapi.testclient.TestClient (httpx transport, no real server).
Skipped automatically if fastapi is not installed (.[api] extra not present).
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed (run: pip install -e '.[api]')")
from fastapi.testclient import TestClient  # noqa: E402

from investment_firm.interfaces.web.app import app  # noqa: E402
import investment_firm  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_contains_version(self, client):
        data = client.get("/api/health").json()
        assert data["version"] == investment_firm.__version__

    def test_contains_disclaimer(self, client):
        data = client.get("/api/health").json()
        assert "disclaimer" in data
        assert "Decision-support" in data["disclaimer"]


# ---------------------------------------------------------------------------
# GET /api/profiles
# ---------------------------------------------------------------------------

class TestProfiles:
    def test_returns_200(self, client):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200

    def test_lists_yaml_profiles(self, client):
        data = client.get("/api/profiles").json()
        profiles = data.get("profiles", {})
        assert "budget" in profiles
        assert "balanced" in profiles
        assert "premium" in profiles

    def test_profiles_include_tier_models(self, client):
        data = client.get("/api/profiles").json()
        balanced = data["profiles"]["balanced"]
        assert "WORKER" in balanced
        assert isinstance(balanced["WORKER"], list)
        assert len(balanced["WORKER"]) > 0


# ---------------------------------------------------------------------------
# GET /api/preview
# ---------------------------------------------------------------------------

class TestPreview:
    def test_happy_path_returns_roles(self, client):
        resp = client.get("/api/preview?profile=budget&simple=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert len(data["roles"]) > 0

    def test_roles_have_required_fields(self, client):
        data = client.get("/api/preview?profile=budget&simple=true").json()
        for role in data["roles"]:
            assert "name" in role
            assert "tier" in role
            assert "model" in role
            assert "mandate" in role

    def test_roles_have_models(self, client):
        data = client.get("/api/preview?profile=balanced&simple=false").json()
        for role in data["roles"]:
            assert role["model"], f"Role {role['name']} has empty model"

    def test_budget_present(self, client):
        data = client.get("/api/preview?profile=budget").json()
        assert "run_token_budget" in data
        assert data["run_token_budget"] > 0

    def test_profile_echoed(self, client):
        data = client.get("/api/preview?profile=premium").json()
        assert data["profile"] == "premium"

    def test_disclaimer_in_preview(self, client):
        data = client.get("/api/preview?profile=balanced").json()
        assert "disclaimer" in data
        assert data["disclaimer"]

    def test_simple_true_has_fixed_analysts(self, client):
        data = client.get("/api/preview?profile=budget&simple=true").json()
        role_names = [r["name"] for r in data["roles"]]
        assert "equity_analyst" in role_names
        assert "credit_analyst" in role_names
        assert "rates_analyst" in role_names

    def test_simple_false_includes_librarian(self, client):
        data = client.get("/api/preview?profile=budget&simple=false").json()
        role_names = [r["name"] for r in data["roles"]]
        assert "research_librarian" in role_names

    def test_unknown_profile_returns_400(self, client):
        resp = client.get("/api/preview?profile=nonexistent_xyz")
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data
        # Should mention available profiles
        assert "budget" in data["detail"] or "Available" in data["detail"]


# ---------------------------------------------------------------------------
# GET / (HTML index)
# ---------------------------------------------------------------------------

class TestIndex:
    def test_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_html_contains_key_elements(self, client):
        text = client.get("/").text
        assert "Investment" in text or "IC Agents" in text
        # The preview form must be present
        assert "preview" in text.lower() or "Preview" in text
