"""Offline tests for the YAML-backed cost tables in ``llm/costs.py``.

No network, no tokens. Prices come from ``config/costs.yaml``; the env override
``IFA_COSTS_CONFIG`` is exercised with a temporary file.
"""

from __future__ import annotations

import textwrap

import pytest

from investment_firm.llm import backends, costs
from investment_firm.llm.models import DATABRICKS_ENDPOINTS


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Never let a test's override or backend switch leak into the next one."""
    monkeypatch.delenv("IFA_COSTS_CONFIG", raising=False)
    monkeypatch.setenv("IFA_LLM_BACKEND", "playground")
    backends.reset_backend()
    costs.reload_costs()
    yield
    backends.reset_backend()
    costs.reload_costs()


@pytest.fixture
def on_databricks():
    """Run the test body with the databricks backend active."""
    backends.set_backend(backends.DATABRICKS)
    yield
    backends.reset_backend()


# --- shipped config --------------------------------------------------------


class TestShippedConfig:
    def test_loads_and_has_expected_sections(self):
        cfg = costs.load_costs()
        assert cfg["currency"] == "USD"
        assert isinstance(cfg["models"], dict) and cfg["models"]
        assert set(cfg["families"]) == {"claude", "gpt", "gemini", "other"}
        assert "default" in cfg

    def test_every_known_chat_and_embedding_model_is_listed(self):
        from investment_firm.llm.models import CHAT_MODELS, EMBEDDING_MODELS

        listed = set(costs.load_costs()["models"])
        missing = [m for m in CHAT_MODELS + EMBEDDING_MODELS if m not in listed]
        assert missing == [], f"add these to config/costs.yaml: {missing}"

    def test_anchor_price_matches_previous_hardcoded_table(self):
        price = costs.price_for("gpt-4o-mini")
        assert price.input_usd == pytest.approx(0.15)
        assert price.output_usd == pytest.approx(0.60)
        assert price.weight == pytest.approx(0.2)
        assert price.source == costs.PRICE_SOURCE_MODEL
        assert price.is_fallback is False

    def test_family_fallback_flagged(self):
        price = costs.price_for("claude-9.9-imaginary")
        assert price.source == costs.PRICE_SOURCE_FAMILY
        assert price.is_fallback is True
        assert (price.input_usd, price.output_usd) == (3.0, 15.0)
        assert costs.price_source("claude-9.9-imaginary") == "family"

    def test_default_fallback_for_unknown_family(self):
        # family() -> "other", which IS in families; force default via a config
        # without a matching family (see TestOverrideFile). Here "other" wins.
        assert costs.price_source("mystery-model") == costs.PRICE_SOURCE_FAMILY

    def test_databricks_prefix_strips_before_family_lookup(self):
        # A *real* endpoint name is spelled differently from the Playground name
        # (variant/version swapped), so stripping the prefix cannot produce an exact
        # hit — it lands on the claude family rung. The vendor ladder is unchanged.
        price = costs.price_for("databricks-claude-haiku-4-5")
        assert price.source == costs.PRICE_SOURCE_FAMILY
        assert (price.input_usd, price.output_usd) == (3.0, 15.0)
        assert price.basis == costs.PRICE_BASIS_VENDOR

    def test_usd_price_tuple_and_weight_helpers_still_work(self):
        assert costs.usd_price("claude-4.8-opus") == (15.0, 75.0)
        assert costs.cost_weight("claude-4.8-opus") == 12.0
        assert costs.estimate_usd("claude-4.8-opus", 1_000_000, 0) == pytest.approx(
            15.0
        )


# --- databricks rate card ----------------------------------------------------


def _endpoint_key(name: str) -> str:
    prefix = "databricks-"
    return name[len(prefix) :] if name.startswith(prefix) else name


class TestDatabricksRateCard:
    """The `databricks:` block must stay in lockstep with the live endpoint list."""

    def test_every_in_scope_databricks_endpoint_is_listed(self):
        listed = set(costs.load_costs()["databricks"]["models"])
        missing = [e for e in DATABRICKS_ENDPOINTS if _endpoint_key(e) not in listed]
        assert missing == [], f"add these to costs.yaml databricks.models: {missing}"

    def test_no_orphan_databricks_entries(self):
        section = costs.load_costs()["databricks"]
        in_scope = {_endpoint_key(e) for e in DATABRICKS_ENDPOINTS}
        orphans = sorted(set(section["models"]) - in_scope)
        assert orphans == [], f"no live endpoint for: {orphans}"
        # Every alias must point at a real entry, or the alias is dead weight.
        for alias, target in (section.get("aliases") or {}).items():
            assert target in section["models"], f"alias {alias} -> unknown {target}"

    def test_databricks_entries_declare_a_known_src(self):
        entries = costs.load_costs()["databricks"]["models"]
        bad = {
            k: v.get("src")
            for k, v in entries.items()
            if v.get("src") not in costs._DATABRICKS_CONFIDENCES
        }
        assert bad == {}

    @pytest.mark.parametrize(
        "model, expected",
        [
            ("gpt-6-astra", (10.0, 50.0)),
            ("gemini-3-5-flash", (1.875, 11.25)),
            ("gpt-oss-20b", (0.07, 0.3)),
            ("claude-sonnet-5", (2.0, 10.0)),
        ],
    )
    def test_published_rates_match_the_rate_card(self, on_databricks, model, expected):
        price = costs.price_for(model)
        assert (price.input_usd, price.output_usd) == expected
        assert price.confidence == costs.PRICE_CONFIDENCE_PUBLISHED

    def test_backend_switch_changes_price(self):
        vendor = costs.price_for("gemini-3.5-flash")
        assert (vendor.input_usd, vendor.output_usd) == (0.3, 2.5)
        assert vendor.basis == costs.PRICE_BASIS_VENDOR
        assert vendor.confidence == costs.PRICE_CONFIDENCE_LIST

        backends.set_backend(backends.DATABRICKS)
        dbx = costs.price_for("gemini-3.5-flash")
        assert (dbx.input_usd, dbx.output_usd) == (1.875, 11.25)
        assert dbx.basis == costs.PRICE_BASIS_DATABRICKS
        assert dbx.confidence == costs.PRICE_CONFIDENCE_PUBLISHED

    def test_explicit_backend_kwarg_beats_active_backend(self, on_databricks):
        forced = costs.price_for("gemini-3.5-flash", backend=backends.PLAYGROUND)
        assert (forced.input_usd, forced.output_usd) == (0.3, 2.5)
        assert costs.usd_price("gemini-3.5-flash", backend=backends.PLAYGROUND) == (
            0.3,
            2.5,
        )
        assert costs.cost_weight("gpt-4o-mini", backend=backends.PLAYGROUND) == 0.2

    def test_weight_is_inherited_from_the_vendor_entry(self, on_databricks):
        price = costs.price_for("claude-4.8-opus")
        # USD from the databricks card...
        assert (price.input_usd, price.output_usd) == (5.0, 25.0)
        assert price.basis == costs.PRICE_BASIS_DATABRICKS
        # ...but the hand-tuned budgeting dial still comes from models:.
        assert price.weight == 12.0

    def test_alias_maps_preview_name_to_real_endpoint(self, on_databricks):
        price = costs.price_for("gemini-3.1-pro-preview")
        assert price.basis == costs.PRICE_BASIS_DATABRICKS
        assert price.source == costs.PRICE_SOURCE_MODEL
        assert price.weight == 3.0  # inherited from the vendor entry

    @pytest.mark.parametrize(
        "model", ["kimi-k2.6", "gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini", "o4-mini"]
    )
    def test_unmappable_models_fall_through_to_vendor_pricing(
        self, on_databricks, model
    ):
        price = costs.price_for(model)
        assert price.basis == costs.PRICE_BASIS_VENDOR
        assert price.confidence == costs.PRICE_CONFIDENCE_LIST
        assert price == costs.price_for(model, backend=backends.PLAYGROUND)

    def test_workspace_custom_endpoint_uses_family_fallback(self, on_databricks):
        price = costs.price_for("mv_prisma_smart_v2")
        assert price.basis == costs.PRICE_BASIS_VENDOR
        assert price.source == costs.PRICE_SOURCE_FAMILY

    @pytest.mark.parametrize(
        "model", ["databricks-gte-large-en", "mxbai-embed-de-large-v1"]
    )
    def test_embedding_endpoints_price_from_the_databricks_table(
        self, on_databricks, model
    ):
        price = costs.price_for(model)
        assert price.basis == costs.PRICE_BASIS_DATABRICKS
        assert price.output_usd == 0.0

    def test_every_in_scope_endpoint_prices_exactly(self, on_databricks):
        fallbacks = [
            e
            for e in DATABRICKS_ENDPOINTS
            if costs.price_for(e).source != costs.PRICE_SOURCE_MODEL
        ]
        assert fallbacks == []

    def test_pricing_never_touches_the_network(self, on_databricks, monkeypatch):
        from investment_firm.llm import databricks_backend

        def _boom(*args, **kwargs):
            raise AssertionError("pricing must not reach the Databricks workspace")

        monkeypatch.setattr(databricks_backend, "_workspace", _boom, raising=False)
        for model in ("gemini-3.5-flash", "claude-4.8-opus", "kimi-k2.6", "gpt-5.5"):
            costs.price_for(model)

    def test_price_reflects_a_mid_session_backend_switch(self):
        # Guards against a future lru_cache on price_for.
        first = costs.price_for("gemini-3.5-flash")
        backends.set_backend(backends.DATABRICKS)
        second = costs.price_for("gemini-3.5-flash")
        backends.set_backend(backends.PLAYGROUND)
        third = costs.price_for("gemini-3.5-flash")
        assert first != second
        assert first == third

    def test_bad_backend_env_does_not_break_pricing(self, monkeypatch):
        monkeypatch.setenv("IFA_LLM_BACKEND", "bedrock")
        backends.reset_backend()
        price = costs.price_for("gemini-3.5-flash")
        assert (price.input_usd, price.output_usd) == (0.3, 2.5)
        assert price.basis == costs.PRICE_BASIS_VENDOR


# --- env override ------------------------------------------------------------


def _write_yaml(tmp_path, body: str):
    path = tmp_path / "costs.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


class TestOverrideFile:
    def test_env_override_changes_prices(self, tmp_path, monkeypatch):
        path = _write_yaml(
            tmp_path,
            """
            currency: USD
            models:
              my-model: {input: 2.0, output: 4.0, weight: 9.0}
            default: {input: 0.5, output: 0.5, weight: 0.1}
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        assert costs.cost_config_path() == path
        assert costs.price_for("my-model").weight == 9.0
        assert costs.estimate_usd("my-model", 1_000_000, 1_000_000) == pytest.approx(
            6.0
        )
        # No families section -> default rung, flagged as fallback.
        unknown = costs.price_for("claude-4.8-opus")
        assert unknown.source == costs.PRICE_SOURCE_DEFAULT
        assert unknown.input_usd == 0.5

    def test_per_token_scales_are_honoured(self, tmp_path, monkeypatch):
        # Prices written per 1k tokens and weights per 1M tokens normalise correctly.
        path = _write_yaml(
            tmp_path,
            """
            usd_per_tokens: 1000
            weight_per_tokens: 1000000
            models:
              m: {input: 0.001, output: 0.002, weight: 500}
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        price = costs.price_for("m")
        assert price.input_usd == pytest.approx(1.0)  # $0.001/1k == $1/1M
        assert price.output_usd == pytest.approx(2.0)
        assert price.weight == pytest.approx(0.5)  # 500/1M == 0.5/1k

    def test_missing_file_raises_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(tmp_path / "nope.yaml"))
        costs.reload_costs()
        with pytest.raises(costs.CostsConfigError, match="not found"):
            costs.load_costs()

    def test_malformed_file_raises(self, tmp_path, monkeypatch):
        path = _write_yaml(tmp_path, "just: a string\n")
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        with pytest.raises(costs.CostsConfigError, match="models"):
            costs.load_costs()

    def test_non_numeric_price_raises(self, tmp_path, monkeypatch):
        path = _write_yaml(
            tmp_path,
            """
            models:
              m: {input: cheap, output: 1.0, weight: 1.0}
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        with pytest.raises(costs.CostsConfigError, match="non-numeric"):
            costs.price_for("m")

    def test_weight_override_in_a_databricks_entry_wins(
        self, tmp_path, monkeypatch, on_databricks
    ):
        path = _write_yaml(
            tmp_path,
            """
            models:
              gpt-5.5: {input: 5.0, output: 15.0, weight: 6.0}
            databricks:
              models:
                gpt-5-5: {input: 2.0, output: 12.0, src: estimated, weight: 42.0}
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        price = costs.price_for("gpt-5.5")
        assert (price.input_usd, price.output_usd) == (2.0, 12.0)
        assert price.weight == 42.0  # explicit override, not the vendor's 6.0

    def test_missing_databricks_section_falls_back_cleanly(
        self, tmp_path, monkeypatch, on_databricks
    ):
        path = _write_yaml(
            tmp_path,
            """
            models:
              gpt-5.5: {input: 5.0, output: 15.0, weight: 6.0}
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        price = costs.price_for("gpt-5.5")
        assert (price.input_usd, price.output_usd) == (5.0, 15.0)
        assert price.basis == costs.PRICE_BASIS_VENDOR

    def test_malformed_databricks_section_raises(self, tmp_path, monkeypatch):
        path = _write_yaml(
            tmp_path,
            """
            models:
              m: {input: 1.0, output: 1.0, weight: 1.0}
            databricks:
              models: not-a-mapping
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        with pytest.raises(costs.CostsConfigError, match="databricks.models"):
            costs.load_costs()

    def test_unknown_src_raises(self, tmp_path, monkeypatch, on_databricks):
        path = _write_yaml(
            tmp_path,
            """
            models:
              gpt-5.5: {input: 5.0, output: 15.0, weight: 6.0}
            databricks:
              models:
                gpt-5-5: {input: 2.0, output: 12.0, src: vibes}
            """,
        )
        monkeypatch.setenv("IFA_COSTS_CONFIG", str(path))
        costs.reload_costs()
        with pytest.raises(costs.CostsConfigError, match="unknown src"):
            costs.price_for("gpt-5.5")


# --- tracker aggregation -----------------------------------------------------


class TestTrackerAggregation:
    def test_record_carries_usd_and_source(self):
        tracker = costs.RunTracker()
        rec = tracker.record("equity_analyst", "gpt-4o-mini", 1_000_000, 0)
        assert rec.cost_usd == pytest.approx(0.15)
        assert rec.price_source == costs.PRICE_SOURCE_MODEL
        assert tracker.total_usd == pytest.approx(rec.cost_usd)

    def test_record_splits_usd_by_direction(self):
        # gpt-4o-mini is 0.15 in / 0.60 out per 1M tokens.
        tracker = costs.RunTracker()
        rec = tracker.record("a", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert rec.cost_usd_input == pytest.approx(0.15)
        assert rec.cost_usd_output == pytest.approx(0.60)

    def test_cost_usd_is_the_sum_of_its_directions(self):
        tracker = costs.RunTracker()
        both = tracker.record("a", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert both.cost_usd == pytest.approx(
            both.cost_usd_input + both.cost_usd_output
        )
        input_only = tracker.record("b", "gpt-4o-mini", 1_000_000, 0)
        assert input_only.cost_usd_output == 0.0
        assert input_only.cost_usd == pytest.approx(input_only.cost_usd_input)

    def test_tracker_totals_split_tokens_and_usd(self):
        tracker = costs.RunTracker()
        tracker.record("a", "gpt-4o-mini", 1_000_000, 0)
        tracker.record("b", "gpt-4o-mini", 0, 1_000_000)
        assert tracker.total_input_tokens == 1_000_000
        assert tracker.total_output_tokens == 1_000_000
        assert tracker.total_tokens == 2_000_000
        assert tracker.total_usd_input == pytest.approx(0.15)
        assert tracker.total_usd_output == pytest.approx(0.60)
        assert tracker.total_usd == pytest.approx(0.75)

    def test_by_model_splits_usd_by_direction(self):
        tracker = costs.RunTracker()
        tracker.record("a", "gpt-4o-mini", 1000, 100)
        tracker.record("b", "claude-4.8-opus", 1000, 100)
        rows = tracker.by_model()
        for row in rows:
            assert row["cost_usd_input"] + row["cost_usd_output"] == pytest.approx(
                row["cost_usd"], abs=1e-6
            )
        assert sum(r["cost_usd_input"] for r in rows) == pytest.approx(
            tracker.total_usd_input, rel=1e-4
        )
        assert sum(r["cost_usd_output"] for r in rows) == pytest.approx(
            tracker.total_usd_output, rel=1e-4
        )

    def test_summary_shows_separate_in_and_out_columns(self):
        tracker = costs.RunTracker()
        tracker.record("a", "gpt-4o-mini", 1_000_000, 1_000_000)
        summary = tracker.render_summary()
        for header in ("tok in", "tok out", "$~ in", "$~ out", "$~ tot"):
            assert header in summary
        # The two legs are rendered independently, not as one collapsed figure.
        assert "0.1500" in summary
        assert "0.6000" in summary

    def test_output_premium_is_visible_on_databricks(self, on_databricks):
        # The point of the split: gemini-3.5-flash bills 1.875 in / 11.25 out there.
        tracker = costs.RunTracker()
        rec = tracker.record("a", "gemini-3.5-flash", 1_000_000, 1_000_000)
        assert rec.cost_usd_input == pytest.approx(1.875)
        assert rec.cost_usd_output == pytest.approx(11.25)
        assert rec.cost_usd_output == pytest.approx(rec.cost_usd_input * 6.0)

    def test_by_model_aggregates_and_sorts_by_usd(self):
        tracker = costs.RunTracker()
        tracker.record("a", "gpt-4o-mini", 1000, 100)
        tracker.record("b", "gpt-4o-mini", 1000, 100)
        tracker.record("c", "claude-4.8-opus", 1000, 100)
        rows = tracker.by_model()
        assert [r["model"] for r in rows] == ["claude-4.8-opus", "gpt-4o-mini"]
        mini = rows[1]
        assert mini["calls"] == 2
        assert mini["input_tokens"] == 2000
        assert mini["total_tokens"] == 2200
        assert mini["price_source"] == "model"
        assert sum(r["cost_usd"] for r in rows) == pytest.approx(
            tracker.total_usd, rel=1e-4
        )

    def test_unpriced_models_and_summary_flag(self):
        tracker = costs.RunTracker()
        tracker.record("x", "gpt-4o-mini", 10, 10)
        tracker.record("y", "gemini-99-unknown", 10, 10)
        assert tracker.unpriced_models() == ["gemini-99-unknown"]
        summary = tracker.render_summary()
        assert "gemini-99-unknown*" in summary
        assert "not listed in costs.yaml" in summary
        assert "costs.yaml" in summary

    def test_summary_has_no_flag_when_all_listed(self):
        tracker = costs.RunTracker()
        tracker.record("x", "gpt-4o-mini", 10, 10)
        assert tracker.unpriced_models() == []
        summary = tracker.render_summary()
        assert "not listed" not in summary
        assert "no published Databricks rate" not in summary
        assert "priced at vendor list rates" not in summary

    def test_record_carries_basis_confidence_and_backend(self, on_databricks):
        tracker = costs.RunTracker()
        rec = tracker.record("a", "gemini-3.5-flash", 1_000_000, 0)
        assert rec.backend == backends.DATABRICKS
        assert rec.price_basis == costs.PRICE_BASIS_DATABRICKS
        assert rec.price_confidence == costs.PRICE_CONFIDENCE_PUBLISHED
        assert rec.cost_usd == pytest.approx(1.875)
        row = tracker.by_model()[0]
        assert row["price_basis"] == costs.PRICE_BASIS_DATABRICKS
        assert row["price_confidence"] == costs.PRICE_CONFIDENCE_PUBLISHED

    def test_records_are_priced_at_the_backend_that_served_them(self):
        tracker = costs.RunTracker()
        tracker.record("playground-call", "gemini-3.5-flash", 1_000_000, 0)
        backends.set_backend(backends.DATABRICKS)
        tracker.record("databricks-call", "gemini-3.5-flash", 1_000_000, 0)
        assert [round(r.cost_usd, 3) for r in tracker.records] == [0.3, 1.875]

    def test_estimated_and_vendor_priced_model_accessors(self, on_databricks):
        tracker = costs.RunTracker()
        tracker.record("a", "gemini-3.5-flash", 10, 10)  # published
        tracker.record("b", "claude-4.8-opus", 10, 10)  # estimated
        tracker.record("c", "kimi-k2.6", 10, 10)  # no dbx entry -> vendor
        assert tracker.estimated_models() == ["claude-4.8-opus"]
        assert tracker.vendor_priced_models() == ["kimi-k2.6"]

    def test_summary_flags_estimated_and_vendor_rates(self, on_databricks):
        tracker = costs.RunTracker()
        tracker.record("b", "claude-4.8-opus", 10, 10)
        tracker.record("c", "kimi-k2.6", 10, 10)
        summary = tracker.render_summary()
        assert "claude-4.8-opus~" in summary
        assert "kimi-k2.6!" in summary
        assert "no published Databricks rate" in summary
        assert "priced at vendor list rates" in summary
