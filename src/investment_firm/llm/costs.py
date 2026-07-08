"""Relative cost weights and a per-run usage tracker.

These weights are **rough, unit-less, and editable** — they exist only to compare model
choices and guard a per-run budget. The live source of truth for real capabilities and
limits is the ``/ai/models`` endpoint; actual monthly usage comes from ``/ai/tokens``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .models import family

# Relative cost weight per 1,000 tokens, loosely anchored to gpt-4o-mini ~= 0.2.
# Adjust freely; nothing in the firm depends on these being exact.
COST_WEIGHTS = {
    # GPT
    "gpt-5.5": 6.0,
    "gpt-5.4": 4.0,
    "gpt-5.4-mini": 0.5,
    "gpt-5-mini": 0.3,
    "gpt-5-nano": 0.1,
    "gpt-4o-mini": 0.2,
    "gpt-4.1": 1.5,
    "gpt-4.1-mini": 0.3,
    "gpt-4.1-nano": 0.1,
    "o4-mini": 0.5,
    # Gemini
    "gemini-3.5-flash": 0.3,
    "gemini-3.1-pro-preview": 3.0,
    "gemini-3-flash-preview": 0.3,
    "gemini-2.5-flash": 0.2,
    "gemini-2.5-pro": 1.5,
    # Claude
    "claude-4.8-opus": 12.0,
    "claude-4.7-opus": 10.0,
    "claude-4.6-opus": 9.0,
    "claude-4.6-sonnet": 2.5,
    "claude-4.5-opus": 8.0,
    "claude-4.5-sonnet": 2.0,
    "claude-4.5-haiku": 0.5,
    # Other
    "kimi-k2.6": 0.4,
    # Embeddings
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-005": 0.02,
    "text-embedding-ada-002": 0.10,
}

# Fallback weight by family when a specific model is not in the table above.
_FAMILY_FALLBACK = {"claude": 2.0, "gpt": 1.0, "gemini": 1.0, "other": 1.0}
DEFAULT_WEIGHT = 1.0


def cost_weight(model: str) -> float:
    """Return the relative cost weight for ``model`` (per 1,000 tokens)."""
    if model in COST_WEIGHTS:
        return COST_WEIGHTS[model]
    return _FAMILY_FALLBACK.get(family(model), DEFAULT_WEIGHT)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return unit-less estimated cost = weight * (input + output) / 1000."""
    tokens = max(0, input_tokens) + max(0, output_tokens)
    return cost_weight(model) * tokens / 1000.0


# Rough real-money list prices in USD per 1,000,000 tokens as (input, output).
# These are APPROXIMATE public API list prices for budgeting only; they are
# editable and may differ from actual DBAG Playground / Databricks billing.
# Output tokens are typically several times more expensive than input tokens.
USD_PRICES = {
    # GPT (USD per 1M tokens: input, output)
    "gpt-5.5": (5.0, 15.0),
    "gpt-5.4": (3.0, 12.0),
    "gpt-5.4-mini": (0.5, 1.5),
    "gpt-5-mini": (0.4, 1.2),
    "gpt-5-nano": (0.1, 0.4),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1-nano": (0.1, 0.4),
    "o4-mini": (1.1, 4.4),
    # Gemini
    "gemini-3.5-flash": (0.3, 2.5),
    "gemini-3.1-pro-preview": (1.25, 10.0),
    "gemini-3-flash-preview": (0.3, 2.5),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
    # Claude
    "claude-4.8-opus": (15.0, 75.0),
    "claude-4.7-opus": (15.0, 75.0),
    "claude-4.6-opus": (15.0, 75.0),
    "claude-4.6-sonnet": (3.0, 15.0),
    "claude-4.5-opus": (15.0, 75.0),
    "claude-4.5-sonnet": (3.0, 15.0),
    "claude-4.5-haiku": (1.0, 5.0),
    # Other
    "kimi-k2.6": (0.6, 2.5),
    # Embeddings (input-priced only)
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-005": (0.02, 0.0),
    "text-embedding-ada-002": (0.10, 0.0),
}

# Fallback (input, output) USD-per-1M by family when a model is not listed.
_FAMILY_USD_FALLBACK = {
    "claude": (3.0, 15.0),
    "gpt": (2.0, 8.0),
    "gemini": (0.5, 4.0),
    "other": (1.0, 4.0),
}
DEFAULT_USD = (1.0, 4.0)


def usd_price(model: str) -> tuple:
    """Return approximate (input, output) USD price per 1M tokens for ``model``."""
    if model in USD_PRICES:
        return USD_PRICES[model]
    return _FAMILY_USD_FALLBACK.get(family(model), DEFAULT_USD)


def estimate_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return an approximate real-money cost in USD (list-price estimate).

    Uses per-model input/output prices from :data:`USD_PRICES`. This is a rough
    budgeting figure only and may differ from actual provider billing.
    """
    in_price, out_price = usd_price(model)
    inp = max(0, input_tokens)
    out = max(0, output_tokens)
    return inp / 1_000_000.0 * in_price + out / 1_000_000.0 * out_price


@dataclass
class CallRecord:
    """A single LLM call's usage and cost."""

    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_units: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class RunTracker:
    """Accumulates per-call usage for one run and renders a summary.

    Optionally enforces a per-run token budget (see :meth:`would_exceed`).
    """

    token_budget: int = 0  # 0 = no budget enforced
    records: List[CallRecord] = field(default_factory=list)

    def record(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_s: float = 0.0,
    ) -> CallRecord:
        """Record one call and return its :class:`CallRecord`."""
        rec = CallRecord(
            agent=agent,
            model=model,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            latency_s=float(latency_s),
            cost_units=estimate_cost(model, input_tokens, output_tokens),
        )
        self.records.append(rec)
        return rec

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_units for r in self.records)

    @property
    def total_usd(self) -> float:
        """Approximate total real-money cost (USD, list-price estimate)."""
        return sum(
            estimate_usd(r.model, r.input_tokens, r.output_tokens) for r in self.records
        )

    def would_exceed(self, additional_tokens: int) -> bool:
        """True if adding ``additional_tokens`` would exceed the token budget."""
        if self.token_budget <= 0:
            return False
        return self.total_tokens + additional_tokens > self.token_budget

    def render_summary(self) -> str:
        """Return a human-readable per-agent + total usage/cost table.

        Includes both the unit-less ``cost~`` budgeting weight and a rough
        real-money ``$~`` USD list-price estimate (see :func:`estimate_usd`).
        """
        if not self.records:
            return "No LLM calls recorded."
        rows = [
            f"{'agent':<22}{'model':<22}{'tokens':>10}{'cost~':>10}{'$~ (est)':>12}"
        ]
        rows.append("-" * 76)
        for r in self.records:
            usd = estimate_usd(r.model, r.input_tokens, r.output_tokens)
            rows.append(
                f"{r.agent:<22}{r.model:<22}{r.total_tokens:>10}"
                f"{r.cost_units:>10.2f}{usd:>12.4f}"
            )
        rows.append("-" * 76)
        rows.append(
            f"{'TOTAL':<44}{self.total_tokens:>10}"
            f"{self.total_cost:>10.2f}{self.total_usd:>12.4f}"
        )
        rows.append(
            f"(cost~ is unit-less for budgeting; $~ ≈ ${self.total_usd:.2f} USD total)"
        )
        rows.append(
            "($~ is a rough public list-price estimate and may differ from actual "
            "Playground/Databricks billing)"
        )
        return "\n".join(rows)
