"""Offline tests for data/forecast.py (pure baseline cone, no torch)."""

from __future__ import annotations

import math

import pytest

from investment_firm.data import forecast as fc

_CLOSES = [100.0 * math.exp(0.001 * i + 0.01 * math.sin(i)) for i in range(300)]


class TestValidation:
    def test_short_series_rejected(self):
        with pytest.raises(fc.ForecastError, match="at least 64"):
            fc.validate_series([1.0] * 10)

    def test_non_positive_rejected(self):
        with pytest.raises(fc.ForecastError, match="positive"):
            fc.validate_series([1.0] * 70 + [0.0])

    def test_non_numeric_rejected(self):
        with pytest.raises(fc.ForecastError, match="not numeric"):
            fc.validate_series([1.0] * 70 + ["x"])

    @pytest.mark.parametrize("bad", [0, 61, -3, "abc", None])
    def test_horizon_clamped(self, bad):
        with pytest.raises(fc.ForecastError):
            fc.clamp_horizon(bad)

    def test_horizon_ok(self):
        assert fc.clamp_horizon("20") == 20
        assert fc.clamp_horizon(60) == 60


class TestRandomWalk:
    def test_shapes_and_ordering(self):
        q = fc.random_walk_quantiles(_CLOSES, 20)
        assert set(q) == {"q10", "q25", "q50", "q75", "q90"}
        assert all(len(v) == 20 for v in q.values())
        for a, b, c, d, e in zip(q["q10"], q["q25"], q["q50"], q["q75"], q["q90"]):
            assert a < b < c < d < e

    def test_median_is_flat_and_bands_widen(self):
        q = fc.random_walk_quantiles(_CLOSES, 10)
        last = _CLOSES[-1]
        assert all(abs(x - last) < 1e-9 for x in q["q50"])
        widths = [h - l for l, h in zip(q["q10"], q["q90"])]
        assert widths == sorted(widths)
        # sqrt-time scaling: width at t=4 is ~2x width at t=1 (exactly 2 in log
        # space; price space differs by cosh(z*vol) ~ 1 + 1e-4).
        assert widths[3] / widths[0] == pytest.approx(2.0, rel=1e-3)

    def test_symmetric_in_log_space(self):
        q = fc.random_walk_quantiles(_CLOSES, 5)
        last = _CLOSES[-1]
        for lo, hi in zip(q["q10"], q["q90"]):
            assert math.log(hi / last) == pytest.approx(-math.log(lo / last))

    def test_bad_quantile(self):
        with pytest.raises(fc.ForecastError):
            fc.random_walk_quantiles(_CLOSES, 5, quantiles=(0.0, 0.5))

    def test_quantile_key(self):
        assert fc.quantile_key(0.1) == "q10"
        assert fc.quantile_key(0.5) == "q50"
        assert fc.quantile_key(0.95) == "q95"


class TestCalendar:
    def test_skips_weekends(self):
        # 2026-10-02 is a Friday.
        days = fc.business_days_after("2026-10-02", 3)
        assert days == ["2026-10-05", "2026-10-06", "2026-10-07"]

    def test_accepts_datetime_prefix(self):
        assert fc.business_days_after("2026-10-01T00:00:00", 1) == ["2026-10-02"]

    def test_bad_date(self):
        with pytest.raises(fc.ForecastError):
            fc.business_days_after("yesterday", 1)

    def test_weekly_steps(self):
        assert fc.step_dates_after("2026-10-05", 2, "1wk") == [
            "2026-10-12",
            "2026-10-19",
        ]

    def test_monthly_steps_cross_year_and_clamp_day(self):
        assert fc.step_dates_after("2026-11-01", 3, "1mo") == [
            "2026-12-01",
            "2027-01-01",
            "2027-02-01",
        ]
        assert fc.step_dates_after("2026-01-31", 1, "1mo") == ["2026-02-28"]

    def test_daily_steps_are_business_days(self):
        assert fc.step_dates_after("2026-10-02", 1, "1d") == ["2026-10-05"]

    def test_bad_interval(self):
        with pytest.raises(fc.ForecastError):
            fc.step_dates_after("2026-10-02", 1, "1h")


class TestSummary:
    def test_summary_pcts(self):
        s = fc.summarize_cone([90.0, 80.0], [100.0, 100.0], [110.0, 125.0], 100.0)
        assert s == {
            "end_q10_pct": -20.0,
            "end_q50_pct": 0.0,
            "end_q90_pct": 25.0,
            "width_pct": 45.0,
        }

    def test_mismatched_lengths(self):
        with pytest.raises(fc.ForecastError):
            fc.summarize_cone([1.0], [1.0, 2.0], [1.0], 1.0)


class TestConePayload:
    def test_baseline_only(self):
        p = fc.cone_payload(
            ticker="spy", closes=_CLOSES, last_date_iso="2026-10-02", horizon=5
        )
        assert p["ticker"] == "SPY"
        assert p["is_model"] is False
        assert p["q50"] == p["baseline_q50"]
        assert len(p["dates"]) == 5 and p["dates"][0] == "2026-10-05"
        assert p["summary"] == p["baseline_summary"]
        assert p["caveat"] == fc.CAVEAT
        assert p["horizon_days"] == 5
        assert p["daily_vol_pct"] > 0
        assert p["interval"] == "1d"
        assert p["q25"] == p["baseline_q25"] and p["q75"] == p["baseline_q75"]
        assert p["summary"]["end_q25_pct"] < 0 < p["summary"]["end_q75_pct"]

    def test_monthly_interval_dates(self):
        p = fc.cone_payload(
            ticker="SPY",
            closes=_CLOSES,
            last_date_iso="2026-10-01",
            horizon=3,
            interval="1mo",
        )
        assert p["dates"] == ["2026-11-01", "2026-12-01", "2027-01-01"]
        assert p["interval"] == "1mo"

    def test_model_without_quartiles_omits_them(self):
        h = 2
        model = {"q10": [95.0] * h, "q50": [101.0] * h, "q90": [107.0] * h}
        p = fc.cone_payload(
            ticker="SPY",
            closes=_CLOSES,
            last_date_iso="2026-10-02",
            horizon=h,
            model_quantiles=model,
        )
        assert "q25" not in p and "q75" not in p
        assert "end_q25_pct" not in p["summary"]
        assert len(p["baseline_q25"]) == h

    def test_model_quantiles_override_but_keep_baseline(self):
        h = 3
        model = {"q10": [95.0] * h, "q50": [101.0] * h, "q90": [107.0] * h}
        p = fc.cone_payload(
            ticker="SPY",
            closes=_CLOSES,
            last_date_iso="2026-10-02",
            horizon=h,
            model_quantiles=model,
            source="TimesFM test",
        )
        assert p["is_model"] is True
        assert p["source"] == "TimesFM test"
        assert p["q50"] == [101.0] * h
        assert p["baseline_q50"] != p["q50"]
        assert p["summary"]["end_q50_pct"] == pytest.approx(
            (101.0 / _CLOSES[-1] - 1) * 100, abs=0.01
        )

    def test_model_quantiles_length_mismatch(self):
        with pytest.raises(fc.ForecastError, match="expected horizon"):
            fc.cone_payload(
                ticker="SPY",
                closes=_CLOSES,
                last_date_iso="2026-10-02",
                horizon=3,
                model_quantiles={"q10": [1.0], "q50": [1.0], "q90": [1.0]},
            )

    def test_model_quantiles_missing_key(self):
        with pytest.raises(fc.ForecastError, match="missing q90"):
            fc.cone_payload(
                ticker="SPY",
                closes=_CLOSES,
                last_date_iso="2026-10-02",
                horizon=1,
                model_quantiles={"q10": [1.0], "q50": [1.0]},
            )

    def test_json_safe(self):
        import json

        p = fc.cone_payload(
            ticker="SPY", closes=_CLOSES, last_date_iso="2026-10-02", horizon=2
        )
        json.dumps(p)
