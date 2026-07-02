"""Pure-Python quantitative risk metrics (stdlib only: math, statistics).

No numpy/pandas required. All functions are stateless and immutable-friendly —
they return new values, never mutate inputs.

Sign convention for VaR / ES
-----------------------------
``historical_var``, ``parametric_var``, and ``expected_shortfall`` all return a
**positive** number representing the *loss magnitude* (fraction of portfolio value)
at the specified confidence level.

For ``parametric_var`` the formula is ``-(mu + z_alpha * sigma)`` where
``z_alpha = NormalDist().inv_cdf(1 - level) < 0``.  For a portfolio with strongly
positive drift the result can be negative, which means at that confidence level the
distribution predicts a gain, not a loss.  We do **not** clamp to zero — the sign
carries information.
"""
from __future__ import annotations

import math
import statistics
from typing import Dict, Sequence


# ---------------------------------------------------------------------------
# Core building blocks
# ---------------------------------------------------------------------------


def returns_from_prices(prices: Sequence[float]) -> list[float]:
    """Compute simple daily returns from a price series.

    Args:
        prices: Sequence of positive closing prices, oldest first.

    Returns:
        List of daily simple returns: ``(p[t] - p[t-1]) / p[t-1]``.

    Raises:
        ValueError: if fewer than 2 prices are supplied or any price is non-positive.
    """
    prices = list(prices)
    if len(prices) < 2:
        raise ValueError(f"Need at least 2 prices to compute returns; got {len(prices)}")
    for i, p in enumerate(prices):
        if p <= 0:
            raise ValueError(f"Price at index {i} is non-positive: {p}")
    return [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]


def _sorted_returns(returns: Sequence[float]) -> list[float]:
    """Return a sorted copy (ascending) of the returns list."""
    return sorted(returns)


def _interpolate_quantile(sorted_vals: list[float], q: float) -> float:
    """Linear interpolation of quantile ``q`` in [0, 1] over ``sorted_vals``."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    # Map q to a 0-based floating index
    index = q * (n - 1)
    lo = int(index)
    hi = min(lo + 1, n - 1)
    frac = index - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


# ---------------------------------------------------------------------------
# Risk measures
# ---------------------------------------------------------------------------


def historical_var(returns: Sequence[float], level: float = 0.99) -> float:
    """Historical (empirical) Value-at-Risk as a positive loss fraction.

    Uses linear interpolation on the sorted return series.

    Args:
        returns: Sequence of daily returns (as fractions, e.g. -0.02 for -2%).
        level: Confidence level in (0, 1).  Default 0.99 = 99% VaR.

    Returns:
        Positive loss magnitude at the ``(1 - level)`` quantile.

    Raises:
        ValueError: if ``returns`` is empty or ``level`` is not in (0, 1).
    """
    returns = list(returns)
    if not returns:
        raise ValueError("returns must not be empty")
    if not (0 < level < 1):
        raise ValueError(f"level must be in (0, 1); got {level}")
    sorted_r = _sorted_returns(returns)
    q = 1.0 - level  # e.g. 0.01 for 99% VaR
    quantile_value = _interpolate_quantile(sorted_r, q)
    return -quantile_value  # negate so a loss is positive


def parametric_var(returns: Sequence[float], level: float = 0.99) -> float:
    """Gaussian (parametric) Value-at-Risk.

    Formula: ``-(mu + z_alpha * sigma)`` where ``z_alpha`` is the
    ``(1 - level)`` quantile of the standard normal distribution.

    See module docstring for sign-convention notes.

    Args:
        returns: Sequence of daily returns.
        level: Confidence level in (0, 1).

    Returns:
        Positive loss magnitude for typical negatively-skewed distributions.
        May be negative if drift is strongly positive.

    Raises:
        ValueError: if fewer than 2 returns or ``level`` not in (0, 1).
    """
    returns = list(returns)
    if len(returns) < 2:
        raise ValueError(f"Need at least 2 returns for parametric VaR; got {len(returns)}")
    if not (0 < level < 1):
        raise ValueError(f"level must be in (0, 1); got {level}")
    mu = statistics.mean(returns)
    sigma = statistics.stdev(returns)  # sample stdev
    z_alpha = statistics.NormalDist().inv_cdf(1.0 - level)  # negative for level > 0.5
    return -(mu + z_alpha * sigma)


def expected_shortfall(returns: Sequence[float], level: float = 0.99) -> float:
    """Expected Shortfall (CVaR): mean loss beyond the historical VaR threshold.

    Args:
        returns: Sequence of daily returns.
        level: Confidence level in (0, 1).

    Returns:
        Positive average loss in the tail.  Falls back to ``historical_var``
        when no observations fall below the ``(1 - level)`` quantile.

    Raises:
        ValueError: if ``returns`` is empty or ``level`` not in (0, 1).
    """
    returns = list(returns)
    if not returns:
        raise ValueError("returns must not be empty")
    if not (0 < level < 1):
        raise ValueError(f"level must be in (0, 1); got {level}")
    sorted_r = _sorted_returns(returns)
    q = 1.0 - level
    threshold = _interpolate_quantile(sorted_r, q)
    tail = [r for r in sorted_r if r <= threshold]
    if not tail:
        return historical_var(returns, level)
    return -statistics.mean(tail)


def annualized_vol(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Annualized volatility (standard deviation of daily returns, scaled).

    Args:
        returns: Sequence of daily returns.
        periods_per_year: Trading days per year (default 252).

    Returns:
        Annualized volatility as a positive fraction.

    Raises:
        ValueError: if fewer than 2 returns.
    """
    returns = list(returns)
    if len(returns) < 2:
        raise ValueError(f"Need at least 2 returns for volatility; got {len(returns)}")
    daily_vol = statistics.stdev(returns)
    return daily_vol * math.sqrt(periods_per_year)


def max_drawdown(prices: Sequence[float]) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction.

    Args:
        prices: Sequence of closing prices, oldest first.

    Returns:
        Peak-to-trough drawdown magnitude, e.g. 0.25 for a 25% drop.
        Returns 0.0 if no drawdown occurred.

    Raises:
        ValueError: if fewer than 2 prices or any price is non-positive.
    """
    prices = list(prices)
    if len(prices) < 2:
        raise ValueError(f"Need at least 2 prices for drawdown; got {len(prices)}")
    for i, p in enumerate(prices):
        if p <= 0:
            raise ValueError(f"Price at index {i} is non-positive: {p}")
    peak = prices[0]
    max_dd = 0.0
    for p in prices[1:]:
        peak = max(peak, p)
        dd = (peak - p) / peak
        max_dd = max(max_dd, dd)
    return max_dd


# ---------------------------------------------------------------------------
# Composite summary
# ---------------------------------------------------------------------------


def risk_summary(prices: Sequence[float], level: float = 0.99) -> Dict[str, object]:
    """Compute all risk metrics from a price series.

    Args:
        prices: Sequence of closing prices, oldest first.
        level: VaR / ES confidence level.

    Returns:
        Dict with keys:
          - ``n_obs``: number of return observations
          - ``ann_vol``: annualized volatility (fraction, 4 d.p.)
          - ``hist_var_1d``: 1-day historical VaR (fraction, 4 d.p.)
          - ``param_var_1d``: 1-day parametric VaR (fraction, 4 d.p.)
          - ``es_1d``: 1-day Expected Shortfall (fraction, 4 d.p.)
          - ``max_drawdown``: peak-to-trough drawdown (fraction, 4 d.p.)
          - ``var_level``: the confidence level used

    Raises:
        ValueError: propagated from the underlying functions.
    """
    rets = returns_from_prices(prices)
    return {
        "n_obs": len(rets),
        "ann_vol": round(annualized_vol(rets), 4),
        "hist_var_1d": round(historical_var(rets, level), 4),
        "param_var_1d": round(parametric_var(rets, level), 4),
        "es_1d": round(expected_shortfall(rets, level), 4),
        "max_drawdown": round(max_drawdown(prices), 4),
        "var_level": level,
    }
