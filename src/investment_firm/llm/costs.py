"""Cost tables (from ``config/costs.yaml``) and a per-run usage tracker.

Every model carries two figures in the YAML: approximate USD list prices per 1M tokens
(``input``/``output``) for a real-money estimate, and a unit-less relative ``weight``
per 1k tokens for budget guards. Both are **rough and editable** — nothing in the firm
depends on them being exact. Live usage comes from ``/ai/tokens``.

Pricing is **backend-aware**. On the ``databricks`` backend the logical model name is
mapped to its serving endpoint and looked up in the YAML's ``databricks:`` rate card
first; a miss falls through to the vendor ladder (exact model name → family → default).
Databricks bills from DBUs, which diverge sharply from vendor list price.

The resolved :class:`Price` carries three independent provenance fields so a wrong or
approximate number is never reported silently: ``source`` (which rung matched),
``basis`` (which table the USD came from) and ``confidence`` (how it was obtained).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from . import backends
from .models import family

# Which rung of the lookup ladder matched.
PRICE_SOURCE_MODEL = "model"
PRICE_SOURCE_FAMILY = "family"
PRICE_SOURCE_DEFAULT = "default"

# Which rate table the USD figures came from.
PRICE_BASIS_VENDOR = "vendor"
PRICE_BASIS_DATABRICKS = "databricks"

# How trustworthy the USD figures are.
PRICE_CONFIDENCE_LIST = "list"  # vendor's own published list price
PRICE_CONFIDENCE_PUBLISHED = "published"  # Databricks' own published DBU rate
PRICE_CONFIDENCE_VENDOR_PROXY = "vendor-proxy"  # no DBU rate; vendor price as proxy
PRICE_CONFIDENCE_ESTIMATED = "estimated"  # no DBU rate; nearest published sibling

# Valid values for a `src:` key inside the YAML's databricks rate card.
_DATABRICKS_CONFIDENCES = (
    PRICE_CONFIDENCE_PUBLISHED,
    PRICE_CONFIDENCE_VENDOR_PROXY,
    PRICE_CONFIDENCE_ESTIMATED,
)

# Databricks serving endpoints mirror Playground names with this prefix.
_DATABRICKS_PREFIX = "databricks-"

# Used only if the YAML has no ``default`` section at all.
_HARDCODED_DEFAULT = {"input": 1.0, "output": 4.0, "weight": 1.0}


class CostsConfigError(RuntimeError):
    """Raised when ``costs.yaml`` is missing or malformed."""


def cost_config_path() -> Path:
    """Resolve the costs config path lazily (``IFA_COSTS_CONFIG`` env override wins)."""
    override = os.getenv("IFA_COSTS_CONFIG", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config" / "costs.yaml"


@lru_cache(maxsize=1)
def load_costs(path: Optional[str] = None) -> dict:
    """Load and cache the parsed ``costs.yaml`` document."""
    cfg_path = Path(path) if path else cost_config_path()
    if not cfg_path.exists():
        raise CostsConfigError(f"Costs config not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        raise CostsConfigError(
            f"Costs config must be a mapping with a 'models' section: {cfg_path}"
        )
    _validate_databricks(data.get("databricks"), cfg_path)
    return data


def _validate_databricks(section: Any, cfg_path: Path) -> None:
    """The optional ``databricks`` rate card must be a mapping of mappings."""
    if section is None:
        return
    if not isinstance(section, dict):
        raise CostsConfigError(f"'databricks' must be a mapping: {cfg_path}")
    for key in ("models", "aliases"):
        value = section.get(key)
        if value is not None and not isinstance(value, dict):
            raise CostsConfigError(f"'databricks.{key}' must be a mapping: {cfg_path}")


def reload_costs() -> None:
    """Drop the cached YAML so the next lookup re-reads it (tests / hot edits)."""
    load_costs.cache_clear()


@dataclass(frozen=True)
class Price:
    """Resolved pricing for one model (normalised to per-1M USD, per-1k weight).

    ``source``, ``basis`` and ``confidence`` are independent — do not conflate them.
    A Databricks-basis price commonly takes its USD from the ``databricks:`` rate card
    while inheriting ``weight`` from the vendor ``models:``/``families:`` entry, since
    weight is a hand-tuned budgeting dial rather than a function of price.
    """

    input_usd: float  # USD per 1,000,000 input tokens
    output_usd: float  # USD per 1,000,000 output tokens
    weight: float  # unit-less, per 1,000 tokens
    source: str  # PRICE_SOURCE_MODEL | PRICE_SOURCE_FAMILY | PRICE_SOURCE_DEFAULT
    basis: str = PRICE_BASIS_VENDOR  # PRICE_BASIS_*
    confidence: str = PRICE_CONFIDENCE_LIST  # PRICE_CONFIDENCE_*

    @property
    def is_fallback(self) -> bool:
        return self.source != PRICE_SOURCE_MODEL

    @property
    def is_estimate(self) -> bool:
        """True when the figures were guessed rather than taken from a rate card."""
        return self.confidence in (
            PRICE_CONFIDENCE_VENDOR_PROXY,
            PRICE_CONFIDENCE_ESTIMATED,
        )


def _entry(raw: Any, *, where: str) -> Tuple[float, float, float]:
    if not isinstance(raw, dict):
        raise CostsConfigError(f"{where}: expected a mapping with input/output/weight")
    try:
        return (
            float(raw.get("input", 0.0)),
            float(raw.get("output", 0.0)),
            float(raw.get("weight", 1.0)),
        )
    except (TypeError, ValueError) as exc:
        raise CostsConfigError(f"{where}: non-numeric price value") from exc


def _normalize(model: str) -> str:
    name = (model or "").strip()
    if name.lower().startswith(_DATABRICKS_PREFIX):
        name = name[len(_DATABRICKS_PREFIX) :]
    return name


def _active_backend(backend: Optional[str]) -> str:
    """Resolve the backend to price against. Never raises.

    ``price_for`` sits on the CLI summary and web payload paths, so a bad
    ``IFA_LLM_BACKEND`` must degrade to playground pricing rather than break the run.
    """
    try:
        return backends.normalize(backend) if backend else backends.current_backend()
    except backends.BackendError:
        return backends.PLAYGROUND


def _resolve_vendor(cfg: dict, model: str) -> Tuple[Any, str, str]:
    """Walk the vendor ladder: exact model name → family → default."""
    name = _normalize(model)
    models: Dict[str, Any] = cfg.get("models") or {}
    families: Dict[str, Any] = cfg.get("families") or {}

    if name in models:
        return models[name], PRICE_SOURCE_MODEL, f"models.{name}"
    fam = family(name)
    if fam in families:
        return families[fam], PRICE_SOURCE_FAMILY, f"families.{fam}"
    return cfg.get("default") or _HARDCODED_DEFAULT, PRICE_SOURCE_DEFAULT, "default"


def _confidence(raw: dict, *, where: str) -> str:
    value = str(raw.get("src", PRICE_CONFIDENCE_ESTIMATED)).strip()
    if value not in _DATABRICKS_CONFIDENCES:
        raise CostsConfigError(
            f"{where}: unknown src {value!r}; expected one of "
            + ", ".join(_DATABRICKS_CONFIDENCES)
        )
    return value


def price_for(model: str, *, backend: Optional[str] = None) -> Price:
    """Return the :class:`Price` for ``model`` on the given (or active) backend.

    Ladder: ``databricks.models`` (databricks backend only) → ``models`` → ``families``
    → ``default``. Deliberately uncached, so a mid-session backend switch in the web UI
    takes effect immediately.
    """
    cfg = load_costs()
    usd_scale = 1_000_000.0 / float(cfg.get("usd_per_tokens") or 1_000_000)
    weight_scale = 1_000.0 / float(cfg.get("weight_per_tokens") or 1_000)

    if _active_backend(backend) == backends.DATABRICKS:
        section: Dict[str, Any] = cfg.get("databricks") or {}
        entries: Dict[str, Any] = section.get("models") or {}
        aliases: Dict[str, Any] = section.get("aliases") or {}
        # No `available=` — pricing must not hit the network or log fallback warnings.
        endpoint = _normalize(backends.map_model(model, backend=backends.DATABRICKS))
        key = str(aliases.get(endpoint, endpoint))
        if key in entries:
            raw = entries[key]
            where = f"databricks.models.{key}"
            inp, out, weight = _entry(raw, where=where)
            if not isinstance(raw, dict) or "weight" not in raw:
                vendor_raw, _, vendor_where = _resolve_vendor(cfg, model)
                weight = _entry(vendor_raw, where=vendor_where)[2]
            return Price(
                inp * usd_scale,
                out * usd_scale,
                weight * weight_scale,
                PRICE_SOURCE_MODEL,
                basis=PRICE_BASIS_DATABRICKS,
                confidence=_confidence(raw, where=where),
            )

    # Vendor ladder. Note this normalises the *original* model argument, never the
    # mapped endpoint — feeding `databricks-claude-opus-4-8` in here would turn an
    # exact `claude-4.8-opus` hit into a family fallback.
    raw, source, where = _resolve_vendor(cfg, model)
    inp, out, weight = _entry(raw, where=where)
    return Price(inp * usd_scale, out * usd_scale, weight * weight_scale, source)


def price_source(model: str, *, backend: Optional[str] = None) -> str:
    """Return ``'model'``, ``'family'`` or ``'default'`` — how ``model`` was priced."""
    return price_for(model, backend=backend).source


# --- Public helpers (backend is keyword-only and optional) -----------------


def cost_weight(model: str, *, backend: Optional[str] = None) -> float:
    """Return the relative cost weight for ``model`` (per 1,000 tokens)."""
    return price_for(model, backend=backend).weight


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    backend: Optional[str] = None,
) -> float:
    """Return unit-less estimated cost = weight * (input + output) / 1000."""
    tokens = max(0, input_tokens) + max(0, output_tokens)
    return cost_weight(model, backend=backend) * tokens / 1000.0


def usd_price(model: str, *, backend: Optional[str] = None) -> tuple:
    """Return approximate (input, output) USD price per 1M tokens for ``model``."""
    price = price_for(model, backend=backend)
    return (price.input_usd, price.output_usd)


def estimate_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    backend: Optional[str] = None,
) -> float:
    """Return an approximate real-money cost in USD (list-price estimate).

    Prices come from ``config/costs.yaml``. This is a rough budgeting figure only and
    may differ from actual provider billing.
    """
    price = price_for(model, backend=backend)
    inp = max(0, input_tokens)
    out = max(0, output_tokens)
    return inp / 1_000_000.0 * price.input_usd + out / 1_000_000.0 * price.output_usd


# --- Tracking --------------------------------------------------------------


@dataclass
class CallRecord:
    """A single LLM call's usage and cost."""

    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_units: float
    cost_usd_input: float = 0.0
    cost_usd_output: float = 0.0
    price_source: str = PRICE_SOURCE_MODEL
    price_basis: str = PRICE_BASIS_VENDOR
    price_confidence: str = PRICE_CONFIDENCE_LIST
    backend: str = backends.PLAYGROUND

    @property
    def cost_usd(self) -> float:
        return self.cost_usd_input + self.cost_usd_output

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
        *,
        backend: Optional[str] = None,
    ) -> CallRecord:
        """Record one call and return its :class:`CallRecord`.

        Priced eagerly at the backend that served the call, so a later backend switch
        does not retroactively re-price completed work.
        """
        active = _active_backend(backend)
        price = price_for(model, backend=active)
        inp = int(input_tokens)
        out = int(output_tokens)
        rec = CallRecord(
            agent=agent,
            model=model,
            input_tokens=inp,
            output_tokens=out,
            latency_s=float(latency_s),
            cost_units=price.weight * (max(0, inp) + max(0, out)) / 1000.0,
            cost_usd_input=max(0, inp) / 1_000_000.0 * price.input_usd,
            cost_usd_output=max(0, out) / 1_000_000.0 * price.output_usd,
            price_source=price.source,
            price_basis=price.basis,
            price_confidence=price.confidence,
            backend=active,
        )
        self.records.append(rec)
        return rec

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_units for r in self.records)

    @property
    def total_usd(self) -> float:
        """Approximate total real-money cost (USD, list-price estimate)."""
        return sum(r.cost_usd for r in self.records)

    @property
    def total_usd_input(self) -> float:
        return sum(r.cost_usd_input for r in self.records)

    @property
    def total_usd_output(self) -> float:
        return sum(r.cost_usd_output for r in self.records)

    def would_exceed(self, additional_tokens: int) -> bool:
        """True if adding ``additional_tokens`` would exceed the token budget."""
        if self.token_budget <= 0:
            return False
        return self.total_tokens + additional_tokens > self.token_budget

    def by_model(self) -> List[dict]:
        """Aggregate usage per model, most expensive first (JSON-friendly dicts)."""
        agg: Dict[str, dict] = {}
        for r in self.records:
            row = agg.setdefault(
                r.model,
                {
                    "model": r.model,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_units": 0.0,
                    "cost_usd_input": 0.0,
                    "cost_usd_output": 0.0,
                    "cost_usd": 0.0,
                    "price_source": r.price_source,
                    "price_basis": r.price_basis,
                    "price_confidence": r.price_confidence,
                },
            )
            row["calls"] += 1
            row["input_tokens"] += r.input_tokens
            row["output_tokens"] += r.output_tokens
            row["total_tokens"] += r.total_tokens
            row["cost_units"] += r.cost_units
            row["cost_usd_input"] += r.cost_usd_input
            row["cost_usd_output"] += r.cost_usd_output
            row["cost_usd"] += r.cost_usd
        rows = sorted(agg.values(), key=lambda x: (-x["cost_usd"], x["model"]))
        for row in rows:
            row["cost_units"] = round(row["cost_units"], 4)
            row["cost_usd_input"] = round(row["cost_usd_input"], 6)
            row["cost_usd_output"] = round(row["cost_usd_output"], 6)
            row["cost_usd"] = round(row["cost_usd"], 6)
        return rows

    def unpriced_models(self) -> List[str]:
        """Models priced via family/default fallback (not listed in costs.yaml)."""
        return sorted(
            {r.model for r in self.records if r.price_source != PRICE_SOURCE_MODEL}
        )

    def estimated_models(self) -> List[str]:
        """Models whose USD figures were guessed rather than taken from a rate card."""
        return sorted(
            {
                r.model
                for r in self.records
                if r.price_confidence
                in (PRICE_CONFIDENCE_VENDOR_PROXY, PRICE_CONFIDENCE_ESTIMATED)
            }
        )

    def vendor_priced_models(self) -> List[str]:
        """Models that ran on Databricks but were billed at vendor list rates.

        These have no entry in the ``databricks:`` rate card, so their USD figures
        under-report (or over-report) what Databricks actually charged.
        """
        return sorted(
            {
                r.model
                for r in self.records
                if r.backend == backends.DATABRICKS
                and r.price_basis == PRICE_BASIS_VENDOR
            }
        )

    def render_summary(self) -> str:
        """Return a human-readable per-agent + total usage/cost table.

        Includes both the unit-less ``cost~`` budgeting weight and a rough
        real-money ``$~`` USD list-price estimate (see :func:`estimate_usd`).
        """
        if not self.records:
            return "No LLM calls recorded."
        rows = [
            f"{'agent':<22}{'model':<22}{'tok in':>9}{'tok out':>9}"
            f"{'cost~':>8}{'$~ in':>10}{'$~ out':>10}{'$~ tot':>11}"
        ]
        rows.append("-" * 101)
        for r in self.records:
            flag = "" if r.price_source == PRICE_SOURCE_MODEL else "*"
            if r.price_confidence in (
                PRICE_CONFIDENCE_VENDOR_PROXY,
                PRICE_CONFIDENCE_ESTIMATED,
            ):
                flag += "~"
            if r.backend == backends.DATABRICKS and r.price_basis == PRICE_BASIS_VENDOR:
                flag += "!"
            rows.append(
                f"{r.agent:<22}{(r.model + flag):<22}"
                f"{r.input_tokens:>9}{r.output_tokens:>9}{r.cost_units:>8.2f}"
                f"{r.cost_usd_input:>10.4f}{r.cost_usd_output:>10.4f}{r.cost_usd:>11.4f}"
            )
        rows.append("-" * 101)
        rows.append(
            f"{'TOTAL':<44}"
            f"{self.total_input_tokens:>9}{self.total_output_tokens:>9}"
            f"{self.total_cost:>8.2f}"
            f"{self.total_usd_input:>10.4f}{self.total_usd_output:>10.4f}"
            f"{self.total_usd:>11.4f}"
        )
        rows.append(
            f"(cost~ is unit-less for budgeting; $~ ≈ ${self.total_usd:.2f} USD total)"
        )
        rows.append(
            "($~ is a rough public list-price estimate from config/costs.yaml and may "
            "differ from actual Playground/Databricks billing)"
        )
        unpriced = self.unpriced_models()
        if unpriced:
            rows.append(
                "(* not listed in costs.yaml — priced by family/default fallback: "
                + ", ".join(unpriced)
                + ")"
            )
        estimated = self.estimated_models()
        if estimated:
            rows.append(
                "(~ no published Databricks rate — estimated from the nearest "
                "published sibling: " + ", ".join(estimated) + ")"
            )
        vendor_priced = self.vendor_priced_models()
        if vendor_priced:
            rows.append(
                "(! ran on Databricks but has no databricks: entry — priced at vendor "
                "list rates, which Databricks does not bill: "
                + ", ".join(vendor_priced)
                + ")"
            )
        return "\n".join(rows)
