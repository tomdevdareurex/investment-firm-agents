"""Offline tests for the rule-based strategy backtester (no network).

Covers the pure engine in ``data/backtest.py`` (signal helpers, no-lookahead
equity math, cost model, error paths) and the ``run_strategy_backtest`` tool
wrapper (yfinance mocked), plus its inclusion in the consultant's read-only
tool subset.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from investment_firm.data import backtest, risk
from investment_firm.core.consultant import (
    CONSULTANT_TOOL_NAMES,
    consultant_registry,
)


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
        cat = backtest.available_strategies()
        assert cat == backtest.STRATEGIES
        assert cat is not backtest.STRATEGIES  # copy, not the module dict
        assert all(isinstance(v, str) and v for v in cat.values())

    def test_every_strategy_runs_on_synthetic_frame(self):
        df = _ohlcv(60)
        for name in backtest.STRATEGIES:
            out = backtest.run_strategy(df, name)
            assert out["strategy"] == name
            assert out["n_obs"] == len(df) - 1
            assert 0.0 <= out["time_in_market"] <= 1.0
            assert out["max_drawdown"] >= 0.0  # positive = loss convention


class TestSignalHelpers:
    def test_above_handles_missing_values(self):
        fast = [None, 2.0, 3.0, 1.0]
        slow = [1.0, None, 2.0, 2.0]
        assert backtest._above(fast, slow) == [0, 0, 1, 0]

    def test_threshold_state_enters_and_exits(self):
        trigger = [50.0, 25.0, 40.0, 70.0, 70.5, 20.0]
        n = len(trigger)
        signals = backtest._threshold_state(trigger, [30.0] * n, [70.0] * n)
        # enter below 30, hold through 70 (not strictly above), exit at 70.5
        assert signals == [0, 1, 1, 1, 0, 1]

    def test_unknown_strategy_raises(self):
        with pytest.raises(backtest.BacktestError, match="unknown strategy"):
            backtest.run_strategy(_ohlcv(60), "momo_yolo")

    def test_insufficient_history_raises(self):
        with pytest.raises(backtest.BacktestError, match="insufficient"):
            backtest.run_strategy(_ohlcv(2), "sma_crossover")
        with pytest.raises(backtest.BacktestError, match="insufficient"):
            backtest.run_strategy(None, "sma_crossover")


class TestEquityMath:
    def test_total_return_matches_manual_recompute(self):
        # No-lookahead: signal on day t earns the t -> t+1 return.
        df = _ohlcv(60)
        signals = backtest._signals(df, "macd_crossover")
        closes = [float(v) for v in df["Close"].tolist()]
        rets = risk.returns_from_prices(closes)
        equity = 1.0
        for pos, ret in zip(signals[:-1], rets):
            equity *= 1.0 + pos * ret
        out = backtest.run_strategy(df, "macd_crossover")
        assert out["total_return"] == pytest.approx(equity - 1.0, abs=1e-4)

    def test_benchmark_is_buy_and_hold(self):
        df = _ohlcv(60)
        closes = [float(v) for v in df["Close"].tolist()]
        out = backtest.run_strategy(df, "sma_crossover")
        assert out["benchmark_total_return"] == pytest.approx(
            closes[-1] / closes[0] - 1.0, abs=1e-4
        )

    def test_costs_reduce_return_when_trades_occur(self):
        df = _ohlcv(60)
        free = backtest.run_strategy(df, "sma_crossover", cost_bps=0.0)
        paid = backtest.run_strategy(df, "sma_crossover", cost_bps=25.0)
        assert free["n_trades"] > 0
        assert paid["total_return"] < free["total_return"]
        assert paid["cost_bps"] == 25.0

    def test_uptrend_sma_crossover_is_mostly_long(self):
        # Monotonic uptrend: both partial-window SMAs are equal (flat) for the
        # first 50 bars, then the 50 SMA rides above the 200 SMA for good.
        out = backtest.run_strategy(_ohlcv(300), "sma_crossover")
        assert out["time_in_market"] > 0.8
        assert out["total_return"] > 0.0


class TestStrategyBacktestTool:
    def _patch_yf(self, monkeypatch, rows: int = 60):
        df = _ohlcv(rows)
        hist = df.drop(columns=["Date"]).set_index(df["Date"])
        ticker = MagicMock()
        ticker.history.return_value = hist
        fake_yf = MagicMock()
        fake_yf.Ticker.return_value = ticker
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    def test_tool_output_shape_and_provenance(self, monkeypatch):
        self._patch_yf(monkeypatch)
        reg = consultant_registry()
        out = json.loads(
            reg.dispatch(
                "run_strategy_backtest",
                '{"ticker": "aapl", "strategy": "sma_crossover"}',
            )
        )
        assert out["ticker"] == "AAPL"
        assert out["strategy"] == "sma_crossover"
        assert out["rule"] == backtest.STRATEGIES["sma_crossover"]
        assert out["as_of"] == "2026-03-01"  # last of 60 daily bars
        assert "data/backtest.py" in out["source"]
        for key in (
            "total_return_pct",
            "annualized_return_pct",
            "benchmark_total_return_pct",
            "benchmark_annualized_return_pct",
            "time_in_market_pct",
            "ann_vol_pct",
            "max_drawdown_pct",
            "hist_var_1d_pct",
            "es_1d_pct",
        ):
            assert isinstance(out[key], float), key
        assert out["n_trades"] >= 1
        assert out["var_level"] == 0.99

    def test_unknown_strategy_returns_error_envelope(self, monkeypatch):
        self._patch_yf(monkeypatch)
        reg = consultant_registry()
        out = json.loads(
            reg.dispatch(
                "run_strategy_backtest",
                '{"ticker": "AAPL", "strategy": "momo_yolo"}',
            )
        )
        assert "error" in out
        assert "unknown strategy" in out["error"]

    def test_schema_advertises_strategy_catalog(self):
        reg = consultant_registry()
        tool = next(
            t for t in reg.schemas() if t["function"]["name"] == "run_strategy_backtest"
        )
        enum = tool["function"]["parameters"]["properties"]["strategy"]["enum"]
        assert set(enum) == set(backtest.STRATEGIES)

    def test_consultant_subset_includes_strategy_backtest(self):
        assert "run_strategy_backtest" in CONSULTANT_TOOL_NAMES
        assert "run_strategy_backtest" in consultant_registry().names()
