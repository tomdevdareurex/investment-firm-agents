"""investment_firm — a buy-side investment firm simulated as orchestrated LLM agents.

Decision-support only: this package produces analysis and a recommendation for a human
to act on. It never executes orders or connects to a broker/exchange/wallet.
"""

from __future__ import annotations

__version__ = "0.1.0"

DISCLAIMER = (
    "Decision-support only. Not investment advice. No orders are executed; a human "
    "reviews every recommendation."
)

__all__ = ["__version__", "DISCLAIMER"]
