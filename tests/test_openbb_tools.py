"""Offline tests for the optional OpenBB data tools (no network, no openbb needed).

The OpenBB entry point is stubbed by monkeypatching ``_get_obb`` in
:mod:`investment_firm.core.tools.openbb_datasources`; availability gating is
stubbed via ``_openbb_available``. Follows the FakeLLM / inline-ToolRegistry
conventions from test_core_offline.py.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

import investment_firm.core.tools.openbb_datasources as obbds
from investment_firm.core.agent import Agent
from investment_firm.core.roster import RoleSpec
from investment_firm.core.tools.base import ToolError, ToolRegistry
from investment_firm.core.tools.openbb_datasources import (
    default_openbb_tools,
    get_cpi,
    get_options_summary,
    get_yield_curve,
)

from conftest import openai_text, openai_tool_call

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, results):
        self.results = results


class _Row:
    """Minimal stand-in for an OpenBB pydantic result row."""

    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self):
        return dict(self._fields)


def _spec(name: str = "rates_analyst", model: str = "gpt-4o-mini") -> RoleSpec:
    return RoleSpec(
        name=name,
        group="research",
        tier="WORKER",
        model=model,
        mandate="Test mandate.",
    )


def _clean_json() -> str:
    return json.dumps(
        {
            "stance": "NEUTRAL",
            "conviction": 3,
            "rationale": "Curve is flat.",
            "key_risks": ["inflation"],
            "evidence": ["fed: 10y at 4.1%"],
        }
    )


def _obb_with_treasury(rows):
    return SimpleNamespace(
        fixedincome=SimpleNamespace(
            government=SimpleNamespace(treasury_rates=lambda **kw: _Result(rows))
        )
    )


def _obb_with_chains(results):
    return SimpleNamespace(
        derivatives=SimpleNamespace(
            options=SimpleNamespace(chains=lambda **kw: _Result(results))
        )
    )


def _obb_with_cpi(rows):
    return SimpleNamespace(economy=SimpleNamespace(cpi=lambda **kw: _Result(rows)))


# ---------------------------------------------------------------------------
# Factory gating
# ---------------------------------------------------------------------------


class TestFactoryGating:
    def test_empty_when_openbb_missing(self, monkeypatch):
        monkeypatch.setattr(obbds, "_openbb_available", lambda: False)
        assert default_openbb_tools() == []

    def test_tools_when_openbb_available(self, monkeypatch):
        monkeypatch.setattr(obbds, "_openbb_available", lambda: True)
        names = [t.name for t in default_openbb_tools()]
        assert names == ["get_yield_curve", "get_options_summary", "get_cpi"]


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    def _schemas(self, monkeypatch):
        monkeypatch.setattr(obbds, "_openbb_available", lambda: True)
        return {t.name: t.schema() for t in default_openbb_tools()}

    def test_openai_function_format(self, monkeypatch):
        for schema in self._schemas(monkeypatch).values():
            assert schema["type"] == "function"
            assert schema["function"]["parameters"]["type"] == "object"
            assert schema["function"]["description"]

    def test_options_requires_ticker(self, monkeypatch):
        schema = self._schemas(monkeypatch)["get_options_summary"]
        assert schema["function"]["parameters"]["required"] == ["ticker"]


# ---------------------------------------------------------------------------
# get_yield_curve
# ---------------------------------------------------------------------------


class TestYieldCurve:
    def test_provenance_and_curve(self, monkeypatch):
        # Provider returns decimal fractions (0.041 = 4.1%).
        rows = [
            _Row(date=date(2026, 7, 2), month_3=0.045, year_10=0.040, year_30=None),
            _Row(date=date(2026, 7, 3), month_3=0.0455, year_10=0.041, year_30=None),
        ]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_treasury(rows))
        out = get_yield_curve()
        assert out["as_of"] == "2026-07-03"
        assert "Federal Reserve" in out["source"]
        assert out["curve_pct"] == {"month_3": 4.55, "year_10": 4.1}
        assert out["n_maturities"] == 2

    def test_empty_results_raises(self, monkeypatch):
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_treasury([]))
        with pytest.raises(ToolError):
            get_yield_curve()


# ---------------------------------------------------------------------------
# get_options_summary
# ---------------------------------------------------------------------------


def _contract(option_type, strike, volume, oi, iv, expiration=date(2026, 7, 17)):
    return dict(
        option_type=option_type,
        strike=strike,
        volume=volume,
        open_interest=oi,
        implied_volatility=iv,
        expiration=expiration,
        underlying_price=100.0,
    )


class TestOptionsSummary:
    _ROWS = [
        _contract("call", 100.0, 100, 500, 0.25),
        _contract("put", 100.0, 50, 300, 0.27),
        _contract("call", 110.0, 10, 200, 0.30),
        _contract("put", 90.0, 40, 100, 0.35, expiration=date(2026, 8, 21)),
    ]

    def _check(self, out):
        assert out["ticker"] == "AAPL"
        assert out["underlying_price"] == 100.0
        assert out["n_contracts"] == 4
        assert out["n_expirations"] == 2
        assert out["nearest_expiry"] == "2026-07-17"
        # puts 50+40=90, calls 100+10=110
        assert out["put_call_volume_ratio"] == round(90 / 110, 3)
        assert out["total_open_interest"] == 1100
        # nearest expiry, strike closest to 100 → mean(0.25, 0.27) * 100
        assert out["atm_implied_vol_pct"] == 26.0
        assert out["source"] == "OpenBB / Cboe (options chains)"
        assert "as_of" in out

    def test_list_of_rows_shape(self, monkeypatch):
        rows = [_Row(**c) for c in self._ROWS]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_chains(rows))
        self._check(get_options_summary("aapl"))

    def test_columnar_shape(self, monkeypatch):
        cols = {k: [c[k] for c in self._ROWS] for k in self._ROWS[0]}
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_chains(_Row(**cols)))
        self._check(get_options_summary("aapl"))

    def test_dump_list_shape(self, monkeypatch):
        # Cboe's CboeOptionsChainsData: one model whose model_dump() is a row list.
        class _RowsModel:
            def model_dump(self):
                return [dict(c) for c in TestOptionsSummary._ROWS]

        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_chains(_RowsModel()))
        self._check(get_options_summary("aapl"))

    def test_expired_contracts_excluded(self, monkeypatch):
        rows = [_Row(**c) for c in self._ROWS] + [
            _Row(**_contract("call", 100.0, 9999, 9999, 0.5), dte=-3)
        ]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_chains(rows))
        self._check(get_options_summary("aapl"))

    def test_zero_call_volume_gives_null_ratio(self, monkeypatch):
        rows = [_Row(**_contract("put", 100.0, 50, 300, 0.27))]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_chains(rows))
        assert get_options_summary("AAPL")["put_call_volume_ratio"] is None

    def test_zero_iv_treated_as_missing(self, monkeypatch):
        rows = [_Row(**_contract("call", 100.0, 10, 10, 0.0))]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_chains(rows))
        assert get_options_summary("AAPL")["atm_implied_vol_pct"] is None


# ---------------------------------------------------------------------------
# get_cpi
# ---------------------------------------------------------------------------


class TestCpi:
    def test_provenance_and_value(self, monkeypatch):
        # Provider returns decimal fractions (0.031 = 3.1%).
        rows = [
            _Row(date=date(2026, 4, 30), country="united_states", value=0.029),
            _Row(date=date(2026, 5, 31), country="united_states", value=0.031),
        ]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_cpi(rows))
        out = get_cpi()
        assert out["cpi_yoy_pct"] == 3.1
        assert out["country"] == "united_states"
        assert out["as_of"] == "2026-05-31"
        assert "OECD" in out["source"]

    def test_empty_results_raises(self, monkeypatch):
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_cpi([]))
        with pytest.raises(ToolError):
            get_cpi("narnia")


# ---------------------------------------------------------------------------
# Dispatch error envelopes (openbb missing at call time)
# ---------------------------------------------------------------------------


class TestDispatchEnvelope:
    def test_missing_openbb_returns_error_envelope(self, monkeypatch):
        monkeypatch.setattr(obbds, "_openbb_available", lambda: True)

        def _raise():
            raise ToolError(
                "provider 'openbb' not installed; run: pip install -e \".[openbb]\""
            )

        monkeypatch.setattr(obbds, "_get_obb", _raise)
        registry = ToolRegistry(default_openbb_tools())
        result = json.loads(registry.dispatch("get_yield_curve", {}))
        assert "error" in result
        assert "openbb" in result["error"]

    def test_bad_args_returns_error_envelope(self, monkeypatch):
        monkeypatch.setattr(obbds, "_openbb_available", lambda: True)
        registry = ToolRegistry(default_openbb_tools())
        result = json.loads(registry.dispatch("get_options_summary", "{not json"))
        assert "error" in result


# ---------------------------------------------------------------------------
# Agent loop integration (FakeLLM, offline)
# ---------------------------------------------------------------------------


class TestAgentLoop:
    def test_yield_curve_call_grounds_view(self, fake_llm, monkeypatch):
        monkeypatch.setattr(obbds, "_openbb_available", lambda: True)
        rows = [_Row(date=date(2026, 7, 3), year_10=0.041)]
        monkeypatch.setattr(obbds, "_get_obb", lambda: _obb_with_treasury(rows))
        fake_llm(
            [
                openai_tool_call("get_yield_curve", {}),
                openai_text(_clean_json()),
            ]
        )
        agent = Agent(_spec(), tools=ToolRegistry(default_openbb_tools()), max_steps=3)
        view = agent.run("Where are US rates headed?")
        assert view.grounded is True
        assert view.stance == "NEUTRAL"
