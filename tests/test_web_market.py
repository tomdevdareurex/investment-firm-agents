"""Offline tests for market-data web endpoints — no network, no tokens."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

fastapi = pytest.importorskip(
    "fastapi",
    reason="fastapi not installed (run: pip install -e '.[api]')",
)
from fastapi.testclient import TestClient  # noqa: E402

from investment_firm.interfaces.web.market_data import (  # noqa: E402
    MarketDataProviderError,
    MarketDataValidationError,
    get_price_history,
)


def _fake_history_payload(
    ticker: str,
    period: str,
    interval: str,
    *,
    close: float = 101.0,
) -> Dict[str, Any]:
    return {
        "provider": "yfinance",
        "ticker": ticker.upper(),
        "period": period,
        "interval": interval,
        "source": "yfinance (Yahoo Finance)",
        "as_of": "2026-07-02",
        "ohlc": [
            {
                "time": "2026-07-01",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": close,
            },
            {
                "time": "2026-07-02",
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": close + 1.0,
            },
        ],
        "volume": [
            {"time": "2026-07-01", "value": 1000},
            {"time": "2026-07-02", "value": 1200},
        ],
    }


@pytest.fixture()
def market_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cache_path = tmp_path / "market_data.sqlite"
    monkeypatch.setenv("INVESTMENT_FIRM_MARKET_CACHE", str(cache_path))

    import investment_firm.interfaces.web.market_data as market_data

    calls: List[tuple[str, str, str]] = []

    def fake_fetch(ticker: str, period: str, interval: str) -> Dict[str, Any]:
        calls.append((ticker, period, interval))
        return _fake_history_payload(ticker, period, interval, close=100.0 + len(calls))

    monkeypatch.setattr(market_data, "fetch_yfinance_price_history", fake_fetch)

    from investment_firm.interfaces.web.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, calls, cache_path


class TestPriceHistoryEndpoint:
    def test_returns_chart_ready_price_history(self, market_client):
        client, calls, cache_path = market_client

        resp = client.get("/api/market/price-history?ticker=aapl&period=5d&interval=1d")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["period"] == "5d"
        assert data["interval"] == "1d"
        assert data["ohlc"] == [
            {
                "time": "2026-07-01",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
            },
            {
                "time": "2026-07-02",
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
            },
        ]
        assert data["volume"][0] == {"time": "2026-07-01", "value": 1000}
        assert data["cache"]["enabled"] is True
        assert data["cache"]["hit"] is False
        assert data["cache"]["stored"] is True
        assert cache_path.exists()
        assert calls == [("AAPL", "5d", "1d")]

    def test_technicals_param_is_accepted_and_degrades_gracefully(self, market_client):
        client, _calls, _cache_path = market_client

        # The fake fixture returns only two bars — too little for a summary — so
        # the endpoint must still succeed and simply omit the technicals block.
        resp = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&technicals=true"
        )

        assert resp.status_code == 200
        assert "technicals" not in resp.json()

    def test_second_request_uses_saved_cache(self, market_client):
        client, calls, _cache_path = market_client

        first = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )
        second = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["ohlc"] == second.json()["ohlc"]
        assert first.json()["cache"]["hit"] is False
        assert second.json()["cache"]["hit"] is True
        assert second.json()["cache"]["ttl_seconds"] == 900
        assert calls == [("AAPL", "5d", "1d")]

    def test_stricter_ttl_refetches_existing_saved_data(self, market_client):
        client, calls, _cache_path = market_client

        first = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&ttl_seconds=900"
        )
        stricter = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&ttl_seconds=0"
        )

        assert first.status_code == 200
        assert stricter.status_code == 200
        assert first.json()["ohlc"] != stricter.json()["ohlc"]
        assert stricter.json()["cache"]["hit"] is False
        assert stricter.json()["cache"]["ttl_seconds"] == 0
        assert len(calls) == 2

    def test_force_refresh_bypasses_saved_cache(self, market_client):
        client, calls, _cache_path = market_client

        first = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )
        refreshed = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&force_refresh=true"
        )

        assert first.status_code == 200
        assert refreshed.status_code == 200
        assert first.json()["ohlc"] != refreshed.json()["ohlc"]
        assert refreshed.json()["cache"]["hit"] is False
        assert len(calls) == 2

    def test_cache_can_be_disabled(self, market_client):
        client, calls, _cache_path = market_client

        first = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&cache=false"
        )
        second = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&cache=false"
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["cache"]["enabled"] is False
        assert second.json()["cache"]["enabled"] is False
        assert first.json()["ohlc"] != second.json()["ohlc"]
        assert len(calls) == 2

    def test_rejects_invalid_ticker(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get("/api/market/price-history?ticker=AAPL;DROP&period=5d")

        assert resp.status_code == 422

    def test_corrupt_saved_cache_is_treated_as_miss(self, market_client):
        client, calls, cache_path = market_client

        first = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )
        assert first.status_code == 200

        with sqlite3.connect(str(cache_path)) as conn:
            conn.execute(
                "UPDATE market_data_cache SET fetched_at_epoch = ?", ("not-a-number",)
            )
            conn.commit()

        refreshed = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )

        assert refreshed.status_code == 200
        assert refreshed.json()["cache"]["hit"] is False
        assert first.json()["ohlc"] != refreshed.json()["ohlc"]
        assert len(calls) == 2

    def test_malformed_saved_payload_is_treated_as_miss(self, market_client):
        client, calls, cache_path = market_client

        first = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )
        assert first.status_code == 200

        with sqlite3.connect(str(cache_path)) as conn:
            conn.execute(
                "UPDATE market_data_cache SET payload_json = ?", ('{"ohlc": []}',)
            )
            conn.commit()

        refreshed = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
        )

        assert refreshed.status_code == 200
        assert refreshed.json()["cache"]["hit"] is False
        assert first.json()["ohlc"] != refreshed.json()["ohlc"]
        assert len(calls) == 2

    def test_provider_error_returns_502_with_truncated_cause(
        self, market_client, monkeypatch
    ):
        client, _calls, _cache_path = market_client

        import investment_firm.interfaces.web.market_data as market_data

        def fail_fetch(_ticker: str, _period: str, _interval: str) -> Dict[str, Any]:
            raise MarketDataProviderError(
                "Yahoo Finance fetch failed (CertificateVerifyError)" + "x" * 300
            )

        monkeypatch.setattr(market_data, "fetch_yfinance_price_history", fail_fetch)

        resp = client.get("/api/market/price-history?ticker=MSFT&period=5d&interval=1d")

        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail.startswith(
            "market data provider unavailable: Yahoo Finance fetch failed (CertificateVerifyError)"
        )
        assert len(detail) <= len("market data provider unavailable: ") + 120


class TestIndicatorOverlays:
    def test_indicators_query_attaches_overlays(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d"
            "&indicators=close_50_sma,rsi"
        )

        assert resp.status_code == 200
        data = resp.json()
        overlays = data["indicators"]
        assert set(overlays) == {"close_50_sma", "rsi"}
        # One point per bar, aligned to the OHLC time axis (chart == agent engine).
        assert [p["time"] for p in overlays["close_50_sma"]] == [
            "2026-07-01",
            "2026-07-02",
        ]
        assert all("value" in p for p in overlays["close_50_sma"])

    def test_no_indicators_param_omits_overlays(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get("/api/market/price-history?ticker=AAPL&period=5d&interval=1d")

        assert resp.status_code == 200
        assert "indicators" not in resp.json()

    def test_unknown_indicator_returns_400(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get(
            "/api/market/price-history?ticker=AAPL&period=5d&interval=1d&indicators=bogus"
        )

        assert resp.status_code == 400
        assert "unknown indicator" in resp.json()["detail"]


class TestSslResolution:
    def test_ca_bundle_env_wins_over_verify_toggle(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.setenv("REQUESTS_CA_BUNDLE", r"C:\Users\wn686\corp-ca.pem")
        monkeypatch.setenv("INVESTMENT_FIRM_MARKET_VERIFY_SSL", "false")

        assert market_data._resolve_verify_ssl() == r"C:\Users\wn686\corp-ca.pem"

    def test_curl_ca_bundle_used_when_requests_bundle_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.setenv("CURL_CA_BUNDLE", "/etc/corp-ca.pem")

        assert market_data._resolve_verify_ssl() == "/etc/corp-ca.pem"

    def test_explicit_false_toggle_disables_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.setenv("INVESTMENT_FIRM_MARKET_VERIFY_SSL", "false")

        assert market_data._resolve_verify_ssl() is False

    def test_default_is_full_verification(self, monkeypatch: pytest.MonkeyPatch):
        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("INVESTMENT_FIRM_MARKET_VERIFY_SSL", raising=False)

        assert market_data._resolve_verify_ssl() is True

    def test_default_verification_uses_no_custom_session(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("INVESTMENT_FIRM_MARKET_VERIFY_SSL", raising=False)

        assert market_data._build_yfinance_session() is None

    def test_verify_off_builds_curl_cffi_session(self, monkeypatch: pytest.MonkeyPatch):
        import sys
        import types

        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.setenv("INVESTMENT_FIRM_MARKET_VERIFY_SSL", "false")

        created: List[Dict[str, Any]] = []

        class FakeSession:
            def __init__(self, **kwargs: Any) -> None:
                created.append(kwargs)

        fake_requests = types.ModuleType("curl_cffi.requests")
        fake_requests.Session = FakeSession  # type: ignore[attr-defined]
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_curl_cffi.requests = fake_requests  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl_cffi)
        monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_requests)

        session = market_data._build_yfinance_session()

        assert isinstance(session, FakeSession)
        assert created == [{"impersonate": "chrome", "verify": False}]

    def test_ca_bundle_builds_session_with_bundle_path(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import sys
        import types

        import investment_firm.interfaces.web.market_data as market_data

        monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/corp-ca.pem")
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        created: List[Dict[str, Any]] = []

        class FakeSession:
            def __init__(self, **kwargs: Any) -> None:
                created.append(kwargs)

        fake_requests = types.ModuleType("curl_cffi.requests")
        fake_requests.Session = FakeSession  # type: ignore[attr-defined]
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_curl_cffi.requests = fake_requests  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl_cffi)
        monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_requests)

        session = market_data._build_yfinance_session()

        assert isinstance(session, FakeSession)
        assert created == [{"impersonate": "chrome", "verify": "/etc/corp-ca.pem"}]


class TestChartsPanelStatic:
    def test_index_contains_charts_panel(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get("/")

        assert resp.status_code == 200
        html = resp.text
        assert 'id="charts-panel"' in html
        assert 'id="chart-form"' in html
        assert "Research only" in html
        assert "/static/vendor/lightweight-charts.standalone.production.js" in html
        assert "/static/charts.js" in html

    def test_charts_js_is_served_and_xss_safe(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get("/static/charts.js")

        assert resp.status_code == 200
        # No DOM sink usage — a doc comment may mention the word, so match usage.
        assert ".innerHTML" not in resp.text
        assert "insertAdjacentHTML" not in resp.text

    def test_vendored_chart_library_is_served(self, market_client):
        client, _calls, _cache_path = market_client

        resp = client.get("/static/vendor/lightweight-charts.standalone.production.js")

        assert resp.status_code == 200
        assert "LightweightCharts" in resp.text


class TestPriceHistoryServiceValidation:
    def test_rejects_invalid_service_ticker(self, tmp_path: Path):
        with pytest.raises(MarketDataValidationError):
            get_price_history(
                ticker="AAPL;DROP",
                period="5d",
                interval="1d",
                cache_path=tmp_path / "market_data.sqlite",
            )

    def test_rejects_invalid_service_period(self, tmp_path: Path):
        with pytest.raises(MarketDataValidationError):
            get_price_history(
                ticker="AAPL",
                period="13d",
                interval="1d",
                cache_path=tmp_path / "market_data.sqlite",
            )

    def test_rejects_invalid_service_interval(self, tmp_path: Path):
        with pytest.raises(MarketDataValidationError):
            get_price_history(
                ticker="AAPL",
                period="5d",
                interval="1m",
                cache_path=tmp_path / "market_data.sqlite",
            )

    def test_rejects_unbounded_service_ttl(self, tmp_path: Path):
        with pytest.raises(MarketDataValidationError):
            get_price_history(
                ticker="AAPL",
                period="5d",
                interval="1d",
                ttl_seconds=86_401,
                cache_path=tmp_path / "market_data.sqlite",
            )
