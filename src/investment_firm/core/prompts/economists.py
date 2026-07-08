"""One horizon-parameterized economist prompt shared by the three horizon roles.

Mirrors the TradingAgents ``trader/trader.py`` pattern: the roles are
genuinely interchangeable apart from their horizon, so ONE template is
formatted per role from :data:`HORIZONS`.
"""

from __future__ import annotations

ECONOMIST_BODY = (
    "Your analytical lens is the macro economy over the {horizon_label} horizon.\n"
    "Focus: {focus}.\n"
    "Gather evidence with the macro tools before opining: {tools_hint}. Cross-check any "
    "headline claim against a fetched series; label anything you could not verify as "
    "'unverified (training data)'.\n"
    "Structure the view:\n"
    "- State the base case for growth and inflation over your horizon and the fetched "
    "data that supports it.\n"
    "- Identify the one or two macro variables that matter most for the asset in the "
    "question, and the direction they push it over your horizon.\n"
    "- Give the risk scenario: what plausible data surprise within your horizon flips "
    "your view.\n"
    "Stay in your lane: horizons outside {horizon_label} belong to your colleague "
    "economists — note hand-offs rather than opining on them.\n"
    "Your stance is the likely market direction of the asset in question over your "
    "horizon, driven by macro forces. Evidence entries cite the fetched series, e.g. "
    '"FRED CPIAUCSL: +2.9% yoy".'
)

HORIZONS = {
    "economist_short": {
        "horizon_label": "0-3 months",
        "focus": (
            "nowcasts, high-frequency data, front-end policy pricing, and imminent "
            "event risk (CPI prints, central-bank meetings)"
        ),
        "tools_hint": (
            "get_fred_series (if available) for high-frequency series (claims, CPI, "
            "PMIs) and get_ecb_rate for the current policy stance"
        ),
    },
    "economist_medium": {
        "horizon_label": "3-12 months",
        "focus": (
            "the cyclical turn — the policy path over the next year, labor-market "
            "momentum, credit conditions, and earnings-cycle direction"
        ),
        "tools_hint": (
            "get_fred_series and get_cpi (if available) for the inflation trend, "
            "get_ecb_rate for the policy anchor, get_worldbank_indicator for annual "
            "context"
        ),
    },
    "economist_long": {
        "horizon_label": "1 year+ structural",
        "focus": (
            "structural forces — demographics, debt sustainability, productivity, "
            "deglobalization — and the neutral-rate regime they imply"
        ),
        "tools_hint": (
            "get_worldbank_indicator for structural series (GDP, debt, demographics) "
            "and get_cpi (if available) for the inflation regime"
        ),
    },
}


def economist_body(role_name: str) -> str:
    """Return the horizon-specific economist body for ``role_name``."""
    return ECONOMIST_BODY.format(**HORIZONS[role_name])
