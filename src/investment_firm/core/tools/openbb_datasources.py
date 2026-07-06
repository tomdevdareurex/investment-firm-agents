"""Optional OpenBB Platform data tools (keyless providers only).

Same contract as :mod:`datasources`: every tool returns a **provenance-tagged** dict
(``source``, ``as_of``, and the value) and is *read-only*. OpenBB is a heavy optional
dependency (``.[openbb]`` extra, AGPLv3 — treated as local/personal use here), so it is
imported lazily via :func:`_get_obb` and :func:`default_openbb_tools` returns an empty
list when it is not installed — uninstalled environments never advertise tools to the
model that can only fail.

Endpoints (all free, no API key):
  - ``get_yield_curve``      — US Treasury rates, ``federal_reserve`` provider.
  - ``get_options_summary``  — options chain summary, ``cboe`` provider (openbb-cboe).
  - ``get_cpi``              — monthly year-over-year CPI, ``oecd`` provider.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .base import Tool, ToolError
from .datasources import _now_iso, _require


def _openbb_available() -> bool:
    return importlib.util.find_spec("openbb") is not None


def _patch_static_imports() -> None:
    """Export the dynamic ``OBBject_<Model>`` classes from ``provider_interface``.

    OpenBB's static package builder emits ``from openbb_core.app.provider_interface
    import OBBject_<Model>`` because pydantic's ``create_model`` stamps that module
    onto the classes it builds — but nothing ever assigns them into the module, so
    every generated ``openbb.package.*`` module fails to import (upstream builder
    bug; observed with openbb 4.7.2 / openbb-core 1.6.13). Injecting the classes
    before ``from openbb import obb`` makes the generated imports resolve.
    """
    import openbb_core.app.provider_interface as pim  # type: ignore

    if getattr(pim, "_ifa_obbject_patch", False):
        return
    annotations = pim.ProviderInterface().return_annotations
    for name, cls in annotations.items():
        setattr(pim, f"OBBject_{name}", cls)
    pim._ifa_obbject_patch = True


def _get_obb() -> Any:
    """Lazily import and return the OpenBB entry point ``obb``."""
    _require("openbb", "openbb")
    _patch_static_imports()
    from openbb import obb  # type: ignore

    return obb


def _dump(row: Any) -> Dict[str, Any]:
    """Return a plain dict for an OpenBB result row (pydantic model or mapping)."""
    if hasattr(row, "model_dump"):
        return row.model_dump()
    return dict(row)


# --- Federal Reserve H.15: US Treasury yield curve --------------------------


def get_yield_curve() -> dict:
    """Return the latest US Treasury yield curve (percent) from the Federal Reserve.

    Uses OpenBB's ``fixedincome.government.treasury_rates`` with the keyless
    ``federal_reserve`` provider (H.15 release). The provider returns decimal
    fractions (0.0448 = 4.48%); values are converted to percent. Maturities with
    no data (e.g. discontinued tenors) are omitted.
    """
    obb = _get_obb()
    start = (date.today() - timedelta(days=30)).isoformat()
    result = obb.fixedincome.government.treasury_rates(
        start_date=start, provider="federal_reserve"
    )
    rows = list(result.results or [])
    if not rows:
        raise ToolError("no treasury rates data returned")
    latest = _dump(rows[-1])
    observed = latest.pop("date", None)
    curve = {
        k: round(float(v) * 100, 4)
        for k, v in latest.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if not curve:
        raise ToolError("could not parse treasury rates response")
    return {
        "curve_pct": curve,
        "n_maturities": len(curve),
        "source": "OpenBB / Federal Reserve H.15 (treasury_rates)",
        "as_of": str(observed) if observed else _now_iso(),
    }


# --- Cboe: options chain summary --------------------------------------------


def _option_rows(results: Any) -> List[Dict[str, Any]]:
    """Normalize OpenBB options-chains results to a list of per-contract dicts.

    Handles the shapes OpenBB has used: a list of row models, a single model whose
    ``model_dump()`` yields a list of row dicts (Cboe's ``CboeOptionsChainsData``),
    and a single columnar model whose fields are equal-length lists.
    """
    if isinstance(results, list):
        return [_dump(r) for r in results]
    data = _dump(results)
    if isinstance(data, list):
        return [dict(r) for r in data]
    lists = {k: v for k, v in data.items() if isinstance(v, list)}
    if not lists:
        raise ToolError("could not parse options chains response")
    n = max(len(v) for v in lists.values())
    cols = {k: v for k, v in lists.items() if len(v) == n}
    return [{k: cols[k][i] for k in cols} for i in range(n)]


def get_options_summary(ticker: str) -> dict:
    """Return an options-chain summary for ``ticker`` from Cboe (via OpenBB).

    Summarizes the full chain (never returned raw): put/call volume ratio, total
    open interest, nearest expiry, and ATM implied volatility (percent) at the
    strike closest to the underlying price.
    """
    obb = _get_obb()
    result = obb.derivatives.options.chains(symbol=ticker, provider="cboe")
    rows = _option_rows(result.results)
    # Cboe keeps just-expired contracts in the chain (negative days-to-expiry).
    rows = [r for r in rows if r.get("dte") is None or int(r["dte"]) >= 0]
    if not rows:
        raise ToolError(f"no options data for {ticker!r}")

    underlying = next(
        (float(r["underlying_price"]) for r in rows if r.get("underlying_price")), None
    )
    expirations = sorted({r["expiration"] for r in rows if r.get("expiration")})
    call_vol = sum(
        int(r.get("volume") or 0)
        for r in rows
        if str(r.get("option_type", "")).lower() == "call"
    )
    put_vol = sum(
        int(r.get("volume") or 0)
        for r in rows
        if str(r.get("option_type", "")).lower() == "put"
    )
    total_oi = sum(int(r.get("open_interest") or 0) for r in rows)

    atm_iv_pct: Optional[float] = None
    if underlying is not None and expirations:
        # Truthy IV filter: Cboe emits 0.0 for contracts it did not price.
        near = [
            r
            for r in rows
            if r.get("expiration") == expirations[0]
            and r.get("implied_volatility")
            and r.get("strike") is not None
        ]
        if near:
            best_strike = min(near, key=lambda r: abs(float(r["strike"]) - underlying))[
                "strike"
            ]
            ivs = [
                float(r["implied_volatility"])
                for r in near
                if r["strike"] == best_strike
            ]
            atm_iv_pct = round(sum(ivs) / len(ivs) * 100, 2)

    return {
        "ticker": ticker.upper(),
        "underlying_price": underlying,
        "n_contracts": len(rows),
        "n_expirations": len(expirations),
        "nearest_expiry": str(expirations[0]) if expirations else None,
        "put_call_volume_ratio": round(put_vol / call_vol, 3) if call_vol else None,
        "total_open_interest": total_oi,
        "atm_implied_vol_pct": atm_iv_pct,
        "source": "OpenBB / Cboe (options chains)",
        "as_of": _now_iso(),
    }


# --- OECD: monthly CPI (year-over-year) --------------------------------------


def get_cpi(country: str = "united_states") -> dict:
    """Return the latest monthly year-over-year CPI for ``country`` from the OECD.

    Fresher than the annual World Bank indicator: monthly frequency, OECD/G20
    coverage (e.g. ``"united_states"``, ``"euro_area_20"``, ``"germany"``). The
    provider returns decimal fractions (0.031 = 3.1%); converted to percent.
    """
    obb = _get_obb()
    result = obb.economy.cpi(
        country=country, transform="yoy", frequency="monthly", provider="oecd"
    )
    rows = list(result.results or [])
    if not rows:
        raise ToolError(f"no CPI data for {country!r}")
    latest = _dump(rows[-1])
    value = latest.get("value")
    if value is None:
        raise ToolError("could not parse CPI response")
    return {
        "country": str(latest.get("country") or country),
        "cpi_yoy_pct": round(float(value) * 100, 2),
        "period": str(latest.get("date", "")),
        "source": "OpenBB / OECD (consumer price index, yoy)",
        "as_of": str(latest.get("date")) if latest.get("date") else _now_iso(),
    }


# --- Registry assembly ----------------------------------------------------

_YIELD_CURVE_TOOL = Tool(
    name="get_yield_curve",
    description=(
        "Get the latest US Treasury yield curve (all maturities, in percent) from the "
        "Federal Reserve H.15 release. Use for rates term structure, duration, and "
        "macro/rates views."
    ),
    parameters={"type": "object", "properties": {}},
    func=get_yield_curve,
)

_OPTIONS_TOOL = Tool(
    name="get_options_summary",
    description=(
        "Get an options-chain summary for a stock/ETF ticker from Cboe: put/call "
        "volume ratio, total open interest, nearest expiry, and ATM implied "
        "volatility in percent. Use for positioning, sentiment, and implied-vol "
        "evidence."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "e.g. 'AAPL' or 'SPY'"},
        },
        "required": ["ticker"],
    },
    func=get_options_summary,
)

_CPI_TOOL = Tool(
    name="get_cpi",
    description=(
        "Get the latest monthly year-over-year CPI inflation (percent) for an "
        "OECD/G20 country. Monthly and fresher than the annual World Bank "
        "indicator. Country in snake_case, e.g. 'united_states', 'euro_area_20', "
        "'germany'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": "snake_case country, e.g. 'united_states'",
                "default": "united_states",
            },
        },
    },
    func=get_cpi,
)


def default_openbb_tools() -> List[Tool]:
    """Return the OpenBB-backed tools, or ``[]`` when the extra is not installed.

    Gating on availability keeps uninstalled environments from advertising tools
    to the model that could only ever fail.
    """
    if not _openbb_available():
        return []
    return [_YIELD_CURVE_TOOL, _OPTIONS_TOOL, _CPI_TOOL]
