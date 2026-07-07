"""Resolve firm roles to concrete models from ``config/firm.yaml`` (M1).

A role declares a *tier* (``WORKER``/``SENIOR``/``AUTHORITY``/``HEAD``). A selected
*profile* (``budget``/``balanced``/``premium``) maps each tier to a list of concrete
models; roles sharing a tier are assigned round-robin for cognitive diversity, unless the
role pins a ``family:`` hint or an explicit ``model:``. This module is pure (no network,
no LLM calls) so it is fully offline-testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from ..llm import config
from ..llm.models import family


def _config_path() -> Path:
    """Resolve the firm config path lazily (``IFA_FIRM_CONFIG`` env override wins)."""
    override = os.getenv("IFA_FIRM_CONFIG", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config" / "firm.yaml"


class RosterError(RuntimeError):
    """Raised when the firm configuration is missing or inconsistent."""


@lru_cache(maxsize=1)
def load_firm(path: Optional[str] = None) -> dict:
    """Load and cache the parsed ``firm.yaml`` document."""
    cfg_path = Path(path) if path else _config_path()
    if not cfg_path.exists():
        raise RosterError(f"Firm config not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RosterError(f"Firm config is not a mapping: {cfg_path}")
    return data


def profile_names(firm: Optional[dict] = None) -> list:
    """Return the available profile names (e.g. ``budget``/``balanced``/``premium``)."""
    firm = firm or load_firm()
    return sorted((firm.get("profiles") or {}).keys())


def resolve_profile(name: Optional[str] = None, firm: Optional[dict] = None) -> str:
    """Return a valid profile name, falling back to the configured default.

    Precedence: explicit ``name`` → ``IFA_PROFILE`` (via :func:`config.profile`) →
    ``default_profile`` in the YAML → ``balanced``.
    """
    firm = firm or load_firm()
    profiles = firm.get("profiles") or {}
    candidate = name or config.profile() or firm.get("default_profile") or "balanced"
    if candidate not in profiles:
        raise RosterError(
            f"Unknown profile {candidate!r}. Available: {', '.join(sorted(profiles))}"
        )
    return candidate


@dataclass(frozen=True)
class RoleSpec:
    """A resolved role: which model it uses and its committee attributes."""

    name: str
    group: str
    tier: str
    model: str
    mandate: str
    votes: bool = False
    vote_weight: int = 0
    veto: bool = False
    optional: bool = False


def _tier_models(profile_cfg: dict, tier: str) -> list:
    models = profile_cfg.get(tier)
    if not models:
        raise RosterError(f"Profile has no models for tier {tier!r}")
    return list(models)


def _pick_model(tier_models: list, *, family_hint: Optional[str], counter: int) -> str:
    """Choose a model from ``tier_models`` honouring a family hint, else round-robin."""
    if family_hint:
        for model in tier_models:
            if family(model) == family_hint.lower():
                return model
    return tier_models[counter % len(tier_models)]


def resolve_roles(
    role_names: Optional[list] = None,
    *,
    profile: Optional[str] = None,
    firm: Optional[dict] = None,
) -> dict:
    """Resolve roles to :class:`RoleSpec`s for the selected profile.

    Args:
        role_names: Subset of roles to resolve (default: every role in the YAML).
        profile: Profile override (default: :func:`resolve_profile`).
        firm: Pre-loaded firm document (default: :func:`load_firm`).

    Returns:
        Mapping ``role_name -> RoleSpec``.
    """
    firm = firm or load_firm()
    profile_name = resolve_profile(profile, firm)
    profile_cfg = firm["profiles"][profile_name]
    roles_cfg = firm.get("roles") or {}

    wanted = role_names if role_names is not None else list(roles_cfg.keys())
    # Per-tier round-robin counters give cognitive diversity within a tier.
    tier_counters: dict = {}
    resolved: dict = {}

    for name in wanted:
        spec = roles_cfg.get(name)
        if spec is None:
            raise RosterError(f"Unknown role {name!r} in firm config")
        tier = spec.get("tier")
        if not tier:
            raise RosterError(f"Role {name!r} has no tier")

        if spec.get("model"):
            model = spec["model"]
        else:
            tier_models = _tier_models(profile_cfg, tier)
            counter = tier_counters.get(tier, 0)
            model = _pick_model(
                tier_models, family_hint=spec.get("family"), counter=counter
            )
            tier_counters[tier] = counter + 1

        resolved[name] = RoleSpec(
            name=name,
            group=spec.get("group", "?"),
            tier=tier,
            model=model,
            mandate=str(spec.get("mandate", "")).strip(),
            votes=bool(spec.get("votes", False)),
            vote_weight=int(spec.get("vote_weight", 0)),
            veto=bool(spec.get("veto", False)),
            optional=bool(spec.get("optional", False)),
        )
    return resolved


def profile_setting(
    key: str,
    default: Any = None,
    *,
    profile: Optional[str] = None,
    firm: Optional[dict] = None,
) -> Any:
    """Return a scalar setting (e.g. ``run_token_budget``) for the active profile."""
    firm = firm or load_firm()
    profile_name = resolve_profile(profile, firm)
    return firm["profiles"][profile_name].get(key, default)
