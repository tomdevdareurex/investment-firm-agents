"""ARIMA(1,1,1) and ARIMA(1,1,1)-GARCH(1,1) forecast cones on log prices.

The model is fitted to log returns ``r_t = log P_t - log P_{t-1}`` (an ARMA(1,1)
on returns, i.e. an ARIMA(1,1,1) on the log price):

* mean      ``r_t = mu + phi * r_{t-1} + theta * eps_{t-1} + eps_t``
* variance  ``sigma2`` constant (plain ARIMA), or
            ``sigma2_t = omega + alpha * eps_{t-1}^2 + beta * sigma2_{t-1}`` (GARCH(1,1))

Both are Gaussian conditional maximum-likelihood fits; the GARCH variant fits
mean and variance jointly. The k-step variance of the cumulative log return uses
the ARMA psi-weights, ``var_k = sum_i Psi_{k-i}^2 * E[sigma2_{T+i}]`` with
``Psi_m = psi_0 + ... + psi_m``, and price quantiles are
``exp(log P_T + mean_k + z_q * sqrt(var_k))``.

numpy + scipy only (imported lazily); never touches the network. Decision
support only -- a cone is a statistical range, not a prediction.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Sequence, Tuple

from .forecast import (
    DEFAULT_QUANTILES,
    ForecastError,
    clamp_horizon,
    quantile_key,
    validate_series,
)

METHODS: Tuple[str, ...] = ("arima", "arima_garch")
METHOD_LABELS = {
    "arima": "ARIMA(1,1,1) on log price",
    "arima_garch": "ARIMA(1,1,1)-GARCH(1,1) on log price",
}
# Returns are fitted in percent so GARCH omega is not ~1e-6 (better conditioning).
_SCALE = 100.0
_COEF_BOUND = 0.99
_PERSISTENCE_MAX = 0.9999
# Diagnostics thresholds for the ``fit.warnings`` list.
_IGARCH_WARN = 0.999
_CANCEL_WARN = 0.1


def _np():
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:  # pragma: no cover - numpy ships with the data extra
        raise ForecastError(
            'ARIMA/GARCH needs numpy + scipy; run: pip install -e ".[data]"'
        ) from exc
    return np


def _scipy():
    try:
        from scipy import optimize, signal  # type: ignore
    except ImportError as exc:  # pragma: no cover - scipy ships with the data extra
        raise ForecastError(
            'ARIMA/GARCH needs scipy; run: pip install -e ".[data]"'
        ) from exc
    return optimize, signal


# ---------------------------------------------------------------------------
# Recursions
# ---------------------------------------------------------------------------


def _arma_residuals(r, mu: float, phi: float, theta: float):
    """``eps_t`` for t = 1..n-1, conditional on ``r_0`` and ``eps_0 = 0``."""
    _, signal = _scipy()
    x = r[1:] - mu - phi * r[:-1]
    # eps_t + theta * eps_{t-1} = x_t
    return signal.lfilter([1.0], [1.0, theta], x)


def _garch_variance(eps, omega: float, alpha: float, beta: float, s0: float):
    """``sigma2_t`` per residual; pre-sample ``eps^2`` and ``sigma2`` are ``s0``."""
    np = _np()
    _, signal = _scipy()
    prev_sq = np.concatenate(([s0], eps[:-1] ** 2))
    u = omega + alpha * prev_sq
    # sigma2_t - beta * sigma2_{t-1} = u_t with sigma2_0 = s0
    return signal.lfilter([1.0], [1.0, -beta], u, zi=[beta * s0])[0]


# ---------------------------------------------------------------------------
# Fits
# ---------------------------------------------------------------------------


def _fit_arma(r) -> Dict[str, Any]:
    np = _np()
    optimize, _ = _scipy()
    n = len(r) - 1

    def sse(p):
        eps = _arma_residuals(r, p[0], p[1], p[2])
        val = float(np.dot(eps, eps))
        return val if math.isfinite(val) else 1e300

    bounds = [(None, None), (-_COEF_BOUND, _COEF_BOUND), (-_COEF_BOUND, _COEF_BOUND)]
    mean = float(np.mean(r))
    best = None
    # Several starts: ARMA(1,1) has a near-flat ridge where phi ~ -theta.
    for phi0, theta0 in ((0.2, 0.0), (-0.2, 0.0), (0.5, -0.3), (-0.5, 0.3)):
        res = optimize.minimize(
            sse, x0=[mean, phi0, theta0], method="L-BFGS-B", bounds=bounds
        )
        if best is None or res.fun < best.fun:
            best = res
    mu, phi, theta = (float(v) for v in best.x)
    sigma2 = float(best.fun) / n
    if not (math.isfinite(sigma2) and sigma2 > 0):
        raise ForecastError("ARIMA fit failed: residual variance is not positive")
    loglik = -0.5 * n * (math.log(2 * math.pi) + math.log(sigma2) + 1.0)
    eps = _arma_residuals(r, mu, phi, theta)
    return {
        "mu": mu,
        "phi": phi,
        "theta": theta,
        "sigma2": sigma2,
        "loglik": loglik,
        "k": 4,
        "n": n,
        "converged": bool(best.success),
        "last_eps": float(eps[-1]),
    }


def _fit_arma_garch(r, start: Dict[str, Any]) -> Dict[str, Any]:
    np = _np()
    optimize, _ = _scipy()
    s0 = float(np.var(r))
    log2pi = math.log(2 * math.pi)

    def nll(p):
        mu, phi, theta, omega, alpha, beta = p
        eps = _arma_residuals(r, mu, phi, theta)
        s2 = _garch_variance(eps, omega, alpha, beta, s0)
        if not np.all(np.isfinite(s2)) or np.any(s2 <= 0):
            return 1e10
        val = 0.5 * float(np.sum(log2pi + np.log(s2) + eps**2 / s2))
        return val if math.isfinite(val) else 1e10

    bounds = [
        (None, None),
        (-_COEF_BOUND, _COEF_BOUND),
        (-_COEF_BOUND, _COEF_BOUND),
        (1e-8 * s0, 10.0 * s0),
        (0.0, 1.0),
        (0.0, 1.0),
    ]
    constraints = [{"type": "ineq", "fun": lambda p: _PERSISTENCE_MAX - p[4] - p[5]}]
    best = None
    for alpha0, beta0 in ((0.05, 0.90), (0.10, 0.80), (0.15, 0.60)):
        x0 = [
            start["mu"],
            start["phi"],
            start["theta"],
            max(s0 * (1.0 - alpha0 - beta0), 1e-6 * s0),
            alpha0,
            beta0,
        ]
        res = optimize.minimize(
            nll,
            x0=x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 300, "ftol": 1e-9},
        )
        if best is None or res.fun < best.fun:
            best = res
    mu, phi, theta, omega, alpha, beta = (float(v) for v in best.x)
    eps = _arma_residuals(r, mu, phi, theta)
    s2 = _garch_variance(eps, omega, alpha, beta, s0)
    if not (np.all(np.isfinite(s2)) and math.isfinite(float(best.fun))):
        raise ForecastError("GARCH fit failed: variance path is not finite")
    return {
        "mu": mu,
        "phi": phi,
        "theta": theta,
        "omega": omega,
        "alpha": alpha,
        "beta": beta,
        "loglik": -float(best.fun),
        "k": 6,
        "n": len(eps),
        "converged": bool(best.success),
        "last_eps": float(eps[-1]),
        "last_sigma2": float(s2[-1]),
    }


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def _psi_cumsum(phi: float, theta: float, h: int) -> List[float]:
    """``Psi_m = sum_{j=0..m} psi_j`` with psi_0 = 1, psi_j = phi^(j-1) (phi + theta)."""
    out: List[float] = []
    total, psi = 0.0, 1.0
    for j in range(h):
        if j == 1:
            psi = phi + theta
        elif j > 1:
            psi *= phi
        total += psi
        out.append(total)
    return out


def arima_garch_quantiles(
    closes: Sequence[float],
    steps: int,
    *,
    garch: bool = False,
    quantiles: Sequence[float] = DEFAULT_QUANTILES,
) -> Dict[str, Any]:
    """Fit ARIMA(1,1,1) on log price (optionally with GARCH(1,1) errors).

    Returns ``{"quantiles": {"q10": [...], ...}, "params": {...}, "fit": {...},
    "step_vol_pct": [...]}``: every path has ``steps`` points; ``step_vol_pct``
    is the forecast one-bar return volatility (percent) for each step.
    """
    np = _np()
    series = validate_series(closes)
    h = clamp_horizon(steps)
    for q in quantiles:
        if not 0.0 < float(q) < 1.0:
            raise ForecastError(f"quantile must lie strictly inside (0, 1); got {q}")
    logp = np.log(np.asarray(series, dtype=float))
    r = np.diff(logp) * _SCALE
    if float(np.std(r)) <= 0:
        raise ForecastError("returns have zero variance; cannot fit ARIMA")

    arma = _fit_arma(r)
    fit = _fit_arma_garch(r, arma) if garch else arma
    mu, phi, theta = fit["mu"], fit["phi"], fit["theta"]

    # Mean path of returns: one-step uses the last shock, then decays with phi.
    means: List[float] = []
    nxt = mu + phi * float(r[-1]) + theta * fit["last_eps"]
    for _ in range(h):
        means.append(nxt)
        nxt = mu + phi * nxt

    # Expected conditional variance per step.
    if garch:
        omega, alpha, beta = fit["omega"], fit["alpha"], fit["beta"]
        s2 = omega + alpha * fit["last_eps"] ** 2 + beta * fit["last_sigma2"]
        variances = []
        for _ in range(h):
            variances.append(s2)
            s2 = omega + (alpha + beta) * s2
    else:
        variances = [fit["sigma2"]] * h

    psi_cum = _psi_cumsum(phi, theta, h)
    normal = statistics.NormalDist()
    z = {quantile_key(q): normal.inv_cdf(float(q)) for q in quantiles}
    out: Dict[str, List[float]] = {k: [] for k in z}
    last_log = float(logp[-1])
    cum_mean = 0.0
    for k in range(1, h + 1):
        cum_mean += means[k - 1]
        var_k = sum(psi_cum[k - i] ** 2 * variances[i - 1] for i in range(1, k + 1))
        sd_k = math.sqrt(var_k) / _SCALE
        centre = last_log + cum_mean / _SCALE
        for key, zq in z.items():
            out[key].append(math.exp(centre + zq * sd_k))

    params: Dict[str, float] = {
        "mu_pct": round(mu, 6),
        "phi": round(phi, 6),
        "theta": round(theta, 6),
    }
    warnings: List[str] = []
    if abs(phi + theta) < _CANCEL_WARN:
        warnings.append(
            "AR and MA terms nearly cancel (phi ~ -theta): returns are close to "
            "white noise and phi/theta are weakly identified"
        )
    if garch:
        persistence = fit["alpha"] + fit["beta"]
        params.update(
            {
                "omega": round(fit["omega"], 8),
                "alpha": round(fit["alpha"], 6),
                "beta": round(fit["beta"], 6),
                "persistence": round(persistence, 6),
            }
        )
        if persistence < _IGARCH_WARN:
            params["uncond_vol_pct"] = round(
                math.sqrt(fit["omega"] / (1.0 - persistence)), 6
            )
        else:
            warnings.append(
                "GARCH persistence at the stationarity bound (alpha + beta ~ 1, "
                "IGARCH): volatility shocks do not decay, so the cone keeps widening"
            )
    else:
        params["sigma_pct"] = round(math.sqrt(fit["sigma2"]), 6)
    if not fit["converged"]:
        warnings.append("optimizer did not fully converge")

    n, k_params, loglik = fit["n"], fit["k"], fit["loglik"]
    return {
        "quantiles": out,
        "params": params,
        "fit": {
            "loglik": round(loglik, 4),
            "aic": round(2 * k_params - 2 * loglik, 4),
            "bic": round(k_params * math.log(n) - 2 * loglik, 4),
            "n_obs": n,
            "converged": fit["converged"],
            "warnings": warnings,
        },
        "step_vol_pct": [round(math.sqrt(v), 6) for v in variances],
    }
