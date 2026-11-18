"""Offline tests for core/tools/forecast_tools.py (fake timesfm + fake yfinance)."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import types
from unittest.mock import MagicMock

import pytest

from investment_firm.core.tools import ToolRegistry, forecast_tools as ft
from investment_firm.core.tools.base import ToolError

pd = pytest.importorskip("pandas")

_N = 300


def _hist(n: int = _N):
    closes = [100.0 * math.exp(0.0005 * i + 0.01 * math.sin(i / 3.0)) for i in range(n)]
    idx = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame({"Close": closes}, index=idx)


def _patch_yf(monkeypatch, hist=None):
    ticker = MagicMock()
    ticker.history.return_value = _hist() if hist is None else hist
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    return fake_yf


class _FakeModel:
    """Mimics TimesFM_2p5_200M_torch: forecast() -> (point, quantiles[1,h,10])."""

    compiled = None
    calls: list = []

    def compile(self, config):
        _FakeModel.compiled = config

    def forecast(self, *, horizon, inputs):
        _FakeModel.calls.append((horizon, [len(x) for x in inputs]))
        last = float(inputs[0][-1])
        rows = []
        for t in range(1, horizon + 1):
            # mean + deciles q10..q90, monotone in the quantile index
            rows.append(
                [last] + [last * (1 + (d - 5) * 0.01 * t) for d in range(1, 10)]
            )
        return [[last] * horizon], [rows]


def _install_fake_timesfm(monkeypatch, *, loader_fails=False, bad_shape=False):
    mod = types.ModuleType("timesfm")

    class ForecastConfig:
        def __init__(self, **kw):
            self.kw = kw

    class TimesFM_2p5_200M_torch:
        @classmethod
        def from_pretrained(cls, repo):
            if loader_fails:
                raise RuntimeError("no network")
            m = _FakeModel()
            m.repo = repo
            if bad_shape:
                m.forecast = lambda *, horizon, inputs: (
                    [[1.0]],
                    [[[1.0, 2.0]] * horizon],
                )
            return m

    mod.ForecastConfig = ForecastConfig
    mod.TimesFM_2p5_200M_torch = TimesFM_2p5_200M_torch
    monkeypatch.setitem(sys.modules, "timesfm", mod)
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    monkeypatch.setattr(ft, "timesfm_available", lambda: True)
    ft.reset_model_cache()
    _FakeModel.calls = []


@pytest.fixture(autouse=True)
def _reset_cache():
    ft.reset_model_cache()
    yield
    ft.reset_model_cache()


class TestAvailabilityGate:
    def test_no_tools_when_timesfm_missing(self, monkeypatch):
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        assert ft.default_forecast_tools() == []

    def test_tool_advertised_when_available(self, monkeypatch):
        monkeypatch.setattr(ft, "timesfm_available", lambda: True)
        names = [t.name for t in ft.default_forecast_tools()]
        assert names == ["forecast_quantiles"]

    def test_find_spec_based_detection(self, monkeypatch):
        real = importlib.util.find_spec

        def fake(name, *a, **k):
            if name in {"timesfm", "torch"}:
                return None
            return real(name, *a, **k)

        monkeypatch.setattr(importlib.util, "find_spec", fake)
        assert ft.timesfm_available() is False


class TestBaselineWithoutModel:
    def test_baseline_payload(self, monkeypatch):
        _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        out = ft.forecast_quantiles("aapl", horizon_days=5)
        assert out["ticker"] == "AAPL"
        assert out["is_model"] is False
        assert out["source"] == "random-walk baseline"
        assert out["model_repo"] is None
        assert len(out["q50"]) == 5 and len(out["dates"]) == 5
        assert out["q50"] == out["baseline_q50"]
        assert out["price_source"].startswith("yfinance")
        assert "caveat" in out
        json.dumps(out)

    def test_horizon_clamped(self, monkeypatch):
        _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        with pytest.raises(ToolError):
            ft.forecast_quantiles("AAPL", horizon_days=0)
        with pytest.raises(ToolError):
            ft.forecast_quantiles("AAPL", horizon_days=61)

    def test_empty_history_is_tool_error(self, monkeypatch):
        _patch_yf(monkeypatch, hist=pd.DataFrame())
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        with pytest.raises(ToolError, match="no price data"):
            ft.forecast_quantiles("ZZZZ")

    def test_too_short_history_is_tool_error(self, monkeypatch):
        _patch_yf(monkeypatch, hist=_hist(10))
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        with pytest.raises(ToolError):
            ft.forecast_quantiles("AAPL")

    def test_interval_fetches_matching_bars_and_default_period(self, monkeypatch):
        fake_yf = _patch_yf(monkeypatch)
        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        out = ft.forecast_quantiles("SPY", horizon_days=4, interval="1mo")
        fake_yf.Ticker.return_value.history.assert_called_with(
            period="max", interval="1mo"
        )
        assert out["interval"] == "1mo"
        assert out["period"] == "max"
        assert len(out["dates"]) == 4

    def test_bad_interval_is_tool_error(self, monkeypatch):
        _patch_yf(monkeypatch)
        with pytest.raises(ToolError, match="interval"):
            ft.forecast_quantiles("SPY", interval="1h")


class TestWithFakeModel:
    def test_model_cone_and_baseline_shipped(self, monkeypatch):
        _patch_yf(monkeypatch)
        _install_fake_timesfm(monkeypatch)
        out = ft.forecast_quantiles("spy", horizon_days=10, period="2y")
        assert out["is_model"] is True
        assert out["source"] == ft.MODEL_SOURCE
        assert out["model_repo"] == ft.DEFAULT_MODEL_REPO
        assert out["period"] == "2y"
        assert "model_error" not in out
        assert len(out["q10"]) == len(out["q50"]) == len(out["q90"]) == 10
        # q10 < q50 < q90 at the horizon end and the baseline is still present
        assert out["q10"][-1] < out["q50"][-1] < out["q90"][-1]
        assert len(out["baseline_q50"]) == 10
        assert out["baseline_summary"]["end_q50_pct"] == 0.0
        # the compile config asks for the quantile head and crossing fix
        assert _FakeModel.compiled.kw["use_continuous_quantile_head"] is True
        assert _FakeModel.compiled.kw["fix_quantile_crossing"] is True
        # context capped at MAX_CONTEXT and horizon passed through
        assert _FakeModel.calls == [(10, [min(_N, ft.MAX_CONTEXT)])]

    def test_model_env_overrides_read_lazily(self, monkeypatch):
        _patch_yf(monkeypatch)
        _install_fake_timesfm(monkeypatch)
        monkeypatch.setenv("IFA_FORECAST_MODEL", "org/custom-weights")
        out = ft.forecast_quantiles("SPY", horizon_days=3)
        assert out["model_repo"] == "org/custom-weights"

    def test_model_cached_once(self, monkeypatch):
        _patch_yf(monkeypatch)
        _install_fake_timesfm(monkeypatch)
        ft.forecast_quantiles("SPY", horizon_days=3)
        ft.forecast_quantiles("SPY", horizon_days=4)
        assert ft._load_model.cache_info().hits == 1

    def test_loader_failure_degrades_to_baseline(self, monkeypatch):
        _patch_yf(monkeypatch)
        _install_fake_timesfm(monkeypatch, loader_fails=True)
        out = ft.forecast_quantiles("SPY", horizon_days=5)
        assert out["is_model"] is False
        assert "no network" in out["model_error"]
        assert out["source"] == "random-walk baseline"

    def test_bad_output_shape_degrades_to_baseline(self, monkeypatch):
        _patch_yf(monkeypatch)
        _install_fake_timesfm(monkeypatch, bad_shape=True)
        out = ft.forecast_quantiles("SPY", horizon_days=5)
        assert out["is_model"] is False
        assert "shape" in out["model_error"]

    def test_registry_dispatch_json(self, monkeypatch):
        _patch_yf(monkeypatch)
        _install_fake_timesfm(monkeypatch)
        reg = ToolRegistry(ft.default_forecast_tools())
        out = json.loads(
            reg.dispatch("forecast_quantiles", '{"ticker": "msft", "horizon_days": 7}')
        )
        assert out["ticker"] == "MSFT"
        assert out["horizon_days"] == 7


class TestWiring:
    def test_consultant_registry_gains_forecast_tool_when_available(self, monkeypatch):
        from investment_firm.core import consultant

        monkeypatch.setattr(ft, "timesfm_available", lambda: True)
        names = set(consultant.consultant_registry().names())
        assert "forecast_quantiles" in names
        assert set(consultant.CONSULTANT_TOOL_NAMES) <= names

    def test_consultant_registry_unchanged_without_timesfm(self, monkeypatch):
        from investment_firm.core import consultant

        monkeypatch.setattr(ft, "timesfm_available", lambda: False)
        names = set(consultant.consultant_registry().names())
        assert names == set(consultant.CONSULTANT_TOOL_NAMES)

    def test_orchestrator_registry_includes_forecast_tool(self, monkeypatch):
        from investment_firm.core import orchestrator

        monkeypatch.setattr(ft, "timesfm_available", lambda: True)
        assert "forecast_quantiles" in orchestrator._full_registry().names()


class TestShapeAdapter:
    def test_extract_quantiles_indices(self):
        rows = [[[float(c) for c in range(10)]] * 3]
        q = ft._extract_quantiles(rows, 3)
        assert q["q10"] == [1.0, 1.0, 1.0]
        assert q["q25"] == [2.5, 2.5, 2.5]
        assert q["q50"] == [5.0, 5.0, 5.0]
        assert q["q75"] == [7.5, 7.5, 7.5]
        assert q["q90"] == [9.0, 9.0, 9.0]

    def test_extract_quantiles_short_horizon_raises(self):
        with pytest.raises(ToolError):
            ft._extract_quantiles([[[0.0] * 10]], 2)
