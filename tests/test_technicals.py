"""Offline tests for the technical-summary gauge engine (no network)."""

from __future__ import annotations

import math

import pytest

from investment_firm.core.technicals import (
    TechnicalsError,
    _interp_pct,
    format_number,
    technical_summary,
)

_DIR_CLASSES = {"strong-sell", "sell", "neutral", "buy", "strong-buy"}
_TREND_CLASSES = {"strength-0", "strength-1", "strength-2", "strength-3", "strength-4"}
_VOL_CLASSES = {"vol-0", "vol-1", "vol-2", "vol-3", "vol-4"}


def _make_ohlc(n: int = 140) -> list:
    """Deterministic synthetic OHLC: a gentle uptrend plus an oscillation."""
    bars = []
    for i in range(n):
        base = 100.0 + i * 0.4 + 6.0 * math.sin(i / 7.0)
        high = base + 1.5
        low = base - 1.5
        close = base + 0.5 * math.cos(i / 5.0)
        bars.append(
            {
                "time": f"2026-01-{(i % 27) + 1:02d}",
                "open": round(base, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
            }
        )
    # Give the last bar a stable, known timestamp for the as_of assertion.
    bars[-1]["time"] = "2026-07-06"
    return bars


class TestFormatNumber:
    def test_thousands_suffix(self):
        assert format_number(60123, 1) == "60.1K"

    def test_millions_suffix(self):
        assert format_number(1_500_000, 1) == "1.5M"

    def test_billions_suffix(self):
        assert format_number(2_300_000_000, 1) == "2.3B"

    def test_plain_two_decimals(self):
        assert format_number(-259.2, 2) == "-259.20"

    def test_non_finite_is_na(self):
        assert format_number(float("nan")) == "n/a"
        assert format_number(None) == "n/a"


class TestInterpPct:
    def test_ascending_midpoint(self):
        control = [(0, 0), (100, 100)]
        assert _interp_pct(50, control) == pytest.approx(50.0)

    def test_descending_axis(self):
        # High value = left (0%), low value = right (100%).
        control = [(100, 0), (0, 100)]
        assert _interp_pct(75, control) == pytest.approx(25.0)

    def test_clamps_outside_range(self):
        control = [(0, 0), (100, 100)]
        assert _interp_pct(-10, control) == 0.0
        assert _interp_pct(999, control) == 100.0


class TestTechnicalSummary:
    def test_returns_expected_rows(self):
        summary = technical_summary(_make_ohlc())
        keys = [row["key"] for row in summary["rows"]]
        for expected in ("rsi", "stoch", "wr", "cci", "roc", "macd", "adx", "atr"):
            assert expected in keys
        assert summary["as_of"] == "2026-07-06"

    def test_every_row_is_well_formed(self):
        summary = technical_summary(_make_ohlc())
        for row in summary["rows"]:
            assert 0.0 <= row["marker_pct"] <= 100.0
            assert len(row["segments"]) == 5
            assert len(row["ticks"]) == 4
            assert all(0 < t["pct"] < 100 for t in row["ticks"])
            assert row["action"]
            assert row["display"]

    def test_directional_rows_use_action_palette(self):
        summary = technical_summary(_make_ohlc())
        for row in summary["rows"]:
            if row["kind"] == "momentum":
                assert row["action_class"] in _DIR_CLASSES

    def test_adx_row_is_trend_strength(self):
        summary = technical_summary(_make_ohlc())
        adx = next(r for r in summary["rows"] if r["key"] == "adx")
        assert adx["kind"] == "trend"
        assert adx["action_class"] in _TREND_CLASSES
        assert adx["action"].endswith("Trend")

    def test_atr_row_is_volatility_with_percent_ticks(self):
        summary = technical_summary(_make_ohlc())
        atr = next(r for r in summary["rows"] if r["key"] == "atr")
        assert atr["kind"] == "volatility"
        assert atr["action_class"] in _VOL_CLASSES
        assert atr["action"].endswith("Vol")
        assert all(t["label"].endswith("%") for t in atr["ticks"])

    def test_too_little_history_raises(self):
        with pytest.raises(TechnicalsError):
            technical_summary(_make_ohlc(n=5))
