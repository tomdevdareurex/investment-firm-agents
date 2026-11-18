"""Offline tests for GET /api/market/forecast and the health flag — no network."""

from __future__ import annotations

import math
import sys
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip(
    "fastapi", reason="fastapi not installed (run: pip install -e '.[api]')"
)
pd = pytest.importorskip("pandas")
from fastapi.testclient import TestClient  # noqa: E402

from investment_firm.core.tools import forecast_tools as ft  # noqa: E402
from investment_firm.interfaces.web.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _patch_yf(monkeypatch, n: int = 300):
    closes = [50.0 * math.exp(0.0004 * i + 0.02 * math.sin(i / 5.0)) for i in range(n)]
    hist = pd.DataFrame(
        {"Close": closes}, index=pd.bdate_range("2025-01-02", periods=n)
    )
    ticker = MagicMock()
    ticker.history.return_value = hist
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    return ticker


class TestHealthFlag:
    def test_health_reports_forecast_flag(self, client, monkeypatch):
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        data = client.get("/api/health").json()
        assert data["forecast_available"] is False


class TestForecastRoute:
    def test_baseline_cone_without_model(self, client, monkeypatch):
        _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        resp = client.get("/api/market/forecast", params={"ticker": "aapl"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["available"] is False
        assert data["is_model"] is False
        assert data["horizon_days"] == 20
        assert len(data["q10"]) == len(data["q50"]) == len(data["q90"]) == 20
        assert len(data["dates"]) == 20
        assert "caveat" in data

    def test_horizon_and_period_forwarded(self, client, monkeypatch):
        ticker = _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        resp = client.get(
            "/api/market/forecast",
            params={"ticker": "SPY", "horizon_days": 7, "period": "2y"},
        )
        assert resp.status_code == 200
        assert resp.json()["horizon_days"] == 7
        assert resp.json()["period"] == "2y"
        ticker.history.assert_called_with(period="2y", interval="1d")

    def test_interval_forwarded_with_default_period(self, client, monkeypatch):
        ticker = _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        resp = client.get(
            "/api/market/forecast",
            params={"ticker": "SPY", "horizon_days": 20, "interval": "1wk"},
        )
        assert resp.status_code == 200
        assert resp.json()["interval"] == "1wk"
        ticker.history.assert_called_with(period="10y", interval="1wk")

    def test_bad_interval_is_422(self, client):
        resp = client.get(
            "/api/market/forecast", params={"ticker": "SPY", "interval": "1h"}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad", [0, 61, "abc"])
    def test_bad_horizon_is_422(self, client, bad):
        resp = client.get(
            "/api/market/forecast", params={"ticker": "SPY", "horizon_days": bad}
        )
        assert resp.status_code == 422

    def test_bad_ticker_pattern_is_422(self, client):
        resp = client.get("/api/market/forecast", params={"ticker": "A B;"})
        assert resp.status_code == 422

    def test_bad_period_is_422(self, client):
        resp = client.get(
            "/api/market/forecast", params={"ticker": "SPY", "period": "3mo"}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("method", ["arima", "arima_garch"])
    def test_arima_methods(self, client, monkeypatch, method):
        _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        resp = client.get(
            "/api/market/forecast",
            params={"ticker": "^GSPC", "horizon_days": 15, "method": method},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == method
        assert data["is_model"] is True
        assert data["model_repo"] is None
        assert data["source"].startswith("ARIMA(1,1,1)")
        assert len(data["q50"]) == len(data["q25"]) == len(data["dates"]) == 15
        assert len(data["baseline_q50"]) == 15
        assert len(data["step_vol_pct"]) == 15
        assert {"phi", "theta", "mu_pct"} <= set(data["model_params"])
        assert {"loglik", "aic", "bic", "n_obs", "converged", "warnings"} <= set(
            data["fit"]
        )
        if method == "arima_garch":
            assert {"omega", "alpha", "beta", "persistence"} <= set(
                data["model_params"]
            )
            assert data["source"].endswith("GARCH(1,1) on log price")
        else:
            assert "sigma_pct" in data["model_params"]

    def test_default_method_reports_baseline(self, client, monkeypatch):
        _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        data = client.get("/api/market/forecast", params={"ticker": "SPY"}).json()
        assert data["method"] == "baseline"
        assert "model_params" not in data

    def test_bad_method_is_422(self, client):
        resp = client.get(
            "/api/market/forecast", params={"ticker": "SPY", "method": "lstm"}
        )
        assert resp.status_code == 422

    def test_no_prices_is_502(self, client, monkeypatch):
        ticker = _patch_yf(monkeypatch)
        ticker.history.return_value = pd.DataFrame()
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        resp = client.get("/api/market/forecast", params={"ticker": "ZZZZ"})
        assert resp.status_code == 502

    def test_too_short_history_is_400(self, client, monkeypatch):
        _patch_yf(monkeypatch, n=5)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        resp = client.get("/api/market/forecast", params={"ticker": "SPY"})
        assert resp.status_code == 400


class TestForecastStaticAssets:
    """forecast.js overlays the chart drawn by charts.js — ordering + XSS hygiene."""

    def test_index_wires_checkbox_and_script_after_charts(self, client):
        html = client.get("/").text
        assert 'id="chart-forecast"' in html
        assert 'id="chart-forecast-info"' in html
        assert 'id="chart-arima"' in html
        assert 'id="chart-garch"' in html
        assert 'id="chart-arima-info"' in html
        assert "/static/forecast.js" in html
        assert html.index("/static/app.js") < html.index("/static/charts.js")
        assert html.index("/static/charts.js") < html.index("/static/forecast.js")

    def test_forecast_js_served_without_innerhtml(self, client):
        resp = client.get("/static/forecast.js")
        assert resp.status_code == 200
        assert ".innerHTML" not in resp.text
        assert "/api/market/forecast" in resp.text
        assert "ifa:chart-rendered" in resp.text
        assert "&method=" in resp.text
        assert "arima_garch" in resp.text

    def test_charts_js_exposes_hooks(self, client):
        js = client.get("/static/charts.js").text
        assert "ifa:chart-rendered" in js
        assert "ifa:chart-destroyed" in js
        assert "window.ifaCharts" in js
