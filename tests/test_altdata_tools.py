"""Offline tests for the alt-data vendor tools (FRED, Polymarket, StockTwits).

All HTTP is mocked via monkeypatching ``requests.get`` — no network, no tokens.
"""

from __future__ import annotations

import json

import pytest

from investment_firm.core.tools import ToolRegistry, default_data_tools
from investment_firm.core.tools.base import ToolError
from investment_firm.core.tools import datasources as ds


class _Resp:
    def __init__(self, status=200, text="", json_data=None):
        self.status_code = status
        self.text = text
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def _patch_get(monkeypatch, handler):
    import requests

    monkeypatch.setattr(requests, "get", handler)


class TestFred:
    def test_returns_latest_non_missing_value(self, monkeypatch):
        csv = "DATE,DGS10\n2026-06-01,4.20\n2026-06-02,.\n2026-06-03,4.35\n"
        _patch_get(monkeypatch, lambda url, **kw: _Resp(text=csv))
        out = ds.get_fred_series("dgs10")
        assert out["series"] == "DGS10"
        assert out["value"] == 4.35
        assert out["observation_date"] == "2026-06-03"
        assert "FRED" in out["source"]
        assert out["as_of"]

    def test_all_missing_raises(self, monkeypatch):
        csv = "DATE,X\n2026-06-01,.\n2026-06-02,.\n"
        _patch_get(monkeypatch, lambda url, **kw: _Resp(text=csv))
        with pytest.raises(ToolError):
            ds.get_fred_series("X")

    def test_http_error_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(status=500, text="boom"))
        with pytest.raises(ToolError):
            ds.get_fred_series("DGS10")


class TestPolymarket:
    def test_parses_json_encoded_outcomes(self, monkeypatch):
        market = {
            "question": "Will the ECB cut rates in 2026?",
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["0.62", "0.38"]),
        }
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data=[market]))
        out = ds.get_prediction_market_odds("ECB rate cut", limit=3)
        assert out["query"] == "ECB rate cut"
        assert out["markets"][0]["implied_odds_pct"] == {"Yes": 62.0, "No": 38.0}
        assert "Polymarket" in out["source"]
        assert out["as_of"]

    def test_empty_result_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data=[]))
        with pytest.raises(ToolError):
            ds.get_prediction_market_odds("nothing matches")

    def test_read_only_no_trade_keys(self, monkeypatch):
        market = {"question": "Q", "outcomes": ["Yes"], "outcomePrices": [0.5]}
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data=[market]))
        out = ds.get_prediction_market_odds("q")
        # Decision-support only: the payload never exposes order/wallet fields.
        blob = json.dumps(out).lower()
        for banned in ("order", "wallet", "private_key", "signature"):
            assert banned not in blob


class TestStockTwits:
    def _stream(self, bull, bear, neutral):
        msgs = []
        for _ in range(bull):
            msgs.append({"entities": {"sentiment": {"basic": "Bullish"}}})
        for _ in range(bear):
            msgs.append({"entities": {"sentiment": {"basic": "Bearish"}}})
        for _ in range(neutral):
            msgs.append({"entities": {"sentiment": None}})
        return {"messages": msgs}

    def test_counts_and_net_sentiment(self, monkeypatch):
        _patch_get(
            monkeypatch, lambda url, **kw: _Resp(json_data=self._stream(5, 1, 24))
        )
        out = ds.get_stocktwits_sentiment("aapl")
        assert out["symbol"] == "AAPL"
        assert out["bullish"] == 5
        assert out["bearish"] == 1
        assert out["unlabeled"] == 24
        assert out["sample_size"] == 30
        assert out["net_sentiment"] == "bullish"
        assert "StockTwits" in out["source"]

    def test_no_messages_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data={"messages": []}))
        with pytest.raises(ToolError):
            ds.get_stocktwits_sentiment("AAPL")

    def test_crypto_404_retries_with_x_suffix(self, monkeypatch):
        """BTC → 404, BTC.X → 200; payload reports the resolved symbol."""
        seen = []

        def handler(url, **kw):
            seen.append(url)
            if "BTC.X.json" in url:
                return _Resp(json_data=self._stream(3, 1, 0))
            return _Resp(status=404)

        _patch_get(monkeypatch, handler)
        out = ds.get_stocktwits_sentiment("btc")
        assert out["symbol"] == "BTC.X"
        assert out["bullish"] == 3
        assert len(seen) == 2

    def test_crypto_404_both_raises_structured_message(self, monkeypatch):
        """404 on both plain and .X symbol → explicit unsupported-asset ToolError."""
        _patch_get(monkeypatch, lambda url, **kw: _Resp(status=404))
        with pytest.raises(ToolError) as exc:
            ds.get_stocktwits_sentiment("BTC")
        msg = str(exc.value)
        assert "no stream for 'BTC'" in msg
        assert "BTC.X" in msg
        assert "unsupported" in msg

    def test_x_suffix_symbol_404_no_double_retry(self, monkeypatch):
        """Already-suffixed symbols fail with a plain HTTP error, no retry loop."""
        seen = []

        def handler(url, **kw):
            seen.append(url)
            return _Resp(status=404)

        _patch_get(monkeypatch, handler)
        with pytest.raises(ToolError):
            ds.get_stocktwits_sentiment("BTC.X")
        assert len(seen) == 1


class TestAlphaVantage:
    _OVERVIEW = {
        "Symbol": "AAPL",
        "Name": "Apple Inc",
        "Sector": "TECHNOLOGY",
        "PERatio": "31.5",
        "PEGRatio": "2.1",
        "PriceToBookRatio": "45.2",
        "DividendYield": "0.0045",
        "ProfitMargin": "0.253",
        "EPS": "6.42",
        "MarketCapitalization": "3100000000000",
        "52WeekHigh": "260.1",
        "52WeekLow": "164.0",
        "LatestQuarter": "2026-03-31",
    }

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
        with pytest.raises(ToolError):
            ds.get_av_overview("AAPL")

    def test_parses_fundamentals(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "demo")
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data=self._OVERVIEW))
        out = ds.get_av_overview("aapl")
        assert out["symbol"] == "AAPL"
        assert out["pe_ratio"] == 31.5
        assert out["dividend_yield_pct"] == 0.45
        assert out["profit_margin_pct"] == 25.3
        assert out["market_cap"] == 3100000000000.0
        assert "Alpha Vantage" in out["source"]
        assert out["as_of"] == "2026-03-31"

    def test_rate_limit_note_raises(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "demo")
        note = {"Note": "call frequency limit reached"}
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data=note))
        with pytest.raises(ToolError):
            ds.get_av_overview("AAPL")

    def test_unknown_symbol_empty_raises(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "demo")
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data={}))
        with pytest.raises(ToolError):
            ds.get_av_overview("ZZZZ")


class TestReddit:
    def _reset_token(self):
        ds._REDDIT_TOKEN["value"] = None
        ds._REDDIT_TOKEN["expires"] = 0.0

    def _listing(self, titles):
        children = [{"data": {"title": t, "score": i}} for i, t in enumerate(titles)]
        return {"data": {"children": children}}

    def _creds(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
        monkeypatch.setenv("REDDIT_USER_AGENT", "ifa-test/0.1")

    def test_missing_creds_raises(self, monkeypatch):
        self._reset_token()
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        with pytest.raises(ToolError):
            ds.get_reddit_sentiment("AAPL")

    def test_token_and_sentiment(self, monkeypatch):
        self._reset_token()
        self._creds(monkeypatch)
        import requests

        monkeypatch.setattr(
            requests,
            "post",
            lambda url, **kw: _Resp(
                json_data={"access_token": "tok123", "expires_in": 3600}
            ),
        )
        titles = [
            "AAPL calls to the moon",
            "AAPL puts, this will crash",
            "AAPL earnings soon",
        ]
        monkeypatch.setattr(
            requests, "get", lambda url, **kw: _Resp(json_data=self._listing(titles))
        )
        out = ds.get_reddit_sentiment("AAPL", subreddit="r/stocks", limit=10)
        assert out["subreddit"] == "stocks"
        assert out["sample_size"] == 3
        assert out["bullish_titles"] == 1
        assert out["bearish_titles"] == 1
        assert out["net_sentiment"] == "neutral"
        assert "Reddit" in out["source"]

    def test_auth_failure_raises(self, monkeypatch):
        self._reset_token()
        self._creds(monkeypatch)
        import requests

        monkeypatch.setattr(requests, "post", lambda url, **kw: _Resp(status=401))
        with pytest.raises(ToolError):
            ds.get_reddit_sentiment("AAPL")


class TestEdgar:
    _FACTS = {
        "units": {
            "USD": [
                {"val": 383285000000, "fy": 2024, "fp": "FY"},
                {"val": 391035000000, "fy": 2025, "fp": "FY"},
            ]
        }
    }

    def test_returns_latest_value_with_provenance(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(json_data=self._FACTS))
        out = ds.get_company_filing("320193", concept="Revenues")
        assert out["cik"] == "0000320193"
        assert out["concept"] == "Revenues"
        assert out["value"] == 391035000000
        assert out["fiscal_period"] == "2025 FY"
        assert "EDGAR" in out["source"]
        assert out["as_of"]

    def test_uses_sec_user_agent_env(self, monkeypatch):
        captured = {}

        def handler(url, **kw):
            captured["headers"] = kw.get("headers", {})
            return _Resp(json_data=self._FACTS)

        monkeypatch.setenv(
            "SEC_USER_AGENT", "investment-firm-agents contact@example.com"
        )
        _patch_get(monkeypatch, handler)
        ds.get_company_filing("320193")
        assert (
            captured["headers"]["User-Agent"]
            == "investment-firm-agents contact@example.com"
        )

    def test_falls_back_when_env_unset(self, monkeypatch):
        captured = {}

        def handler(url, **kw):
            captured["headers"] = kw.get("headers", {})
            return _Resp(json_data=self._FACTS)

        monkeypatch.delenv("SEC_USER_AGENT", raising=False)
        _patch_get(monkeypatch, handler)
        ds.get_company_filing("320193")
        assert "investment-firm-agents" in captured["headers"]["User-Agent"]

    def test_http_error_raises(self, monkeypatch):
        _patch_get(monkeypatch, lambda url, **kw: _Resp(status=404, text="nope"))
        with pytest.raises(ToolError):
            ds.get_company_filing("000")


class TestRegistration:
    def test_new_tools_registered(self):
        names = {t.name for t in default_data_tools()}
        assert {
            "get_fred_series",
            "get_prediction_market_odds",
            "get_stocktwits_sentiment",
            "get_av_overview",
            "get_reddit_sentiment",
        } <= names

    def test_dispatch_returns_provenance(self, monkeypatch):
        csv = "DATE,FEDFUNDS\n2026-06-01,4.75\n"
        _patch_get(monkeypatch, lambda url, **kw: _Resp(text=csv))
        registry = ToolRegistry(default_data_tools())
        payload = json.loads(
            registry.dispatch("get_fred_series", {"series": "FEDFUNDS"})
        )
        assert payload["value"] == 4.75
        assert "source" in payload and "as_of" in payload
