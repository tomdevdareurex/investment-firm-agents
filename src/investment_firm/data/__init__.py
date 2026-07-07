"""Pure, offline-testable market-data compute (quant metrics, indicators).

Layering rule: this package must not import from ``investment_firm.core`` or
``investment_firm.interfaces``. ``core/`` (tools, agents) and ``interfaces/``
(web, CLI) may import from here.
"""
