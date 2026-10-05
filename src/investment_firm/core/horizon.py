"""Investment horizon definitions (short / medium / long).

Pure strings and a frozen dataclass — no LLM imports. The horizon reaches the
agents only through the user message (:func:`frame_question`), never through the
frozen analyst JSON contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

HORIZON_MARKER = "Investment horizon: "


class HorizonError(ValueError):
    """Raised for an unknown horizon name."""


@dataclass(frozen=True)
class Horizon:
    key: str
    label: str
    years_hint: str
    chart_period: str
    chart_interval: str
    tool_lookback: str
    portfolio_period: str
    prompt_guidance: str


HORIZONS: Dict[str, Horizon] = {
    "short": Horizon(
        key="short",
        label="Short term (≤ 1 year)",
        years_hint="up to 1 year",
        chart_period="1y",
        chart_interval="1d",
        tool_lookback="1y",
        portfolio_period="1y",
        prompt_guidance=(
            "Focus on the next few weeks to 12 months: recent price action, momentum, "
            "upcoming data releases and events. Use daily data."
        ),
    ),
    "medium": Horizon(
        key="medium",
        label="Medium term (1–3 years)",
        years_hint="1 to 3 years",
        chart_period="max",
        chart_interval="1wk",
        tool_lookback="5y",
        portfolio_period="5y",
        prompt_guidance=(
            "Focus on the next 1–3 years: the economic cycle, earnings trends, "
            "interest-rate path and valuation. Prefer weekly data and multi-year history."
        ),
    ),
    "long": Horizon(
        key="long",
        label="Long term (3+ years)",
        years_hint="3 years or more",
        chart_period="max",
        chart_interval="1mo",
        tool_lookback="max",
        portfolio_period="max",
        prompt_guidance=(
            "Focus on 3+ years: structural drivers (demographics, productivity, debt, "
            "competitive position), long-run valuation and full-history drawdowns. "
            "Prefer monthly data and the maximum available history; treat short-term "
            "noise as secondary."
        ),
    ),
}

DEFAULT_HORIZON = "short"


def resolve_horizon(name: Optional[str]) -> Horizon:
    """Return the :class:`Horizon` for ``name`` (None/"" → default)."""
    key = (name or DEFAULT_HORIZON).strip().lower()
    try:
        return HORIZONS[key]
    except KeyError:
        raise HorizonError(
            f"unknown horizon {name!r}; valid: {', '.join(HORIZONS)}"
        ) from None


def frame_question(question: str, horizon: str) -> str:
    """Append the horizon framing to ``question`` (stable ``Investment horizon:`` marker)."""
    hz = resolve_horizon(horizon)
    return (
        f"{question}\n\n"
        f"{HORIZON_MARKER}{hz.label} ({hz.years_hint}). {hz.prompt_guidance} "
        f"When you use price-based tools, prefer a lookback period of "
        f"'{hz.tool_lookback}'."
    )
