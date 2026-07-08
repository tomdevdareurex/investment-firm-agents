"""Role → prompt-body registry with a department fallback chain.

Selection order in :func:`body_for`: role-specific body → department-generic
body (keyed by the firm.yaml ``group``) → :data:`~.base.GENERIC_BODY` built
from the role's mandate. ``quant`` deliberately has no role entry and falls
to the quant department body.
"""

from __future__ import annotations

from ..roster import RoleSpec
from .analysts import (
    CREDIT_BODY,
    EQUITY_BODY,
    FX_STRATEGIST_BODY,
    NEWS_BODY,
    RATES_BODY,
    SENTIMENT_BODY,
    STRATEGIST_BODY,
    TECHNICAL_BODY,
)
from .base import GENERIC_BODY
from .debate import BEAR_SEAT_BODY, BULL_SEAT_BODY
from .economists import economist_body
from .governance import (
    CIO_BODY,
    COMPLIANCE_BODY,
    DEVILS_ADVOCATE_BODY,
    IC_CHAIR_BODY,
    PM_BODY,
)
from .librarian import LIBRARIAN_BODY
from .risk import MARKET_RISK_BODY, risk_body
from .trading import desk_body

ROLE_BODIES: dict[str, str] = {
    # research — analysts
    "equity_analyst": EQUITY_BODY,
    "credit_analyst": CREDIT_BODY,
    "rates_analyst": RATES_BODY,
    "technical_analyst": TECHNICAL_BODY,
    "sentiment_analyst": SENTIMENT_BODY,
    "news_analyst": NEWS_BODY,
    "strategist": STRATEGIST_BODY,
    "fx_strategist": FX_STRATEGIST_BODY,
    # research — economists (one parameterized template, three horizons)
    "economist_short": economist_body("economist_short"),
    "economist_medium": economist_body("economist_medium"),
    "economist_long": economist_body("economist_long"),
    # research — debate seats (structured-agent bodies; debate turns use
    # BULL_SYSTEM/BEAR_SYSTEM from prompts.debate instead)
    "bull_researcher": BULL_SEAT_BODY,
    "bear_researcher": BEAR_SEAT_BODY,
    # trading desks (one parameterized template, four asset classes)
    "rates_desk": desk_body("rates_desk"),
    "equity_desk": desk_body("equity_desk"),
    "swaps_desk": desk_body("swaps_desk"),
    "fx_desk": desk_body("fx_desk"),
    # risk
    "market_risk": MARKET_RISK_BODY,
    "credit_risk": risk_body("credit_risk"),
    "liquidity_risk": risk_body("liquidity_risk"),
    # governance
    "cio": CIO_BODY,
    "pm": PM_BODY,
    "compliance": COMPLIANCE_BODY,
    "devils_advocate": DEVILS_ADVOCATE_BODY,
    "ic_chair": IC_CHAIR_BODY,
    # data
    "research_librarian": LIBRARIAN_BODY,
}

DEPARTMENT_BODIES: dict[str, str] = {
    "research": (
        "Your department is research: form an evidence-based view on the question.\n"
        "Fetch current data with the tools available (get_prices, get_fred_series, "
        "get_company_filing where relevant) rather than relying on memory, weigh the "
        "strongest evidence on both sides, and state what would change your mind."
    ),
    "trading": (
        "Your department is trading: assess execution feasibility, liquidity, and "
        "transaction cost — not the investment thesis. Use get_prices for volume and "
        "volatility context; analysis only, the firm never executes orders."
    ),
    "risk": (
        "Your department is risk: quantify what the proposed exposure could lose. Use "
        "compute_risk_metrics (VaR, Expected Shortfall, volatility, max drawdown — "
        "positive values are losses) and cite the exact figures; never estimate risk "
        "numbers from memory."
    ),
    "governance": (
        "Your department is governance: weigh the analysts' views by the quality of "
        "their verifiable evidence, not seniority or rhetoric, surface unresolved "
        "disagreements, and keep every conclusion decision-support only."
    ),
    "quant": (
        "Your department is quantitative research: frame the question in factor and "
        "systematic terms. Ground every claim in computation — run_backtest for "
        "historical behavior (read-only, buy-and-hold) and compute_risk_metrics for "
        "the risk profile; never quote a statistic you did not compute or fetch. "
        "Distinguish signal from noise: state the sample size and the regime "
        "dependence of any pattern you report."
    ),
    "data": (
        "Your department is data: produce sourced, current facts, not opinions. Tag "
        "every datapoint with its source and as_of date, flag unknowns as data gaps, "
        "and never invent or interpolate a number."
    ),
}


def body_for(spec: RoleSpec) -> str:
    """Resolve the prompt body: role-specific → department → generic mandate."""
    body = ROLE_BODIES.get(spec.name)
    if body is not None:
        return body
    body = DEPARTMENT_BODIES.get(spec.group)
    if body is not None:
        return body
    return GENERIC_BODY.format(mandate=spec.mandate)
