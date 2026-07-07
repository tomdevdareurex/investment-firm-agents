"""Offline tests for the shared technical-indicator engine (no network).

Asserts the chart==agent invariant: ``latest_snapshot`` equals the last point
of the same ``compute`` series that feeds chart overlays.
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from investment_firm.data import indicators


def _ohlcv(rows: int = 60) -> pd.DataFrame:
    """Deterministic synthetic OHLCV frame (no randomness, no network)."""
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    closes = [100.0 + i * 0.5 + (i % 5) for i in range(rows)]
    data = {
        "Date": dates,
        "Open": [c - 0.5 for c in closes],
        "High": [c + 1.0 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes,
        "Volume": [1_000_000 + i * 1000 for i in range(rows)],
    }
    return pd.DataFrame(data)


class TestCatalog:
    def test_catalog_nonempty_and_described(self):
        cat = indicators.available_indicators()
        assert cat, "catalog must not be empty"
        assert all(isinstance(v, str) and v for v in cat.values())

    def test_every_catalog_indicator_computes(self):
        df = _ohlcv(60)
        for name in indicators.available_indicators():
            series = indicators.compute(df, [name])[name]
            assert len(series) == len(df)
            assert any(v is not None for v in series), f"{name} produced no values"


class TestCompute:
    def test_sma_matches_manual_mean(self):
        df = _ohlcv(60)
        series = indicators.compute(df, ["close_50_sma"])["close_50_sma"]
        expected = round(float(df["Close"].iloc[-50:].mean()), 6)
        assert series[-1] == pytest.approx(expected, abs=1e-6)

    def test_multiple_indicators_deduped(self):
        df = _ohlcv(60)
        out = indicators.compute(df, "rsi, macd, rsi")
        assert set(out) == {"rsi", "macd"}

    def test_partial_windows_are_filled_not_gapped(self):
        # stockstats uses min_periods=1, so a 200 SMA on a short frame still
        # returns partial-window values rather than leading None gaps.
        df = _ohlcv(60)
        series = indicators.compute(df, ["close_200_sma"])["close_200_sma"]
        assert all(v is not None for v in series)
        assert series[0] == pytest.approx(float(df["Close"].iloc[0]), abs=1e-6)

    def test_nan_and_inf_map_to_none(self):
        assert indicators._is_missing(float("nan")) is True
        assert indicators._is_missing(float("inf")) is True
        assert indicators._is_missing(None) is True
        assert indicators._is_missing(1.5) is False


class TestSnapshotInvariant:
    def test_snapshot_equals_last_compute_point(self):
        df = _ohlcv(60)
        names = ["close_10_ema", "close_50_sma", "rsi", "macd", "boll_ub", "atr"]
        series = indicators.compute(df, names)
        snap = indicators.latest_snapshot(df, names)
        for name in names:
            assert snap["indicators"][name] == series[name][-1]

    def test_snapshot_as_of_is_last_date(self):
        df = _ohlcv(60)
        snap = indicators.latest_snapshot(df, ["close_50_sma"])
        assert snap["as_of"] == "2026-03-01"  # 2026-01-01 + 59 days


class TestOverlaySeries:
    def test_overlay_points_align_and_drop_gaps(self):
        df = _ohlcv(60)
        times = [d.strftime("%Y-%m-%d") for d in pd.to_datetime(df["Date"])]
        overlays = indicators.overlay_series(df, ["close_50_sma"], times)
        points = overlays["close_50_sma"]
        # stockstats fills partial windows -> one point per row, none dropped.
        assert len(points) == len(df)
        assert points[-1]["time"] == "2026-03-01"
        # Overlay last value matches the snapshot (chart == agent).
        snap = indicators.latest_snapshot(df, ["close_50_sma"])
        assert points[-1]["value"] == snap["indicators"]["close_50_sma"]


class TestValidation:
    def test_unknown_indicator_raises(self):
        df = _ohlcv(10)
        with pytest.raises(indicators.IndicatorError):
            indicators.compute(df, ["not_a_real_indicator"])

    def test_empty_names_raises(self):
        df = _ohlcv(10)
        with pytest.raises(indicators.IndicatorError):
            indicators.compute(df, "")

    def test_empty_frame_raises(self):
        with pytest.raises(indicators.IndicatorError):
            indicators.compute(pd.DataFrame(), ["rsi"])


class TestGetIndicatorsTool:
    """The get_indicators agent tool (yfinance mocked — no network)."""

    def _install_fake_yfinance(self, monkeypatch, df):
        import sys
        import types

        indexed = df.set_index("Date")

        class _Ticker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, period="6mo"):
                return indexed

        monkeypatch.setitem(
            sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker)
        )

    def test_registered_in_default_tools(self):
        from investment_firm.core.tools import default_data_tools

        names = {t.name for t in default_data_tools()}
        assert "get_indicators" in names

    def test_schema_is_valid_function_tool(self):
        from investment_firm.core.tools.datasources import _INDICATORS_TOOL

        schema = _INDICATORS_TOOL.schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "get_indicators"
        assert "ticker" in schema["function"]["parameters"]["properties"]

    def test_dispatch_returns_provenance_tagged_indicators(self, monkeypatch):
        from investment_firm.core.tools import ToolRegistry, default_data_tools

        self._install_fake_yfinance(monkeypatch, _ohlcv(60))
        registry = ToolRegistry(default_data_tools())
        raw = registry.dispatch(
            "get_indicators", {"ticker": "spy", "indicators": "close_50_sma,rsi"}
        )
        payload = json.loads(raw)
        assert payload["ticker"] == "SPY"
        assert payload["source"] == "yfinance (Yahoo Finance) + stockstats"
        assert payload["as_of"] == "2026-03-01"
        assert set(payload["indicators"]) == {"close_50_sma", "rsi"}
        assert payload["indicators"]["close_50_sma"] is not None

    def test_matches_engine_snapshot(self, monkeypatch):
        # The tool must return the same value the shared engine (and chart) computes.
        from investment_firm.core.tools.datasources import get_indicators

        df = _ohlcv(60)
        self._install_fake_yfinance(monkeypatch, df)
        tool_out = get_indicators("SPY", indicators="close_50_sma")
        engine = indicators.latest_snapshot(df, ["close_50_sma"])
        assert (
            tool_out["indicators"]["close_50_sma"]
            == engine["indicators"]["close_50_sma"]
        )

    def test_unknown_indicator_becomes_error_envelope(self, monkeypatch):
        from investment_firm.core.tools import ToolRegistry, default_data_tools

        self._install_fake_yfinance(monkeypatch, _ohlcv(60))
        registry = ToolRegistry(default_data_tools())
        raw = registry.dispatch(
            "get_indicators", {"ticker": "spy", "indicators": "bogus_ind"}
        )
        payload = json.loads(raw)
        assert "error" in payload
        assert "unknown indicator" in payload["error"]
