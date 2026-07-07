"""Moved to :mod:`investment_firm.data.technicals` — import from there.

This shim keeps the old import path working; it re-exports the public API only.
"""

from __future__ import annotations

from investment_firm.data.technicals import (
    TechnicalsError,
    format_number,
    technical_summary,
)

__all__ = [
    "TechnicalsError",
    "format_number",
    "technical_summary",
]
