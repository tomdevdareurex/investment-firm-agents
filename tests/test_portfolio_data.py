"""Offline tests for data/portfolio.py (pure compute — no network)."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from typing import List, Tuple

import pytest

from investment_firm.data import portfolio as pf
from investment_firm.data import risk
from investment_firm.data.portfolio import (
    PortfolioError,
    align_closes,
    analyze_portfolio,
    diversification,
    drawdown_details,
    normalize_weights,
    parse_portfolio,
    performance_stats,
    portfolio_equity,
)


def _bdays(n: int, start: date = date(2025, 1, 2)) -> List[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _walk(n: int, seed: int, start: float = 100.0) -> List[float]:
    rng = random.Random(seed)
    prices, p = [], start
    for _ in range(n):
        p *= 1 + rng.gauss(0.0004, 0.01)
        prices.append(p)
    return prices


def _series(n: int, seed: int) -> List[Tuple[str, float]]:
    return list(zip(_bdays(n), _walk(n, seed)))


# ---------------------------------------------------------------------------
# parse_portfolio / normalize_weights
# ---------------------------------------------------------------------------


class TestParse:
    def test_csv_weights_comma(self):
        p = parse_portfolio("ticker,weight\nspy,0.6\nTLT,0.4\n")
        assert p.mode == "weight"
        assert [(x.ticker, x.weight) for x in p.positions] == [
            ("SPY", 0.6),
            ("TLT", 0.4),
        ]
        assert p.warnings == []

    def test_csv_semicolon_with_decimal_comma(self):
        p = parse_portfolio("Ticker;Weight\nSPY;0,5\nGLD;0,5\n")
        assert [x.weight for x in p.positions] == [0.5, 0.5]

    def test_percent_weights_normalised_with_warning(self):
        p = parse_portfolio("ticker,weight\nSPY,60\nTLT,40\n")
        assert [x.weight for x in p.positions] == pytest.approx([0.6, 0.4])
        assert any("percent" in w for w in p.warnings)

    def test_quantity_csv(self):
        p = parse_portfolio("ticker,quantity,price\nSPY,10,500\nTLT,20,\n")
        assert p.mode == "quantity"
        assert p.positions[1].price is None

    def test_json_dict_and_list_forms(self):
        a = parse_portfolio('{"positions": [{"ticker": "SPY", "weight": 1}]}')
        b = parse_portfolio('[{"ticker": "spy", "weight": 1}]')
        assert a.positions == b.positions

    def test_duplicates_merged_with_warning(self):
        p = parse_portfolio("ticker,weight\nSPY,0.3\nspy,0.2\nTLT,0.5\n")
        assert [(x.ticker, x.weight) for x in p.positions] == [
            ("SPY", 0.5),
            ("TLT", 0.5),
        ]
        assert any("Duplicate" in w for w in p.warnings)

    def test_extra_columns_warned(self):
        p = parse_portfolio("ticker,weight,notes\nSPY,1,core\n")
        assert any("notes" in w for w in p.warnings)

    def test_unnormalised_weights_warned(self):
        p = parse_portfolio("ticker,weight\nSPY,0.5\nTLT,0.3\n")
        assert any("normalised" in w for w in p.warnings)

    @pytest.mark.parametrize(
        "text",
        [
            "ticker,weight\n",
            "ticker,weight\n" + "".join(f"T{i},1\n" for i in range(51)),
            "ticker,weight\nSPY,-0.1\n",
            "ticker,weight\nAAPL;DROP,1\n",
            '[{"ticker": "SPY", "weight": 1}, {"ticker": "TLT", "quantity": 3}]',
            "ticker,weight\nSPY,0\nTLT,0\n",
            '{"positions": [',
            "weight\n1\n",
            "",
        ],
    )
    def test_invalid_inputs(self, text):
        with pytest.raises(PortfolioError):
            parse_portfolio(text)

    def test_size_cap(self):
        with pytest.raises(PortfolioError, match="100 KB"):
            parse_portfolio("ticker,weight\n" + "SPY,1\n" * 20_000)

    def test_quantity_mode_uses_last_prices(self):
        p = parse_portfolio("ticker,quantity\nSPY,1\nTLT,3\n")
        w = normalize_weights(p, {"SPY": 300.0, "TLT": 100.0})
        assert w == pytest.approx({"SPY": 0.5, "TLT": 0.5})

    def test_quantity_mode_prefers_given_price(self):
        p = parse_portfolio("ticker,quantity,price\nSPY,1,100\nTLT,1,\n")
        w = normalize_weights(p, {"SPY": 900.0, "TLT": 100.0})
        assert w == pytest.approx({"SPY": 0.5, "TLT": 0.5})

    def test_quantity_mode_missing_price(self):
        p = parse_portfolio("ticker,quantity\nSPY,1\n")
        with pytest.raises(PortfolioError):
            normalize_weights(p, {})


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class TestAlignAndEquity:
    def test_inner_join_reports_dropped(self):
        dates = _bdays(40)
        a = [(d, 100.0 + i) for i, d in enumerate(dates)]
        b = [(d, 50.0 + i) for i, d in enumerate(dates[5:])]
        common, closes, dropped = align_closes({"A": a, "B": b})
        assert common == dates[5:]
        assert dropped == 5
        assert closes["A"][0] == 105.0

    def test_too_few_common_dates(self):
        dates = _bdays(40)
        with pytest.raises(PortfolioError):
            align_closes(
                {"A": [(d, 1.0) for d in dates[:20]], "B": [(d, 1.0) for d in dates]}
            )

    @pytest.mark.parametrize("mode", ["none", "monthly", "daily"])
    def test_single_asset_equity_is_price_ratio(self, mode):
        dates = _bdays(60)
        prices = _walk(60, 1)
        eq, rets, final = portfolio_equity(dates, {"A": prices}, {"A": 1.0}, mode)
        assert eq == pytest.approx([p / prices[0] for p in prices])
        assert len(rets) == 59
        assert final == pytest.approx({"A": 1.0})

    def test_buy_and_hold_differs_from_constant_mix(self):
        dates = _bdays(60)
        closes = {
            "UP": [100 * 1.01**i for i in range(60)],
            "FLAT": [100.0] * 60,
        }
        w = {"UP": 0.5, "FLAT": 0.5}
        none_eq, _, none_w = portfolio_equity(dates, closes, w, "none")
        daily_eq, _, daily_w = portfolio_equity(dates, closes, w, "daily")
        assert none_eq[-1] != pytest.approx(daily_eq[-1])
        assert none_w["UP"] > 0.5
        assert daily_w == pytest.approx(w)

    def test_monthly_rebalances_only_at_month_boundaries(self):
        dates = (
            [f"2025-01-{d:02d}" for d in range(2, 12)]
            + [f"2025-02-{d:02d}" for d in range(3, 13)]
            + [f"2025-03-{d:02d}" for d in range(3, 13)]
        )
        closes = {"UP": [100 * 1.01**i for i in range(30)], "FLAT": [100.0] * 30}
        w = {"UP": 0.5, "FLAT": 0.5}
        eq_m, _, _ = portfolio_equity(dates, closes, w, "monthly")
        eq_n, _, _ = portfolio_equity(dates, closes, w, "none")
        # Identical through January, diverge after the first February rebalance.
        assert eq_m[:11] == pytest.approx(eq_n[:11])
        assert eq_m[12] != pytest.approx(eq_n[12])
        # Weights reset to 50/50 on 2025-02-03 (index 10): the next day earns half of
        # UP's 1%, while buy-and-hold (UP drifted above 50%) earns more.
        assert eq_m[11] / eq_m[10] - 1 == pytest.approx(0.005)
        assert eq_n[11] / eq_n[10] - 1 > 0.005
        # No reset mid-month: by 2025-02-05 the mix has drifted above 50/50 again.
        assert eq_m[12] / eq_m[11] - 1 > 0.005

    def test_unknown_rebalance(self):
        with pytest.raises(PortfolioError):
            portfolio_equity(_bdays(3), {"A": [1, 2, 3]}, {"A": 1.0}, "weekly")


class TestStats:
    def test_drawdown_known_path(self):
        dates = _bdays(5)
        eq = [1.0, 1.2, 0.9, 1.0, 1.25]
        dd = drawdown_details(dates, eq)
        assert dd["max_drawdown"] == pytest.approx(0.25)
        assert dd["max_drawdown"] == risk.max_drawdown(eq)
        assert (dd["peak_date"], dd["trough_date"], dd["recovery_date"]) == (
            dates[1],
            dates[2],
            dates[4],
        )
        assert dd["drawdown_series"][2] == pytest.approx(-0.25)

    def test_drawdown_never_recovered(self):
        dd = drawdown_details(_bdays(3), [1.0, 0.8, 0.9])
        assert dd["recovery_date"] is None
        assert dd["duration_days"] > 0

    def test_constant_growth(self):
        n = 252
        eq = [1.01**i for i in range(n + 1)]
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, n + 1)]
        s = performance_stats(_bdays(n + 1), eq, rets)
        assert s["cagr"] == pytest.approx(1.01**252 - 1)
        assert s["ann_vol"] == 0
        assert s["sharpe"] is None
        assert s["sortino"] is None
        assert s["calmar"] is None
        assert s["max_drawdown"] == 0
        assert s["beta"] is None

    def test_risk_measures_match_data_risk(self):
        rets = [0.01, -0.02, 0.015, -0.005, 0.02, -0.03] * 10
        eq = [1.0]
        for r in rets:
            eq.append(eq[-1] * (1 + r))
        s = performance_stats(_bdays(len(eq)), eq, rets, level=0.95)
        assert s["hist_var_1d"] == pytest.approx(risk.historical_var(rets, 0.95))
        assert s["es_1d"] == pytest.approx(risk.expected_shortfall(rets, 0.95))
        assert s["ann_vol"] == pytest.approx(risk.annualized_vol(rets))
        assert s["var_10d_sqrt_scaled"] == pytest.approx(
            s["hist_var_1d"] * math.sqrt(10)
        )
        assert s["pct_positive_days"] == pytest.approx(0.5)
        assert s["calmar"] == pytest.approx(s["cagr"] / s["max_drawdown"])

    def test_benchmark_against_itself(self):
        prices = _walk(100, 3)
        eq = [p / prices[0] for p in prices]
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, 100)]
        s = performance_stats(_bdays(100), eq, rets, benchmark_returns=rets)
        assert s["beta"] == pytest.approx(1.0)
        assert s["correlation"] == pytest.approx(1.0)
        assert s["tracking_error"] == pytest.approx(0.0)
        assert s["information_ratio"] is None
        assert s["excess_cagr"] == pytest.approx(0.0, abs=1e-12)

    def test_diversification_equal_weights(self):
        rng = random.Random(7)
        rets = {t: [rng.gauss(0, 0.01) for _ in range(50)] for t in "ABCD"}
        d = diversification({t: 0.25 for t in "ABCD"}, rets)
        assert d["hhi"] == pytest.approx(0.25)
        assert d["effective_n"] == pytest.approx(4.0)
        assert d["correlation_matrix"]["tickers"] == list("ABCD")
        assert d["correlation_matrix"]["values"][0][0] == 1.0
        assert -1 <= d["avg_pairwise_corr"] <= 1

    def test_single_asset_has_no_pairwise_corr(self):
        d = diversification({"A": 1.0}, {"A": [0.01, -0.01, 0.02]})
        assert d["avg_pairwise_corr"] is None


# ---------------------------------------------------------------------------
# analyze_portfolio / strategy_overlays
# ---------------------------------------------------------------------------


def _analyze(n: int = 800, **kwargs):
    p = parse_portfolio("ticker,weight\nSPY,0.5\nTLT,0.3\nGLD,0.2\n")
    series = {t: _series(n, i) for i, t in enumerate(["SPY", "TLT", "GLD"])}
    return analyze_portfolio(
        p, series, benchmark_series=_series(n, 0), strategies=[], **kwargs
    )


class TestAnalyze:
    def test_json_safe_and_complete(self):
        out = _analyze()
        json.dumps(out, allow_nan=False)
        for key in (
            "positions",
            "weights",
            "window",
            "as_of",
            "stats",
            "rebalance_comparison",
            "series",
            "position_stats",
            "diversification",
            "strategy_overlays",
            "warnings",
            "params",
        ):
            assert key in out
        assert set(out["rebalance_comparison"]) == {
            "none",
            "monthly",
            "daily",
            "benchmark",
        }
        assert out["stats"]["beta"] is not None  # benchmark present
        for points in out["series"].values():
            assert len(points) <= 600
        assert out["series"]["equity"][0][1] == pytest.approx(1.0)
        assert out["series"]["equity"][-1][0] == out["as_of"]
        assert sum(out["weights"].values()) == pytest.approx(1.0)

    def test_missing_benchmark_warns_and_nulls(self):
        p = parse_portfolio("ticker,weight\nSPY,1\n")
        out = analyze_portfolio(p, {"SPY": _series(60, 1)}, strategies=[])
        assert out["stats"]["beta"] is None
        assert out["rebalance_comparison"]["benchmark"] is None
        assert any("Benchmark" in w for w in out["warnings"])

    def test_unknown_strategy_and_rebalance(self):
        p = parse_portfolio("ticker,weight\nSPY,1\n")
        with pytest.raises(PortfolioError):
            analyze_portfolio(p, {"SPY": _series(60, 1)}, strategies=["moon"])
        with pytest.raises(PortfolioError):
            analyze_portfolio(p, {"SPY": _series(60, 1)}, rebalance="weekly")

    def test_missing_series(self):
        p = parse_portfolio("ticker,weight\nSPY,1\n")
        with pytest.raises(PortfolioError, match="SPY"):
            analyze_portfolio(p, {}, strategies=[])

    def test_strategies_without_frames_warn(self):
        p = parse_portfolio("ticker,weight\nSPY,1\n")
        out = analyze_portfolio(p, {"SPY": _series(60, 1)})
        assert out["strategy_overlays"] == []
        assert any("OHLCV" in w for w in out["warnings"])


class TestStrategyOverlays:
    @staticmethod
    def _frame(n: int, seed: int):
        pd = pytest.importorskip("pandas")
        pytest.importorskip("stockstats")
        closes = _walk(n, seed)
        return pd.DataFrame(
            {
                "Date": _bdays(n),
                "Open": closes,
                "High": [c * 1.01 for c in closes],
                "Low": [c * 0.99 for c in closes],
                "Close": closes,
                "Volume": [1_000_000] * n,
            }
        )

    def test_calls_run_strategy_with_return_curve(self, monkeypatch):
        frame = self._frame(300, 1)
        real = pf.run_strategy
        calls = []

        def spy(df, name, **kwargs):
            calls.append(kwargs)
            return real(df, name, **kwargs)

        monkeypatch.setattr(pf, "run_strategy", spy)
        overlays, warnings = pf.strategy_overlays(
            {"SPY": frame}, {"SPY": 1.0}, ["sma_crossover"]
        )
        assert calls and all(c["return_curve"] is True for c in calls)
        assert len(overlays) == 1 and warnings == []
        o = overlays[0]
        assert o["strategy"] == "sma_crossover"
        assert "cagr" in o["stats"]
        assert o["equity"][0][1] == pytest.approx(1.0)
        assert o["per_ticker"][0]["ticker"] == "SPY"

    def test_combines_two_sleeves_by_weight(self):
        frames = {"A": self._frame(300, 1), "B": self._frame(300, 2)}
        overlays, _ = pf.strategy_overlays(
            frames, {"A": 0.5, "B": 0.5}, ["macd_crossover", "rsi_reversion"]
        )
        assert [o["strategy"] for o in overlays] == ["macd_crossover", "rsi_reversion"]

    def test_missing_frame_drops_strategy_with_warning(self):
        overlays, warnings = pf.strategy_overlays(
            {"A": self._frame(300, 1)}, {"A": 0.5, "B": 0.5}, ["sma_crossover"]
        )
        assert overlays == []
        assert any("sma_crossover" in w for w in warnings)

    def test_analyze_with_frames(self):
        frames = {"SPY": self._frame(300, 1)}
        p = parse_portfolio("ticker,weight\nSPY,1\n")
        series = {"SPY": list(zip(frames["SPY"]["Date"], frames["SPY"]["Close"]))}
        out = analyze_portfolio(p, series, ohlcv_frames=frames)
        assert len(out["strategy_overlays"]) == 4
        json.dumps(out, allow_nan=False)
