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

    def would_exceed(self, additional_tokens: int) -> bool:
        """True if adding ``additional_tokens`` would exceed the token budget."""
        if self.token_budget <= 0:
            return False
        return self.total_tokens + additional_tokens > self.token_budget

    def render_summary(self) -> str:
        """Return a human-readable per-agent + total usage/cost table."""
        if not self.records:
            return "No LLM calls recorded."
        rows = [f"{'agent':<22}{'model':<22}{'tokens':>10}{'cost~':>10}"]
        rows.append("-" * 64)
        for r in self.records:
            rows.append(
                f"{r.agent:<22}{r.model:<22}{r.total_tokens:>10}{r.cost_units:>10.2f}"
            )
        rows.append("-" * 64)
        rows.append(f"{'TOTAL':<44}{self.total_tokens:>10}{self.total_cost:>10.2f}")
        rows.append("(cost is unit-less and approximate — for budgeting only)")
        return "\n".join(rows)
