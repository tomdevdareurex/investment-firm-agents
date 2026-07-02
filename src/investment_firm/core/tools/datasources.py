"""Free, read-only data-source tools (M1.5).

Every tool returns a **provenance-tagged** dict (``source``, ``as_of``, and the value)
so the research librarian can build a sourced briefing packet. These are *read-only* —
nothing here can place an order. Providers from the optional ``.[data]`` extra are
imported lazily so the package still loads without them; a tool whose provider is missing
raises :class:`ToolError` with an install hint instead of crashing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .base import Tool, ToolError
from ..risk import risk_summary


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require(module: str, extra: str = "data"):
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - exercised only without extras
        raise ToolError(
            f"provider {module!r} not installed; run: "
            f'pip install -e ".[{extra}]"'
        ) from exc


# --- yfinance: prices -----------------------------------------------------


def get_prices(ticker: str, period: str = "1mo") -> dict:
    """Return recent price summary for ``ticker`` from Yahoo Finance (yfinance)."""
    _require("yfinance")
    import yfinance as yf  # type: ignore

    hist = yf.Ticker(ticker).history(period=period)
    if hist is None or hist.empty:
        raise ToolError(f"no price data for {ticker!r}")
    close = hist["Close"]
    return {
        "ticker": ticker.upper(),
        "period": period,
        "last_close": round(float(close.iloc[-1]), 4),
        "first_close": round(float(close.iloc[0]), 4),
        "pct_change": round(float(close.iloc[-1] / close.iloc[0] - 1) * 100, 2),
        "points": int(len(close)),
        "source": "yfinance (Yahoo Finance)",
        "as_of": _now_iso(),
    }


# --- ECB Statistical Data Warehouse: policy rate --------------------------


def get_ecb_rate(series: str = "FM.D.U2.EUR.4F.KR.MRR_FR.LEV") -> dict:
    """Return the latest value of an ECB SDW series (default: MRO rate)."""
    requests = _require("requests")  # type: ignore
    url = f"https://data-api.ecb.europa.eu/service/data/{series}"
    resp = requests.get(
        url, params={"lastNObservations": 1, "format": "jsondata"}, timeout=30
    )
    if resp.status_code != 200:
        raise ToolError(f"ECB SDW HTTP {resp.status_code}")
    data = resp.json()
    try:
        series_block = list(data["dataSets"][0]["series"].values())[0]
        obs = series_block["observations"]
        value = list(obs.values())[0][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ToolError(f"could not parse ECB SDW response: {exc}") from exc
    return {
        "series": series,
        "value": value,
        "source": "ECB Statistical Data Warehouse",
        "as_of": _now_iso(),
    }


# --- World Bank: macro indicator ------------------------------------------


def get_worldbank_indicator(country: str = "EMU", indicator: str = "FP.CPI.TOTL.ZG") -> dict:
    """Return the latest World Bank indicator value (default: euro-area CPI inflation)."""
    requests = _require("requests")  # type: ignore
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
    resp = requests.get(
        url, params={"format": "json", "per_page": 5}, timeout=30
    )
    if resp.status_code != 200:
        raise ToolError(f"World Bank HTTP {resp.status_code}")
    payload = resp.json()
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    latest = next((r for r in rows if r.get("value") is not None), None)
    if latest is None:
        raise ToolError("no World Bank observations with a value")
    return {
        "country": country,
        "indicator": indicator,
        "value": latest.get("value"),
        "year": latest.get("date"),
        "source": "World Bank Open Data",
        "as_of": _now_iso(),
    }


# --- SEC EDGAR: company facts ---------------------------------------------


def get_company_filing(cik: str, concept: str = "Revenues") -> dict:
    """Return the latest value of an XBRL ``concept`` for a SEC ``cik`` (EDGAR).

    EDGAR requires a descriptive ``User-Agent``; we send one identifying this project.
    """
    requests = _require("requests")  # type: ignore
    cik_padded = str(cik).strip().zfill(10)
    url = (
        f"https://data.sec.gov/api/xbrl/companyconcept/"
        f"CIK{cik_padded}/us-gaap/{concept}.json"
    )
    headers = {"User-Agent": "investment-firm-agents (educational; contact: user)"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise ToolError(f"EDGAR HTTP {resp.status_code} for CIK {cik_padded} / {concept}")
    data = resp.json()
    units = data.get("units", {})
    series = next(iter(units.values()), [])
    if not series:
        raise ToolError(f"no data for concept {concept!r}")
    latest = series[-1]
    return {
        "cik": cik_padded,
        "concept": concept,
        "value": latest.get("val"),
        "fiscal_period": f"{latest.get('fy')} {latest.get('fp')}",
        "source": "SEC EDGAR (XBRL company facts)",
        "as_of": _now_iso(),
    }


# --- Risk metrics (yfinance + core/risk.py) --------------------------------


def compute_risk_metrics(ticker: str, period: str = "1y", level: float = 0.99) -> dict:
    """Compute quantitative risk metrics for ``ticker`` using yfinance closing prices.

    Fetches closing prices for the requested period, computes historical VaR,
    parametric VaR, Expected Shortfall, annualized volatility, and max drawdown
    via :func:`investment_firm.core.risk.risk_summary`.

    All VaR / ES / volatility / drawdown values are expressed as **percent** figures
    (e.g. ``2.31`` means 2.31%) with ``_pct`` key suffixes so the model cannot
    misread them as raw fractions.

    Args:
        ticker: Yahoo Finance ticker symbol, e.g. ``"AAPL"`` or ``"EUFN"``.
        period: yfinance lookback period, e.g. ``"1y"``, ``"6mo"``, ``"2y"``.
        level: VaR / ES confidence level in (0, 1).  Default 0.99 (99%).

    Returns:
        Dict with keys: ``ticker``, ``period``, ``as_of``, ``n_obs``,
        ``ann_vol_pct``, ``hist_var_1d_pct``, ``param_var_1d_pct``,
        ``es_1d_pct``, ``max_drawdown_pct``, ``var_level``, ``source``.
    """
    _require("yfinance")
    import yfinance as yf  # type: ignore

    hist = yf.Ticker(ticker).history(period=period)
    if hist is None or hist.empty:
        raise ToolError(f"no price data for {ticker!r}")

    close = hist["Close"]
    prices = list(map(float, close.tolist()))
    as_of = close.index[-1]
    try:
        as_of_iso = as_of.date().isoformat()
    except AttributeError:
        as_of_iso = str(as_of)

    summary = risk_summary(prices, level=level)

    def _pct(val: object) -> float:
        """Convert a fraction to a rounded percentage."""
        return round(float(val) * 100, 2)  # type: ignore[arg-type]

    return {
        "ticker": ticker.upper(),
        "period": period,
        "as_of": as_of_iso,
        "n_obs": summary["n_obs"],
        "ann_vol_pct": _pct(summary["ann_vol"]),
        "hist_var_1d_pct": _pct(summary["hist_var_1d"]),
        "param_var_1d_pct": _pct(summary["param_var_1d"]),
        "es_1d_pct": _pct(summary["es_1d"]),
        "max_drawdown_pct": _pct(summary["max_drawdown"]),
        "var_level": summary["var_level"],
        "source": "computed from yfinance closes (VaR/ES historical + parametric)",
    }


# --- Registry assembly ----------------------------------------------------

_PRICES_TOOL = Tool(
    name="get_prices",
    description=(
        "Get a recent price summary (last close, % change) for a stock/ETF ticker "
        "from Yahoo Finance. Use for market context."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "e.g. 'AAPL' or 'EUFN'"},
            "period": {
                "type": "string",
                "description": "lookback, e.g. '5d','1mo','6mo','1y'",
                "default": "1mo",
            },
        },
        "required": ["ticker"],
    },
    func=get_prices,
)

_ECB_TOOL = Tool(
    name="get_ecb_rate",
    description="Get the latest ECB policy/interest-rate series value (default: MRO).",
    parameters={
        "type": "object",
        "properties": {
            "series": {"type": "string", "description": "ECB SDW series key (optional)"}
        },
    },
    func=get_ecb_rate,
)

_WORLDBANK_TOOL = Tool(
    name="get_worldbank_indicator",
    description=(
        "Get the latest World Bank macro indicator (default: euro-area CPI inflation)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "country": {"type": "string", "description": "ISO/region code, e.g. 'EMU','US'"},
            "indicator": {"type": "string", "description": "World Bank indicator code"},
        },
    },
    func=get_worldbank_indicator,
)

_EDGAR_TOOL = Tool(
    name="get_company_filing",
    description=(
        "Get the latest reported value of a US-GAAP XBRL concept (e.g. 'Revenues') for "
        "a SEC company by CIK, from EDGAR."
    ),
    parameters={
        "type": "object",
        "properties": {
            "cik": {"type": "string", "description": "SEC CIK number (zero-padded ok)"},
            "concept": {"type": "string", "description": "us-gaap concept, e.g. 'Revenues'"},
        },
        "required": ["cik"],
    },
    func=get_company_filing,
)


_RISK_TOOL = Tool(
    name="compute_risk_metrics",
    description=(
        "Compute quantitative risk metrics (annualized volatility, 1-day historical VaR, "
        "parametric VaR, Expected Shortfall, and max drawdown) for a stock/ETF ticker "
        "using recent closing prices from Yahoo Finance. All values returned as percent "
        "figures (e.g. ann_vol_pct=18.5 means 18.5% annualized vol). Use to support "
        "market views with quantitative evidence."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Yahoo Finance ticker symbol, e.g. 'AAPL' or 'EUFN'",
            },
            "period": {
                "type": "string",
                "description": "Lookback period for price history, e.g. '1y', '6mo', '2y'",
                "default": "1y",
            },
            "level": {
                "type": "number",
                "description": "VaR/ES confidence level between 0 and 1 (default 0.99 = 99%)",
                "default": 0.99,
            },
        },
        "required": ["ticker"],
    },
    func=compute_risk_metrics,
)


def default_data_tools() -> List[Tool]:
    """Return the free read-only data tools (enabled set from firm.yaml defaults)."""
    return [_PRICES_TOOL, _ECB_TOOL, _WORLDBANK_TOOL, _EDGAR_TOOL, _RISK_TOOL]
