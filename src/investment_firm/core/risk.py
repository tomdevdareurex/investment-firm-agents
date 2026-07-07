"""Moved to :mod:`investment_firm.data.risk` — import from there.

This shim keeps the old import path working; it re-exports the public API only.
"""

from __future__ import annotations

from investment_firm.data.risk import (
    annualized_vol,
    expected_shortfall,
    historical_var,
    max_drawdown,
    parametric_var,
    returns_from_prices,
    risk_summary,
)

__all__ = [
    "annualized_vol",
    "expected_shortfall",
    "historical_var",
    "max_drawdown",
    "parametric_var",
    "returns_from_prices",
    "risk_summary",
]
