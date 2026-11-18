"""Offline tests for the free alt-data tools (USAspending, Senate LDA, EDGAR Form 4).

All HTTP is mocked via monkeypatching ``requests.get`` / ``requests.post`` —
no network, no tokens.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from investment_firm import endpoints
from investment_firm.core.tools import ToolRegistry, default_data_tools
from investment_firm.core.tools import altdata_free as alt
from investment_firm.core.tools.base import ToolError


class _Resp:
    def __init__(self, status=200, text="", json_data=None, headers=None):
        self.status_code = status
        self.text = text
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def _patch_get(monkeypatch, handler):
    import requests

    monkeypatch.setattr(requests, "get", handler)


def _patch_post(monkeypatch, handler):
    import requests

    monkeypatch.setattr(requests, "post", handler)


class TestEndpoints:
    def test_new_endpoints_present_and_https(self):
        for key in (
            "data.usaspending_awards",
            "data.senate_lda_filings",
            "data.edgar_fts",
        ):
            assert urlsplit(endpoints.url(key)).scheme == "https"
        archive = endpoints.url("data.edgar_archives", cik="320193", accession="x")
        assert archive.endswith("/320193/x/")


class TestGovContracts:
    _ROWS = {
        "results": [
            {
                "Award ID": "W911QY23C0001",
                "Recipient Name": "LOCKHEED MARTIN CORPORATION",
                "Award Amount": 1250000.5,
                "Awarding Agency": "Department of Defense",
                "Start Date": "2026-01-01",
                "End Date": "2027-12-31",
                "Description": "x" * 300,
            },
            {
                "Award ID": "FA860123C0002",
                "Recipient Name": "LOCKHEED MARTIN CORPORATION",
                "Award Amount": "750000",
                "Awarding Agency": "Department of the Air Force",
                "Start Date": "2026-02-01",
                "End Date": None,
                "Description": None,
            },
        ]
    }

    def test_happy_path_posts_filters_and_sums(self, monkeypatch):
        captured = {}

        def handler(url, **kw):
            captured["url"] = url
            captured["json"] = kw.get("json")
            return _Resp(json_data=self._ROWS)

        _patch_post(monkeypatch, handler)
        out = alt.get_gov_contracts("Lockheed Martin", limit=5, fiscal_year=2026)
        assert urlsplit(captured["url"]).scheme == "https"
        filters = captured["json"]["filters"]
        assert filters["recipient_search_text"] == ["Lockheed Martin"]
        assert filters["award_type_codes"] == ["A", "B", "C", "D"]
        assert filters["time_period"] == [
            {"start_date": "2025-10-01", "end_date": "2026-09-30"}
        ]
        assert captured["json"]["limit"] == 5
        assert out["count"] == 2
        assert out["total_amount_usd"] == 2000000.5
        assert out["awards"][1]["amount_usd"] == 750000.0
        assert len(out["awards"][0]["description"]) == 200
        assert out["fiscal_year"] == 2026
        assert "USAspending" in out["source"]
        assert out["as_of"]

    def test_limit_is_clamped(self, monkeypatch):
        captured = {}

        def handler(url, **kw):
            captured["json"] = kw.get("json")
            return _Resp(json_data={"results": []})

        _patch_post(monkeypatch, handler)
        out = alt.get_gov_contracts("ACME", limit=999)
        assert captured["json"]["limit"] == 25
        assert out["count"] == 0
        assert out["awards"] == []

    def test_http_error_raises_with_status(self, monkeypatch):
        _patch_post(monkeypatch, lambda url, **kw: _Resp(status=429))
        with pytest.raises(ToolError) as exc:
            alt.get_gov_contracts("ACME")
        assert "429" in str(exc.value)

    def test_empty_recipient_rejected(self):
        with pytest.raises(ToolError):
            alt.get_gov_contracts("   ")

    def test_non_json_raises(self, monkeypatch):
        _patch_post(monkeypatch, lambda url, **kw: _Resp(text="<html>"))
        with pytest.raises(ToolError):
            alt.get_gov_contracts("ACME")


class TestLobbying:
    _ROWS = {
        "count": 42,
        "results": [
            {
                "filing_year": 2026,
                "filing_period": "first_quarter",
                "filing_period_display": "1st Quarter (Jan 1 - Mar 31)",
                "filing_type": "Q1",
                "filing_type_display": "1st Quarter - Report",
                "income": "120000.00",
                "expenses": None,
                "dt_posted": "2026-04-20T12:00:00",
                "registrant": {"name": "Big Lobby LLC"},
                "client": {"name": "ACME CORP"},
                "lobbying_activities": [
                    {"general_issue_code_display": "Taxation"},
                    {"general_issue_code_display": "Taxation"},
                    {"general_issue_code": "ENG"},
                ],
            }
        ],
    }

    def test_happy_path_anonymous(self, monkeypatch):
        monkeypatch.delenv("SENATE_LDA_API_KEY", raising=False)
        captured = {}

        def handler(url, **kw):
            captured.update(kw)
            return _Resp(json_data=self._ROWS)

        _patch_get(monkeypatch, handler)
        out = alt.get_lobbying("ACME Corp", limit=5)
        assert captured["params"]["client_name"] == "ACME Corp"
        assert captured["params"]["page_size"] == 5
        assert "Authorization" not in captured["headers"]
        assert out["count"] == 1
        assert out["total_reported"] == 42
        row = out["filings"][0]
        assert row["registrant"] == "Big Lobby LLC"
        assert row["income_usd"] == 120000.0
        assert row["expenses_usd"] is None
        assert row["issues"] == ["Taxation", "ENG"]
        assert "Senate" in out["source"]
        assert out["as_of"]

    def test_api_key_header_when_env_set(self, monkeypatch):
        monkeypatch.setenv("SENATE_LDA_API_KEY", "sekrit")
        captured = {}

        def handler(url, **kw):
            captured.update(kw)
            return _Resp(json_data={"count": 0, "results": []})

        _patch_get(monkeypatch, handler)
        out = alt.get_lobbying("ACME")
        assert captured["headers"]["Authorization"] == "Token sekrit"
        assert out["count"] == 0

    def test_http_error_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(status=500))
        with pytest.raises(ToolError) as exc:
            alt.get_lobbying("ACME")
        assert "500" in str(exc.value)


class TestInsiderTrades:
    _HITS = {
        "hits": {
            "total": {"value": 2},
            "hits": [
                {
                    "_source": {
                        "file_date": "2026-05-04",
                        "period_ending": "2026-05-01",
                        "form": "4",
                        "adsh": "0000320193-26-000042",
                        "ciks": ["0001214156", "0000320193"],
                        "display_names": [
                            "Cook Timothy D  (CIK 0001214156)",
                            "Apple Inc.  (AAPL)  (CIK 0000320193)",
                        ],
                    }
                },
                {"_source": {"file_date": "2026-04-30", "adsh": "", "ciks": []}},
            ],
        }
    }

    def test_happy_path_builds_https_urls(self, monkeypatch):
        captured = {}

        def handler(url, **kw):
            captured["url"] = url
            captured.update(kw)
            return _Resp(json_data=self._HITS)

        _patch_get(monkeypatch, handler)
        out = alt.get_insider_trades("aapl", limit=5)
        assert captured["params"]["forms"] == "4"
        assert captured["params"]["q"] == '"AAPL"'
        assert captured["params"]["dateRange"] == "custom"
        assert "User-Agent" in captured["headers"]
        assert out["query"] == "AAPL"
        assert out["count"] == 2
        assert out["total_hits"] == 2
        first = out["filings"][0]
        assert first["reporters"] == ["Cook Timothy D"]
        assert first["issuer"].startswith("Apple Inc.")
        assert first["accession"] == "0000320193-26-000042"
        parts = urlsplit(first["url"])
        assert parts.scheme == "https"
        assert "/320193/000032019326000042/" in parts.path
        assert out["filings"][1]["url"] == ""
        assert "Form 4" in out["source"]
        assert out["caveat"]

    def test_sec_user_agent_env_is_used(self, monkeypatch):
        monkeypatch.setenv("SEC_USER_AGENT", "me me@example.org")
        captured = {}

        def handler(url, **kw):
            captured.update(kw)
            return _Resp(json_data={"hits": {"hits": []}})

        _patch_get(monkeypatch, handler)
        out = alt.get_insider_trades("AAPL")
        assert captured["headers"]["User-Agent"] == "me me@example.org"
        assert out["count"] == 0

    def test_http_error_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(status=403))
        with pytest.raises(ToolError) as exc:
            alt.get_insider_trades("AAPL")
        assert "403" in str(exc.value)

    def test_unparseable_body_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data={"nope": 1}))
        with pytest.raises(ToolError):
            alt.get_insider_trades("AAPL")


class TestRegistry:
    def test_tools_registered_in_default_data_tools(self):
        registry = ToolRegistry(default_data_tools())
        for name in ("get_gov_contracts", "get_lobbying", "get_insider_trades"):
            assert name in registry
        assert len(registry) == 16

    def test_dispatch_returns_provenance(self, monkeypatch):
        _patch_get(
            monkeypatch,
            lambda url, **kw: _Resp(json_data={"count": 0, "results": []}),
        )
        registry = ToolRegistry(default_data_tools())
        payload = json.loads(registry.dispatch("get_lobbying", {"client_name": "X"}))
        assert payload["count"] == 0
        assert "source" in payload and "as_of" in payload

    def test_schemas_are_valid_function_tools(self):
        for tool in alt.default_altdata_tools():
            schema = tool.schema()
            assert schema["type"] == "function"
            assert schema["function"]["parameters"]["type"] == "object"
            assert schema["function"]["parameters"]["required"]
