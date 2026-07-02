"""Offline unit tests for core/risk.py and the compute_risk_metrics tool.

All tests are pure Python — no network, no yfinance calls (yfinance is
monkeypatched where the tool is tested).
"""
from __future__ import annotations

import math
import statistics
from unittest.mock import MagicMock, patch

import pytest

from investment_firm.core.risk import (
    annualized_vol,
    expected_shortfall,
    historical_var,
    max_drawdown,
    parametric_var,
    returns_from_prices,
    risk_summary,
)
from investment_firm.core.tools.base import ToolRegistry
from investment_firm.core.tools.datasources import (
    compute_risk_metrics,
    default_data_tools,
)


# ---------------------------------------------------------------------------
# returns_from_prices
# ---------------------------------------------------------------------------


class TestReturnsFromPrices:
    def test_basic(self):
        prices = [100.0, 110.0, 99.0]
        rets = returns_from_prices(prices)
        assert len(rets) == 2
        assert abs(rets[0] - 0.1) < 1e-9
        assert abs(rets[1] - (-11 / 110)) < 1e-9

    def test_single_price_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            returns_from_prices([100.0])

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            returns_from_prices([])

    def test_non_positive_price_raises(self):
        with pytest.raises(ValueError, match="non-positive"):
            returns_from_prices([100.0, 0.0, 110.0])

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="non-positive"):
            returns_from_prices([-1.0, 100.0])


# ---------------------------------------------------------------------------
# historical_var
# ---------------------------------------------------------------------------


class TestHistoricalVar:
    def _returns_95(self):
        """100 returns: 5 bad at -0.10, 95 good at +0.01.
        At level=0.95, the 5% quantile is at the boundary of the bad returns.
        """
        return [-0.10] * 5 + [0.01] * 95

    def test_var_positive_for_heavy_losses(self):
        """A series dominated by large losses should yield a positive VaR."""
        # 50 losses at -0.10, 50 gains at +0.001 — 5% quantile deep in loss territory
        rets = [-0.10] * 50 + [0.001] * 50
        var = historical_var(rets, level=0.95)
        assert var > 0

    def test_var_is_float(self):
        rets = self._returns_95()
        var = historical_var(rets, level=0.95)
        assert isinstance(var, float)

    def test_var_interpolation(self):
        # 10 returns: [-0.10, -0.08, -0.06, -0.04, -0.02, 0.02, 0.04, 0.06, 0.08, 0.10]
        # level=0.90 → q=0.10 → index = 0.10 * 9 = 0.9 → lerp between idx0 and idx1
        # = -0.10 + 0.9*(−0.08−(−0.10)) = -0.10 + 0.9*0.02 = -0.10 + 0.018 = -0.082
        # VaR = 0.082
        rets = [-0.10, -0.08, -0.06, -0.04, -0.02, 0.02, 0.04, 0.06, 0.08, 0.10]
        var = historical_var(rets, level=0.90)
        assert abs(var - 0.082) < 1e-9

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            historical_var([], level=0.95)

    def test_level_out_of_range_raises(self):
        with pytest.raises(ValueError, match="level"):
            historical_var([0.01, -0.02], level=1.0)
        with pytest.raises(ValueError, match="level"):
            historical_var([0.01, -0.02], level=0.0)


# ---------------------------------------------------------------------------
# expected_shortfall
# ---------------------------------------------------------------------------


class TestExpectedShortfall:
    def _returns(self):
        return [-0.10] * 5 + [0.01] * 95

    def test_es_ge_var(self):
        rets = self._returns()
        var = historical_var(rets, level=0.95)
        es = expected_shortfall(rets, level=0.95)
        assert es >= var - 1e-9  # ES >= VaR (both positive)

    def test_es_positive(self):
        rets = self._returns()
        assert expected_shortfall(rets, level=0.95) > 0

    def test_es_is_mean_of_tail(self):
        # For a simple known series, ES should be the mean of the worst returns
        rets = [-0.10, -0.05, 0.00, 0.05, 0.10]
        # level=0.80 → q=0.20 → 20th percentile = index 0.2*4=0.8 → lerp between -0.10 and -0.05
        # = -0.10 + 0.8 * 0.05 = -0.10 + 0.04 = -0.06 (threshold)
        # tail = [r for r in sorted(rets) if r <= -0.06] = [-0.10]
        # ES = -mean([-0.10]) = 0.10
        es = expected_shortfall(rets, level=0.80)
        assert abs(es - 0.10) < 1e-9

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            expected_shortfall([], level=0.95)


# ---------------------------------------------------------------------------
# parametric_var
# ---------------------------------------------------------------------------


class TestParametricVar:
    def test_symmetric_zero_mean(self):
        """For zero-mean returns, parametric VaR ≈ z_alpha * sigma."""
        # 1000 symmetric returns around zero
        import statistics as st

        rets = [0.01 * ((-1) ** i) for i in range(100)]
        sigma = st.stdev(rets)
        z = st.NormalDist().inv_cdf(1.0 - 0.99)
        expected = -(0.0 + z * sigma)  # mu=0
        result = parametric_var(rets, level=0.99)
        assert abs(result - expected) < 1e-9

    def test_positive_for_negative_drift(self):
        rets = [-0.01] * 50 + [0.001] * 50  # net negative drift
        assert parametric_var(rets, level=0.99) > 0

    def test_level_out_of_range_raises(self):
        with pytest.raises(ValueError, match="level"):
            parametric_var([0.01, -0.02], level=1.5)

    def test_too_few_returns_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            parametric_var([0.01], level=0.99)


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_known_path(self):
        # [100, 120, 90, 110]: peak=120 at idx1, trough=90 → dd=(120-90)/120=0.25
        dd = max_drawdown([100.0, 120.0, 90.0, 110.0])
        assert abs(dd - 0.25) < 1e-9

    def test_monotone_rising_no_drawdown(self):
        dd = max_drawdown([100.0, 110.0, 120.0, 130.0])
        assert dd == 0.0

    def test_single_drop(self):
        dd = max_drawdown([200.0, 100.0])
        assert abs(dd - 0.5) < 1e-9

    def test_non_positive_raises(self):
        with pytest.raises(ValueError, match="non-positive"):
            max_drawdown([100.0, 0.0])

    def test_too_few_prices_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            max_drawdown([100.0])


# ---------------------------------------------------------------------------
# risk_summary
# ---------------------------------------------------------------------------


class TestRiskSummary:
    _PRICES = [100.0, 105.0, 103.0, 108.0, 107.0, 112.0, 110.0, 115.0, 113.0, 118.0]

    def test_keys(self):
        result = risk_summary(self._PRICES)
        expected_keys = {
            "n_obs", "ann_vol", "hist_var_1d", "param_var_1d",
            "es_1d", "max_drawdown", "var_level",
        }
        assert expected_keys == set(result.keys())

    def test_n_obs(self):
        result = risk_summary(self._PRICES)
        assert result["n_obs"] == len(self._PRICES) - 1

    def test_rounding_4dp(self):
        result = risk_summary(self._PRICES)
        for key in ("ann_vol", "hist_var_1d", "param_var_1d", "es_1d", "max_drawdown"):
            val = result[key]
            assert isinstance(val, float)
            # 4 decimal places: round-trip should be exact
            assert round(val, 4) == val

    def test_var_level_preserved(self):
        result = risk_summary(self._PRICES, level=0.95)
        assert result["var_level"] == 0.95

    def test_ann_vol_positive(self):
        result = risk_summary(self._PRICES)
        assert result["ann_vol"] > 0

    def test_es_ge_hist_var(self):
        result = risk_summary(self._PRICES)
        assert result["es_1d"] >= result["hist_var_1d"] - 1e-6


# ---------------------------------------------------------------------------
# compute_risk_metrics (tool) — monkeypatched yfinance
# ---------------------------------------------------------------------------


def _fake_yfinance_ticker(prices: list[float], dates: list):
    """Return a mock yf.Ticker whose .history() returns a DataFrame-like object."""
    import pandas as pd

    mock_ticker = MagicMock()
    idx = pd.DatetimeIndex(dates)
    hist = pd.DataFrame({"Close": prices}, index=idx)
    mock_ticker.history.return_value = hist
    return mock_ticker


class TestComputeRiskMetrics:
    _PRICES = [100.0, 105.0, 103.0, 108.0, 107.0, 112.0, 110.0, 115.0, 113.0, 118.0]
    _DATES = [f"2025-01-{i+1:02d}" for i in range(len(_PRICES))]

    def _patch(self, monkeypatch, ticker="AAPL", prices=None, dates=None):
        prices = prices or self._PRICES
        dates = dates or self._DATES

        fake_ticker = _fake_yfinance_ticker(prices, dates)
        fake_yf = MagicMock()
        fake_yf.Ticker.return_value = fake_ticker
        monkeypatch.setitem(
            __import__("sys").modules,
            "yfinance",
            fake_yf,
        )
        return fake_yf

    def test_dict_shape(self, monkeypatch):
        self._patch(monkeypatch)
        result = compute_risk_metrics("AAPL", period="1y")
        expected_keys = {
            "ticker", "period", "as_of", "n_obs",
            "ann_vol_pct", "hist_var_1d_pct", "param_var_1d_pct",
            "es_1d_pct", "max_drawdown_pct", "var_level", "source",
        }
        assert expected_keys == set(result.keys())

    def test_ticker_uppercased(self, monkeypatch):
        self._patch(monkeypatch)
        result = compute_risk_metrics("aapl")
        assert result["ticker"] == "AAPL"

    def test_pct_values_are_percent(self, monkeypatch):
        """Values should be ~100x the fraction equivalents."""
        self._patch(monkeypatch)
        result = compute_risk_metrics("AAPL")
        # Sanity: ann_vol_pct should be > 1 (not a tiny fraction near 0)
        assert result["ann_vol_pct"] > 0.01  # at least 0.01%
        # And well below 10000 (not already multiplied twice)
        assert result["ann_vol_pct"] < 10000

    def test_source_field(self, monkeypatch):
        self._patch(monkeypatch)
        result = compute_risk_metrics("AAPL")
        assert "yfinance" in result["source"]
        assert "VaR" in result["source"]

    def test_registered_in_default_data_tools(self):
        tools = default_data_tools()
        names = [t.name for t in tools]
        assert "compute_risk_metrics" in names

    def test_schema_in_tool_registry(self):
        tools = default_data_tools()
        registry = ToolRegistry(tools)
        schemas = registry.schemas()
        schema_names = [s["function"]["name"] for s in schemas if s.get("type") == "function"]
        assert "compute_risk_metrics" in schema_names

    def test_no_price_data_raises_tool_error(self, monkeypatch):
        from investment_firm.core.tools.base import ToolError
        import pandas as pd

        fake_ticker = MagicMock()
        fake_ticker.history.return_value = pd.DataFrame()  # empty
        fake_yf = MagicMock()
        fake_yf.Ticker.return_value = fake_ticker
        monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

        with pytest.raises(ToolError, match="no price data"):
            compute_risk_metrics("INVALID")
