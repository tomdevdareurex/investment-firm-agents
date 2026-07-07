"""Moved to :mod:`investment_firm.data.indicators` — import from there.

This shim keeps the old import path working; it re-exports the public API only.
"""

from __future__ import annotations

from investment_firm.data.indicators import (
    INDICATORS,
    IndicatorError,
    available_indicators,
    compute,
    latest_snapshot,
    overlay_series,
)

__all__ = [
    "INDICATORS",
    "IndicatorError",
    "available_indicators",
    "compute",
    "latest_snapshot",
    "overlay_series",
]
