"""Offline tests for /api/portfolio/* (yfinance + LLM mocked — no network, no tokens)."""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import investment_firm  # noqa: E402
from investment_firm.interfaces.web.market_data import (  # noqa: E402
    MarketDataProviderError,
)

from conftest import FakeLLM, openai_text  # noqa: E402
from test_web_runs import _fake_run_committee, _wait_for_done  # noqa: E402

_SAMPLE = (
    Path(__file__).resolve().parents[1] / "docs" / "examples" / "portfolio_sample.csv"
).read_text(encoding="utf-8")

_ADVICE = (
    '{"assessment": "The mix leans on shares for growth over the long term.", '
    '"strengths": ["Spread across three asset types"], '
    '"weaknesses": ["Half the money is in one share fund"], '
    '"ideas": [{"idea": "Compare a monthly rebalance", "why": "It kept risk steadier", '
    '"type": "rebalance"}, {"idea": "Keep an eye on bond yields", "why": "x", '
    '"type": "moonshot"}], "caveats": ["Past results only"]}'
)


def _fake_payload(ticker: str, period: str, interval: str) -> Dict[str, Any]:
    rng = random.Random(sum(map(ord, ticker)))
    ohlc: List[dict] = []
    volume: List[dict] = []
    d, price = date(2025, 1, 2), 100.0 + rng.random() * 50
    while len(ohlc) < 300:
        if d.weekday() < 5:
            price *= 1 + rng.gauss(0.0003, 0.01)
            t = d.isoformat()
            ohlc.append(
                {
                    "time": t,
                    "open": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price,
                }
            )
            volume.append({"time": t, "value": 1_000_000})
        d += timedelta(days=1)
    return {
        "provider": "yfinance",
        "ticker": ticker.upper(),
        "period": period,
        "interval": interval,
        "source": "yfinance (Yahoo Finance)",
        "as_of": ohlc[-1]["time"],
        "ohlc": ohlc,
        "volume": volume,
    }


@pytest.fixture()
def pclient(monkeypatch, tmp_path):
    monkeypatch.setenv("INVESTMENT_FIRM_MARKET_CACHE", str(tmp_path / "md.sqlite"))
    import investment_firm.interfaces.web.market_data as market_data
    import investment_firm.interfaces.web.portfolio as portfolio_mod
    import investment_firm.interfaces.web.runs as runs_mod

    calls: List[tuple] = []
    failing: set = set()

    def fake_fetch(ticker, period, interval):
        calls.append((ticker, period, interval))
        if ticker in failing:
            raise MarketDataProviderError("no price history returned")
        return _fake_payload(ticker, period, interval)

    monkeypatch.setattr(market_data, "fetch_yfinance_price_history", fake_fetch)
    monkeypatch.setattr(runs_mod, "run_committee", _fake_run_committee)
    portfolio_mod._analyses.clear()
    runs_mod._registry.clear()
    from investment_firm.interfaces.web.app import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c, calls, failing


def _analyze(client, **body):
    payload = {"portfolio_text": _SAMPLE, **body}
    return client.post("/api/portfolio/analyze", json=payload)


class TestAnalyze:
    def test_sample_csv_happy_path(self, pclient):
        client, calls, _ = pclient
        resp = _analyze(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["analysis_id"]
        assert data["disclaimer"] == investment_firm.DISCLAIMER
        analysis = data["analysis"]
        assert "sharpe" in analysis["stats"]
        assert data["display"]["max_drawdown_pct"] is not None
        assert set(analysis["rebalance_comparison"]) == {
            "none",
            "monthly",
            "daily",
            "benchmark",
        }
        assert analysis["rebalance_comparison"]["benchmark"] is not None
        assert data["report_url"] == f"/api/portfolio/{data['analysis_id']}/report.html"
        try:
            import pandas  # noqa: F401
            import stockstats  # noqa: F401

            assert len(analysis["strategy_overlays"]) == 4
        except ImportError:
            assert any("Strategy" in w for w in analysis["warnings"])
        # short horizon default → 1y daily bars; benchmark fetched once
        assert {c[1] for c in calls} == {"1y"}
        assert sorted(c[0] for c in calls) == ["GLD", "SPY", "TLT"]

    def test_long_horizon_auto_period_is_max(self, pclient):
        client, calls, _ = pclient
        assert _analyze(client, horizon="long", strategies=[]).status_code == 200
        assert {c[1] for c in calls} == {"max"}
        assert {c[2] for c in calls} == {"1d"}

    def test_explicit_period_overrides_horizon(self, pclient):
        client, calls, _ = pclient
        resp = _analyze(client, horizon="long", period="2y", strategies=[])
        assert resp.status_code == 200
        assert resp.json()["analysis"]["params"]["period"] == "2y"
        assert {c[1] for c in calls} == {"2y"}

    @pytest.mark.parametrize(
        "text",
        [
            "ticker,weight\nAAPL;DROP,1\n",
            "ticker,weight\n" + "".join(f"T{i},1\n" for i in range(51)),
            "ticker,weight\nSPY,-1\n",
        ],
    )
    def test_bad_portfolio_400(self, pclient, text):
        client, calls, _ = pclient
        resp = client.post("/api/portfolio/analyze", json={"portfolio_text": text})
        assert resp.status_code == 400
        assert calls == []

    def test_unknown_strategy_400(self, pclient):
        client, calls, _ = pclient
        resp = _analyze(client, strategies=["moon_phase"])
        assert resp.status_code == 400
        assert calls == []

    def test_invalid_rebalance_422(self, pclient):
        client, _, _ = pclient
        assert _analyze(client, rebalance="weekly").status_code == 422

    def test_position_provider_failure_502(self, pclient):
        client, _, failing = pclient
        failing.add("TLT")
        resp = _analyze(client, strategies=[])
        assert resp.status_code == 502
        assert "TLT" in resp.json()["detail"]

    def test_benchmark_failure_is_a_warning(self, pclient):
        client, _, failing = pclient
        failing.add("QQQ")
        resp = _analyze(client, benchmark="QQQ", strategies=[])
        assert resp.status_code == 200
        analysis = resp.json()["analysis"]
        assert any("QQQ" in w for w in analysis["warnings"])
        assert analysis["stats"]["beta"] is None


class TestStoredAnalysis:
    def test_get_and_404(self, pclient):
        client, _, _ = pclient
        aid = _analyze(client, strategies=[]).json()["analysis_id"]
        got = client.get(f"/api/portfolio/{aid}")
        assert got.status_code == 200
        assert got.json()["suggestion"] is None
        assert client.get("/api/portfolio/nope").status_code == 404

    def test_report_download(self, pclient):
        client, _, _ = pclient
        aid = _analyze(client).json()["analysis_id"]
        resp = client.get(f"/api/portfolio/{aid}/report.html")
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert f"portfolio-report-{aid}" in resp.headers["content-disposition"]
        text = resp.text
        for needle in (
            "Portfolio Analytics Report",
            "Key numbers in plain words",
            "<svg",
            "Strategy backtests",
            "How the numbers are calculated",
            investment_firm.DISCLAIMER,
        ):
            assert needle in text
        assert "<script" not in text
        assert "Suggestions" not in text
        assert client.get("/api/portfolio/nope/report.html").status_code == 404


class TestSuggest:
    def _setup(self, pclient, monkeypatch, responses):
        client, _, _ = pclient
        aid = _analyze(client, horizon="long", strategies=[]).json()["analysis_id"]
        llm = FakeLLM(responses)
        monkeypatch.setattr("investment_firm.llm.client.chat", llm)
        return client, aid, llm

    def test_ok_suggestion_parsed_and_stored(self, pclient, monkeypatch):
        client, aid, llm = self._setup(pclient, monkeypatch, [openai_text(_ADVICE)])
        resp = client.post(f"/api/portfolio/{aid}/suggest", json={})
        assert resp.status_code == 200
        data = resp.json()
        sug = data["suggestion"]
        assert sug["status"] == "ok"
        assert [i["type"] for i in sug["ideas"]] == ["rebalance", "watch"]
        assert data["suggestion_cost"]["total_tokens"] > 0
        assert data["disclaimer"] == investment_firm.DISCLAIMER
        system, user = llm.calls[0][1][0]["content"], llm.calls[0][1][1]["content"]
        assert "never instruct" in system
        assert "Investment horizon: Long term" in user
        assert "no committee run selected" in user
        assert llm.calls[0][2]["max_tokens"] == 1500
        assert len(user) < 12_000  # digest never carries full series
        report = client.get(f"/api/portfolio/{aid}/report.html").text
        assert "Suggestions" in report and "Compare a monthly rebalance" in report
        assert (
            client.get(f"/api/portfolio/{aid}").json()["suggestion"]["status"] == "ok"
        )

    def test_prose_is_an_explicit_error(self, pclient, monkeypatch):
        client, aid, _ = self._setup(
            pclient, monkeypatch, [openai_text("I think you should diversify.")]
        )
        sug = client.post(f"/api/portfolio/{aid}/suggest", json={}).json()["suggestion"]
        assert sug["status"] == "error"
        assert "no parseable JSON" in sug["error"]
        assert "ideas" not in sug
        report = client.get(f"/api/portfolio/{aid}/report.html").text
        assert "did not return a usable answer" in report

    def test_api_error_is_explicit(self, pclient, monkeypatch):
        client, aid, _ = self._setup(
            pclient, monkeypatch, [{"error": {"message": "boom"}}]
        )
        sug = client.post(f"/api/portfolio/{aid}/suggest", json={}).json()["suggestion"]
        assert sug["status"] == "error" and "boom" in sug["error"]

    def test_committee_run_used_as_market_context(self, pclient, monkeypatch):
        client, aid, llm = self._setup(pclient, monkeypatch, [openai_text(_ADVICE)])
        run_id = client.post("/api/runs", json={"question": "SPY?"}).json()["run_id"]
        _wait_for_done(client, run_id)
        resp = client.post(f"/api/portfolio/{aid}/suggest", json={"run_id": run_id})
        assert resp.status_code == 200
        assert "RECOMMENDATION" in llm.calls[0][1][1]["content"]

    def test_unknown_and_unfinished_runs(self, pclient, monkeypatch):
        client, aid, llm = self._setup(pclient, monkeypatch, [])
        resp = client.post(f"/api/portfolio/{aid}/suggest", json={"run_id": "nope"})
        assert resp.status_code == 404
        import investment_firm.interfaces.web.runs as runs_mod

        with runs_mod._lock:
            runs_mod._registry["busy"] = {"status": "error", "memo": None}
        resp = client.post(f"/api/portfolio/{aid}/suggest", json={"run_id": "busy"})
        assert resp.status_code == 409
        llm.assert_call_count(0)

    def test_unknown_analysis_404(self, pclient):
        client, _, _ = pclient
        assert client.post("/api/portfolio/nope/suggest", json={}).status_code == 404


class TestPortfolioStatic:
    def test_portfolio_js_is_served_and_xss_safe(self, pclient):
        client, _, _ = pclient
        resp = client.get("/static/portfolio.js")
        assert resp.status_code == 200
        assert ".innerHTML" not in resp.text
        assert "insertAdjacentHTML" not in resp.text
        assert "spends tokens" in resp.text

    def test_index_has_portfolio_controls_in_order(self, pclient):
        client, _, _ = pclient
        html = client.get("/").text
        for needle in (
            'id="portfolio-file"',
            'id="btn-portfolio"',
            'id="portfolio-panel"',
            "/static/portfolio.js",
        ):
            assert needle in html
        assert html.index("/static/app.js") < html.index("/static/portfolio.js")
        assert html.count('name="portfolio-strategy"') == 4
