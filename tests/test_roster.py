"""Offline tests for core/roster.py — no network, no tokens.

Covers:
- resolve_profile precedence (explicit > IFA_PROFILE env > yaml default)
- Tier round-robin model assignment
- family hint makes assignment deterministic
- Explicit per-role model pin overrides profile
- RosterError on unknown role and unknown profile
"""

from __future__ import annotations

import pytest

from investment_firm.core.roster import (
    RosterError,
    load_firm,
    profile_names,
    resolve_profile,
    resolve_roles,
)

# ---------------------------------------------------------------------------
# Inline minimal firm dicts for edge-case tests (avoids mutation of real yaml)
# ---------------------------------------------------------------------------

_MINI_FIRM: dict = {
    "default_profile": "cheap",
    "profiles": {
        "cheap": {
            "WORKER": ["gpt-4o-mini"],
            "SENIOR": ["claude-4.5-haiku"],
            "AUTHORITY": ["claude-4.6-sonnet"],
            "HEAD": ["claude-4.8-opus"],
            "run_token_budget": 10000,
        },
        "pricey": {
            "WORKER": ["claude-4.6-sonnet", "gpt-4.1"],
            "SENIOR": ["claude-4.7-opus"],
            "AUTHORITY": ["claude-4.8-opus"],
            "HEAD": ["claude-4.8-opus"],
            "run_token_budget": 400000,
        },
    },
    "roles": {
        "analyst_a": {"group": "research", "tier": "WORKER", "mandate": "View A."},
        "analyst_b": {"group": "research", "tier": "WORKER", "mandate": "View B."},
        "analyst_c": {
            "group": "research",
            "tier": "WORKER",
            "mandate": "View C.",
            "family": "claude",
        },
        "senior_a": {"group": "research", "tier": "SENIOR", "mandate": "Senior."},
        "pinned": {
            "group": "research",
            "tier": "WORKER",
            "mandate": "Pinned.",
            "model": "special-model-xyz",
        },
    },
}


# ---------------------------------------------------------------------------
# resolve_profile precedence
# ---------------------------------------------------------------------------


class TestResolveProfilePrecedence:
    def test_explicit_name_wins(self, monkeypatch):
        monkeypatch.setenv("IFA_PROFILE", "pricey")
        result = resolve_profile("cheap", firm=_MINI_FIRM)
        assert result == "cheap"

    def test_env_var_used_when_no_explicit(self, monkeypatch):
        monkeypatch.setenv("IFA_PROFILE", "pricey")
        result = resolve_profile(None, firm=_MINI_FIRM)
        assert result == "pricey"

    def test_yaml_default_when_no_env(self, monkeypatch):
        # config.profile() defaults to "balanced" when env unset, which is not in the
        # mini firm.  We need to wipe the env so resolve_profile falls through to the
        # YAML's default_profile ("cheap").
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        monkeypatch.setattr("investment_firm.llm.config.profile", lambda: "")
        result = resolve_profile(None, firm=_MINI_FIRM)
        assert result == "cheap"

    def test_unknown_profile_raises(self, monkeypatch):
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        with pytest.raises(RosterError, match="Unknown profile"):
            resolve_profile("nonexistent", firm=_MINI_FIRM)

    def test_env_unknown_profile_raises(self, monkeypatch):
        monkeypatch.setenv("IFA_PROFILE", "nonexistent")
        with pytest.raises(RosterError, match="Unknown profile"):
            resolve_profile(None, firm=_MINI_FIRM)


# ---------------------------------------------------------------------------
# Tier round-robin model assignment
# ---------------------------------------------------------------------------


class TestTierRoundRobin:
    def test_round_robin_two_workers_pricey(self, monkeypatch):
        """Three WORKER roles should round-robin across the two WORKER models."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        firm = {**_MINI_FIRM}
        # Add a third worker with no family hint to test full round-robin
        firm = dict(_MINI_FIRM)
        firm["roles"] = {
            **_MINI_FIRM["roles"],
            "analyst_d": {"group": "r", "tier": "WORKER", "mandate": "D."},
        }
        specs = resolve_roles(
            ["analyst_a", "analyst_b", "analyst_d"],
            profile="pricey",
            firm=firm,
        )
        models = [
            specs["analyst_a"].model,
            specs["analyst_b"].model,
            specs["analyst_d"].model,
        ]
        # Should use ["claude-4.6-sonnet", "gpt-4.1"] round-robin (3 items → indices 0,1,0)
        assert models[0] == "claude-4.6-sonnet"
        assert models[1] == "gpt-4.1"
        assert models[2] == "claude-4.6-sonnet"  # wraps around

    def test_different_tiers_independent_counters(self, monkeypatch):
        """WORKER and SENIOR tier counters should be independent."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(
            ["analyst_a", "senior_a"],
            profile="pricey",
            firm=_MINI_FIRM,
        )
        assert specs["analyst_a"].model == "claude-4.6-sonnet"  # WORKER[0]
        assert specs["senior_a"].model == "claude-4.7-opus"  # SENIOR[0]


# ---------------------------------------------------------------------------
# Family hint
# ---------------------------------------------------------------------------


class TestFamilyHint:
    def test_family_hint_selects_claude(self, monkeypatch):
        """analyst_c has family=claude; should get the claude model from the pool."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(["analyst_c"], profile="pricey", firm=_MINI_FIRM)
        assert specs["analyst_c"].model == "claude-4.6-sonnet"

    def test_family_hint_fallback_to_roundrobin_when_missing(self, monkeypatch):
        """If family hint matches nothing, fall back to round-robin."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        firm = {
            "default_profile": "cheap",
            "profiles": {
                "cheap": {
                    "WORKER": ["gpt-4o-mini", "gpt-4.1"],
                    "SENIOR": ["gpt-4.1"],
                    "AUTHORITY": ["gpt-4.1"],
                    "HEAD": ["gpt-4.1"],
                },
            },
            "roles": {
                "claude_role": {
                    "group": "r",
                    "tier": "WORKER",
                    "mandate": "x",
                    "family": "claude",
                },
            },
        }
        # No claude models in pool → should fall through to round-robin (index 0)
        specs = resolve_roles(["claude_role"], profile="cheap", firm=firm)
        assert specs["claude_role"].model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Explicit per-role model pin
# ---------------------------------------------------------------------------


class TestModelPin:
    def test_explicit_model_overrides_profile(self, monkeypatch):
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(["pinned"], profile="cheap", firm=_MINI_FIRM)
        assert specs["pinned"].model == "special-model-xyz"

    def test_explicit_model_in_pricey_profile(self, monkeypatch):
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(["pinned"], profile="pricey", firm=_MINI_FIRM)
        assert specs["pinned"].model == "special-model-xyz"


# ---------------------------------------------------------------------------
# RosterError cases
# ---------------------------------------------------------------------------


class TestRosterErrors:
    def test_unknown_role_raises(self, monkeypatch):
        monkeypatch.setenv("IFA_PROFILE", "cheap")
        with pytest.raises(RosterError, match="Unknown role"):
            resolve_roles(["no_such_role"], profile="cheap", firm=_MINI_FIRM)

    def test_unknown_profile_raises(self, monkeypatch):
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        with pytest.raises(RosterError, match="Unknown profile"):
            resolve_roles(["analyst_a"], profile="fantasy", firm=_MINI_FIRM)


# ---------------------------------------------------------------------------
# Real firm.yaml integration (uses the actual config/firm.yaml)
# ---------------------------------------------------------------------------


class TestRealFirm:
    def test_profile_names_present(self):
        names = profile_names()
        assert "budget" in names
        assert "balanced" in names
        assert "premium" in names

    def test_resolve_equity_in_budget(self, monkeypatch):
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(["equity_analyst"], profile="budget")
        spec = specs["equity_analyst"]
        assert spec.tier == "WORKER"
        assert spec.mandate  # non-empty

    def test_resolve_cio_is_head_tier(self, monkeypatch):
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(["cio"], profile="balanced")
        assert specs["cio"].tier == "HEAD"

    def test_resolve_all_candidate_analysts(self, monkeypatch):
        from investment_firm.core.orchestrator import CANDIDATE_ANALYSTS

        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(CANDIDATE_ANALYSTS, profile="balanced")
        assert len(specs) == len(CANDIDATE_ANALYSTS)

    def test_cognitive_diversity_equity_credit_rates(self, monkeypatch):
        """equity=claude, rates=gemini via family hints; credit's gpt hint falls back
        to round-robin in balanced (gpt-4o-mini dropped from WORKER — web-search-capable
        families only)."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        specs = resolve_roles(
            ["equity_analyst", "credit_analyst", "rates_analyst"],
            profile="balanced",
        )
        assert specs["equity_analyst"].model.startswith("claude")
        assert specs["credit_analyst"].model.startswith(("claude", "gemini"))
        assert specs["rates_analyst"].model.startswith("gemini")

    def test_worker_tiers_have_no_gpt_models(self):
        """budget/balanced WORKER pools are Claude/Gemini only (web search capable)."""
        firm = load_firm()
        for profile in ("budget", "balanced"):
            workers = firm["profiles"][profile]["WORKER"]
            assert not any(m.startswith("gpt") for m in workers), workers

    def test_new_analyst_roles_resolve_in_all_profiles(self, monkeypatch):
        """sentiment/news/technical analysts load and resolve to a model everywhere."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        roles = ["technical_analyst", "sentiment_analyst", "news_analyst"]
        for profile in ("budget", "balanced", "premium"):
            specs = resolve_roles(roles, profile=profile)
            for role in roles:
                spec = specs[role]
                assert spec.tier == "WORKER"
                assert spec.model  # resolved to a concrete model
                assert spec.mandate  # non-empty system-prompt mandate
                assert spec.votes is True
                assert spec.vote_weight == 1

    def test_news_analyst_pins_web_capable_family(self, monkeypatch):
        """news_analyst pins Claude so it always resolves to a web-search-capable model."""
        monkeypatch.delenv("IFA_PROFILE", raising=False)
        for profile in ("budget", "balanced", "premium"):
            spec = resolve_roles(["news_analyst"], profile=profile)["news_analyst"]
            assert spec.model.startswith("claude")


# ---------------------------------------------------------------------------
# Firm-config path resolution (IFA_FIRM_CONFIG override)
# ---------------------------------------------------------------------------


class TestConfigPathOverride:
    @pytest.fixture(autouse=True)
    def _fresh_cache(self, monkeypatch):
        """Isolate the load_firm cache; restore the real config afterwards."""
        monkeypatch.delenv("IFA_FIRM_CONFIG", raising=False)
        load_firm.cache_clear()
        yield
        load_firm.cache_clear()

    def test_env_override_points_at_alternate_yaml(self, tmp_path, monkeypatch):
        alt = tmp_path / "alt_firm.yaml"
        alt.write_text(
            "default_profile: solo\n"
            "profiles:\n"
            "  solo:\n"
            "    WORKER: [gpt-4o-mini]\n"
            "roles:\n"
            "  lone_analyst: {group: research, tier: WORKER, mandate: Only view.}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("IFA_FIRM_CONFIG", str(alt))
        firm = load_firm()
        assert firm["default_profile"] == "solo"
        assert profile_names(firm) == ["solo"]

    def test_missing_override_path_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IFA_FIRM_CONFIG", str(tmp_path / "nope.yaml"))
        with pytest.raises(RosterError, match="Firm config not found"):
            load_firm()

    def test_default_path_still_loads_repo_config(self, monkeypatch):
        firm = load_firm()
        assert "profiles" in firm and "roles" in firm
