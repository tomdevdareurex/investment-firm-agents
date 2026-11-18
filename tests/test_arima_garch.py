"""Offline tests for the ARIMA(1,1,1) / ARIMA-GARCH(1,1) forecast cones."""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from investment_firm.data import arima_garch as ag  # noqa: E402
from investment_firm.data.forecast import ForecastError  # noqa: E402


def _simulate(n, mu, phi, theta, omega, alpha=0.0, beta=0.0, seed=7):
    """Closes whose log returns (in percent) follow ARMA(1,1)-GARCH(1,1)."""
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    e = np.zeros(n)
    s2 = omega / (1.0 - alpha - beta)
    for t in range(1, n):
        s2 = omega + alpha * e[t - 1] ** 2 + beta * s2
        e[t] = math.sqrt(s2) * rng.standard_normal()
        r[t] = mu + phi * r[t - 1] + theta * e[t - 1] + e[t]
    return list(100.0 * np.exp(np.cumsum(r / 100.0)))


def _ordered(q, h):
    keys = ("q10", "q25", "q50", "q75", "q90")
    assert all(len(q[k]) == h for k in keys)
    for i in range(h):
        vals = [q[k][i] for k in keys]
        assert vals == sorted(vals)
        assert all(v > 0 for v in vals)


class TestPsiWeights:
    def test_cumulative_psi(self):
        assert ag._psi_cumsum(0.5, 0.2, 3) == pytest.approx([1.0, 1.7, 2.05])

    def test_white_noise_psi_is_one(self):
        assert ag._psi_cumsum(0.0, 0.0, 4) == pytest.approx([1.0] * 4)


class TestArima:
    def test_recovers_arma_coefficients(self):
        closes = _simulate(2500, 0.02, 0.5, -0.2, omega=1.0)
        out = ag.arima_garch_quantiles(closes, 20)
        p = out["params"]
        assert p["phi"] == pytest.approx(0.5, abs=0.15)
        assert p["theta"] == pytest.approx(-0.2, abs=0.15)
        assert p["sigma_pct"] == pytest.approx(1.0, abs=0.05)
        assert out["fit"]["n_obs"] == 2498
        assert math.isfinite(out["fit"]["aic"])
        assert "alpha" not in p

    def test_cone_shape_and_constant_vol(self):
        closes = _simulate(600, 0.0, 0.3, 0.1, omega=1.0)
        out = ag.arima_garch_quantiles(closes, 30)
        _ordered(out["quantiles"], 30)
        width = [
            hi - lo for lo, hi in zip(out["quantiles"]["q10"], out["quantiles"]["q90"])
        ]
        assert all(b > a for a, b in zip(width, width[1:]))
        assert len(set(out["step_vol_pct"])) == 1

    def test_white_noise_width_matches_sqrt_time(self):
        closes = _simulate(3000, 0.0, 0.0, 0.0, omega=1.0, seed=3)
        out = ag.arima_garch_quantiles(closes, 25)
        q = out["quantiles"]
        p = out["params"]
        # With phi ~ theta ~ 0 the k-step log sd is ~ sigma * sqrt(k).
        log_sd_25 = math.log(q["q90"][-1] / q["q10"][-1]) / (2 * 1.2815515655446004)
        assert log_sd_25 == pytest.approx(p["sigma_pct"] / 100 * 5, rel=0.25)


class TestArimaGarch:
    def test_recovers_garch_parameters(self):
        closes = _simulate(3000, 0.03, 0.4, -0.2, omega=0.02, alpha=0.08, beta=0.9)
        out = ag.arima_garch_quantiles(closes, 20, garch=True)
        p = out["params"]
        assert p["alpha"] == pytest.approx(0.08, abs=0.05)
        assert p["beta"] == pytest.approx(0.9, abs=0.06)
        assert p["persistence"] < 1.0
        assert p["phi"] == pytest.approx(0.4, abs=0.2)
        assert "sigma_pct" not in p
        _ordered(out["quantiles"], 20)

    def test_vol_path_reverts_to_unconditional(self):
        closes = _simulate(2000, 0.0, 0.1, 0.0, omega=0.05, alpha=0.1, beta=0.85)
        out = ag.arima_garch_quantiles(closes, 60, garch=True)
        vol = out["step_vol_pct"]
        target = out["params"]["uncond_vol_pct"]
        assert len(vol) == 60
        assert abs(vol[-1] - target) < abs(vol[0] - target) + 1e-9

    def test_warns_on_cancelling_arma_and_igarch(self, monkeypatch):
        closes = _simulate(800, 0.0, 0.0, 0.0, omega=1.0, seed=5)
        real_fit = ag._fit_arma_garch

        def igarch(r, start):
            out = real_fit(r, start)
            out.update(alpha=0.1, beta=0.9, converged=False)
            return out

        monkeypatch.setattr(ag, "_fit_arma_garch", igarch)
        out = ag.arima_garch_quantiles(closes, 5, garch=True)
        text = " ".join(out["fit"]["warnings"])
        assert "IGARCH" in text
        assert "did not fully converge" in text
        assert "uncond_vol_pct" not in out["params"]

    def test_garch_beats_constant_variance_on_garch_data(self):
        closes = _simulate(2000, 0.0, 0.2, 0.0, omega=0.05, alpha=0.12, beta=0.85)
        plain = ag.arima_garch_quantiles(closes, 5)
        garch = ag.arima_garch_quantiles(closes, 5, garch=True)
        assert garch["fit"]["loglik"] > plain["fit"]["loglik"]


class TestErrors:
    def test_too_short(self):
        with pytest.raises(ForecastError):
            ag.arima_garch_quantiles([100.0 + i for i in range(10)], 5)

    def test_constant_prices(self):
        with pytest.raises(ForecastError):
            ag.arima_garch_quantiles([100.0] * 200, 5)

    def test_bad_horizon(self):
        closes = _simulate(300, 0.0, 0.1, 0.0, omega=1.0)
        with pytest.raises(ForecastError):
            ag.arima_garch_quantiles(closes, 0)
