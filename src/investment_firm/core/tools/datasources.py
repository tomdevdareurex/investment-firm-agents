"""Free, read-only data-source tools (M1.5).

Every tool returns a **provenance-tagged** dict (``source``, ``as_of``, and the value)
so the research librarian can build a sourced briefing packet. These are *read-only* —
nothing here can place an order. Providers from the optional ``.[data]`` extra are
imported lazily so the package still loads without them; a tool whose provider is missing
raises :class:`ToolError` with an install hint instead of crashing.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import List

from .base import Tool, ToolError
from ..risk import risk_summary
from ..indicators import INDICATORS, IndicatorError, latest_snapshot


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require(module: str, extra: str = "data"):
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - exercised only without extras
        raise ToolError(
            f"provider {module!r} not installed; run: " f'pip install -e ".[{extra}]"'
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


def get_worldbank_indicator(
    country: str = "EMU", indicator: str = "FP.CPI.TOTL.ZG"
) -> dict:
    """Return the latest World Bank indicator value (default: euro-area CPI inflation)."""
    requests = _require("requests")  # type: ignore
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
    resp = requests.get(url, params={"format": "json", "per_page": 5}, timeout=30)
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
        raise ToolError(
            f"EDGAR HTTP {resp.status_code} for CIK {cik_padded} / {concept}"
        )
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


# --- Technical indicators (yfinance + stockstats, shared chart engine) -----


def get_indicators(
    ticker: str,
    indicators: str = "close_50_sma,close_200_sma,rsi,macd,macds",
    period: str = "6mo",
) -> dict:
    """Return the latest technical-indicator values for ``ticker``.

    Uses Yahoo Finance OHLCV and the shared :mod:`investment_firm.core.indicators`
    engine — the exact same computation that feeds the web chart overlays, so a
    value cited here matches the value plotted on the chart. ``indicators`` is a
    comma-separated list from the supported catalog.
    """
    _require("yfinance")
    import yfinance as yf  # type: ignore

    hist = yf.Ticker(ticker).history(period=period)
    if hist is None or hist.empty:
        raise ToolError(f"no price data for {ticker!r}")
    hist = hist.reset_index()  # expose the Date column for as_of
    try:
        snap = latest_snapshot(hist, indicators)
    except IndicatorError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "ticker": ticker.upper(),
        "period": period,
        "indicators": snap["indicators"],
        "as_of": snap["as_of"] or _now_iso(),
        "source": "yfinance (Yahoo Finance) + stockstats",
    }


# --- FRED: macro time series (keyless CSV) --------------------------------


def get_fred_series(series: str = "DGS10") -> dict:
    """Return the latest observation of a FRED macro series (keyless CSV endpoint).

    Uses the public fredgraph CSV download, so no API key is required. Examples:
    ``DGS10`` (10y Treasury yield), ``CPIAUCSL`` (CPI), ``UNRATE`` (unemployment),
    ``FEDFUNDS`` (fed funds rate), ``T10Y2Y`` (10y-2y spread).
    """
    requests = _require("requests")  # type: ignore
    series_id = str(series).strip().upper()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise ToolError(f"FRED HTTP {resp.status_code} for {series_id!r}")
    rows = [r for r in resp.text.splitlines() if r.strip()]
    if len(rows) < 2:
        raise ToolError(f"no FRED observations for {series_id!r}")
    latest_date = None
    latest_value = None
    for row in rows[1:]:  # skip header
        parts = row.split(",")
        if len(parts) < 2:
            continue
        date_str, value_str = parts[0].strip(), parts[1].strip()
        if value_str in ("", "."):  # FRED marks missing values with '.'
            continue
        latest_date, latest_value = date_str, value_str
    if latest_value is None:
        raise ToolError(f"no non-missing FRED observations for {series_id!r}")
    try:
        value = float(latest_value)
    except ValueError as exc:
        raise ToolError(f"could not parse FRED value {latest_value!r}") from exc
    return {
        "series": series_id,
        "value": value,
        "observation_date": latest_date,
        "source": "FRED (Federal Reserve, fredgraph CSV — keyless)",
        "as_of": _now_iso(),
    }


# --- Polymarket: prediction-market odds (read-only, public Gamma API) ------


def _parse_json_field(value):
    """Polymarket returns some list fields as JSON-encoded strings; decode defensively."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            import json

            return json.loads(value)
        except ValueError:
            return None
    return None


def get_prediction_market_odds(query: str, limit: int = 5) -> dict:
    """Return read-only prediction-market implied odds from Polymarket's Gamma API.

    Decision-support only: this reads market-implied probabilities as a signal —
    it never places, plans, or authorizes any trade, and uses no wallet or venue
    credentials. ``query`` is a free-text market search (e.g. 'ECB rate cut 2026').
    """
    requests = _require("requests")  # type: ignore
    limit = max(1, min(int(limit), 10))
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "closed": "false",
        "limit": limit,
        "order": "volumeNum",
        "ascending": "false",
        "query": query,
    }
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise ToolError(f"Polymarket HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ToolError("Polymarket returned non-JSON") from exc
    markets_raw = payload if isinstance(payload, list) else (payload.get("data") or [])
    markets = []
    for market in markets_raw[:limit]:
        if not isinstance(market, dict):
            continue
        outcomes = _parse_json_field(market.get("outcomes"))
        prices = _parse_json_field(market.get("outcomePrices"))
        odds = {}
        if isinstance(outcomes, list) and isinstance(prices, list):
            for name, price in zip(outcomes, prices):
                try:
                    odds[str(name)] = round(
                        float(price) * 100, 1
                    )  # fraction -> percent
                except (TypeError, ValueError):
                    continue
        markets.append(
            {
                "question": market.get("question") or market.get("title") or "",
                "implied_odds_pct": odds,
            }
        )
    if not markets:
        raise ToolError(f"no Polymarket markets matched {query!r}")
    return {
        "query": query,
        "markets": markets,
        "source": "Polymarket (Gamma API, read-only market-implied odds)",
        "as_of": _now_iso(),
    }


# --- StockTwits: retail sentiment (public stream) --------------------------


def get_stocktwits_sentiment(symbol: str, limit: int = 30) -> dict:
    """Return recent retail sentiment for a symbol from StockTwits' public stream.

    Counts Bullish/Bearish tags among the most recent messages (no key needed).
    Use to gauge short-term retail mood; it is noisy, so treat as a weak signal.
    """
    requests = _require("requests")  # type: ignore
    sym = str(symbol).strip().upper()
    limit = max(1, min(int(limit), 30))
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise ToolError(f"StockTwits HTTP {resp.status_code} for {sym!r}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ToolError("StockTwits returned non-JSON") from exc
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages:
        raise ToolError(f"no StockTwits messages for {sym!r}")
    messages = messages[:limit]
    bullish = bearish = 0
    for msg in messages:
        entities = msg.get("entities") if isinstance(msg, dict) else None
        sentiment = entities.get("sentiment") if isinstance(entities, dict) else None
        basic = sentiment.get("basic") if isinstance(sentiment, dict) else None
        if basic == "Bullish":
            bullish += 1
        elif basic == "Bearish":
            bearish += 1
    sample = len(messages)
    labeled = bullish + bearish
    net = "neutral"
    if bullish > bearish:
        net = "bullish"
    elif bearish > bullish:
        net = "bearish"
    return {
        "symbol": sym,
        "sample_size": sample,
        "bullish": bullish,
        "bearish": bearish,
        "unlabeled": sample - labeled,
        "net_sentiment": net,
        "source": "StockTwits (public symbol stream)",
        "as_of": _now_iso(),
    }


# --- Alpha Vantage: company fundamentals (needs ALPHA_VANTAGE_API_KEY) ------


def _av_float(data: dict, key: str):
    value = data.get(key)
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # Alpha Vantage uses 'None'/'-' sentinels that float() rejects; guard NaN too.
    return None if result != result else result


def get_av_overview(symbol: str) -> dict:
    """Return company fundamentals for a ticker from Alpha Vantage's OVERVIEW endpoint.

    Needs a free ``ALPHA_VANTAGE_API_KEY`` (25 calls/day on the free tier). Returns
    valuation (P/E, PEG, price/book), profitability (margin, EPS), size (market cap),
    and the 52-week range. Read-only fundamentals for the fundamentals analyst.
    """
    requests = _require("requests")  # type: ignore
    key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        raise ToolError(
            "ALPHA_VANTAGE_API_KEY not set; add it to .env "
            "(free key: https://www.alphavantage.co/support/#api-key)"
        )
    sym = str(symbol).strip().upper()
    resp = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "OVERVIEW", "symbol": sym, "apikey": key},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ToolError(f"Alpha Vantage HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ToolError("Alpha Vantage returned non-JSON") from exc
    if not isinstance(data, dict) or "Symbol" not in data:
        # {} for unknown symbol; {'Note'|'Information': ...} on rate-limit/plan messages.
        note = (
            (data.get("Note") or data.get("Information"))
            if isinstance(data, dict)
            else None
        )
        raise ToolError(note or f"no Alpha Vantage overview for {sym!r}")
    dividend = _av_float(data, "DividendYield")
    margin = _av_float(data, "ProfitMargin")
    return {
        "symbol": sym,
        "name": data.get("Name"),
        "sector": data.get("Sector"),
        "pe_ratio": _av_float(data, "PERatio"),
        "peg_ratio": _av_float(data, "PEGRatio"),
        "price_to_book": _av_float(data, "PriceToBookRatio"),
        "dividend_yield_pct": (
            round(dividend * 100, 3) if dividend is not None else None
        ),
        "profit_margin_pct": round(margin * 100, 3) if margin is not None else None,
        "eps": _av_float(data, "EPS"),
        "market_cap": _av_float(data, "MarketCapitalization"),
        "week52_high": _av_float(data, "52WeekHigh"),
        "week52_low": _av_float(data, "52WeekLow"),
        "source": "Alpha Vantage (OVERVIEW)",
        "as_of": data.get("LatestQuarter") or _now_iso(),
    }


# --- Reddit: retail sentiment (OAuth app-only, read-only) ------------------

_REDDIT_TOKEN: dict = {"value": None, "expires": 0.0}
_BULL_WORDS = ("buy", "long", "bull", "calls", "moon", "breakout", "undervalued", "rip")
_BEAR_WORDS = ("sell", "short", "bear", "puts", "crash", "dump", "overvalued", "drop")


def _reddit_token(requests) -> str:
    """Return a cached Reddit app-only OAuth token (client-credentials grant)."""
    now = time.time()
    if _REDDIT_TOKEN["value"] and _REDDIT_TOKEN["expires"] > now + 30:
        return _REDDIT_TOKEN["value"]
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = (
        os.getenv("REDDIT_USER_AGENT", "").strip() or "investment-firm-agents/0.1"
    )
    if not client_id or not secret:
        raise ToolError(
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set; add them to .env "
            "(create a 'script' app at https://www.reddit.com/prefs/apps)"
        )
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ToolError(f"Reddit auth HTTP {resp.status_code}")
    token = resp.json()
    access = token.get("access_token") if isinstance(token, dict) else None
    if not access:
        raise ToolError("Reddit auth returned no access_token")
    _REDDIT_TOKEN["value"] = access
    _REDDIT_TOKEN["expires"] = now + float(token.get("expires_in", 3600) or 3600)
    return access


def get_reddit_sentiment(
    query: str, subreddit: str = "wallstreetbets", limit: int = 25
) -> dict:
    """Return recent Reddit chatter for a query in a subreddit (OAuth app-only, read-only).

    Searches recent posts and applies a naive bullish/bearish keyword tally to titles.
    This is a weak, noisy signal — treat it as colour, not evidence. Needs a Reddit
    'script' app (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET) using app-only OAuth.
    """
    requests = _require("requests")  # type: ignore
    user_agent = (
        os.getenv("REDDIT_USER_AGENT", "").strip() or "investment-firm-agents/0.1"
    )
    token = _reddit_token(requests)
    sub = str(subreddit).strip().lstrip("r/").strip("/") or "wallstreetbets"
    limit = max(1, min(int(limit), 50))
    resp = requests.get(
        f"https://oauth.reddit.com/r/{sub}/search",
        params={
            "q": query,
            "restrict_sr": "1",
            "sort": "new",
            "limit": limit,
            "t": "month",
        },
        headers={"Authorization": f"Bearer {token}", "User-Agent": user_agent},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ToolError(f"Reddit HTTP {resp.status_code} for r/{sub}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ToolError("Reddit returned non-JSON") from exc
    children = (
        (payload.get("data") or {}).get("children")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(children, list) or not children:
        raise ToolError(f"no Reddit posts for {query!r} in r/{sub}")
    posts = []
    bullish = bearish = 0
    for child in children[:limit]:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        title = str(data.get("title", ""))
        lowered = title.lower()
        if any(word in lowered for word in _BULL_WORDS):
            bullish += 1
        if any(word in lowered for word in _BEAR_WORDS):
            bearish += 1
        posts.append({"title": title[:200], "score": int(data.get("score", 0) or 0)})
    net = "neutral"
    if bullish > bearish:
        net = "bullish"
    elif bearish > bullish:
        net = "bearish"
    return {
        "query": query,
        "subreddit": sub,
        "sample_size": len(posts),
        "bullish_titles": bullish,
        "bearish_titles": bearish,
        "net_sentiment": net,
        "top_posts": sorted(posts, key=lambda p: p["score"], reverse=True)[:5],
        "source": "Reddit (OAuth app-only search; keyword heuristic — noisy)",
        "as_of": _now_iso(),
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
            "country": {
                "type": "string",
                "description": "ISO/region code, e.g. 'EMU','US'",
            },
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
            "concept": {
                "type": "string",
                "description": "us-gaap concept, e.g. 'Revenues'",
            },
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


_INDICATORS_TOOL = Tool(
    name="get_indicators",
    description=(
        "Get the latest technical-indicator values for a stock/ETF ticker "
        "(Yahoo Finance + stockstats). Same engine that draws the chart overlays, "
        "so cited values match the plotted chart. Supported indicators: "
        + ", ".join(sorted(INDICATORS))
        + ". Use to ground technical/momentum/volatility claims in real numbers."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Yahoo Finance ticker symbol, e.g. 'AAPL' or 'SPY'",
            },
            "indicators": {
                "type": "string",
                "description": (
                    "Comma-separated indicator names from the supported set, "
                    "e.g. 'close_50_sma,rsi,macd,boll_ub,atr'"
                ),
                "default": "close_50_sma,close_200_sma,rsi,macd,macds",
            },
            "period": {
                "type": "string",
                "description": "Lookback period for price history, e.g. '3mo','6mo','1y'",
                "default": "6mo",
            },
        },
        "required": ["ticker"],
    },
    func=get_indicators,
)


_FRED_TOOL = Tool(
    name="get_fred_series",
    description=(
        "Get the latest value of a FRED macro series (keyless). Examples: 'DGS10' "
        "(10y Treasury), 'CPIAUCSL' (CPI), 'UNRATE' (unemployment), 'FEDFUNDS' "
        "(fed funds), 'T10Y2Y' (10y-2y spread). Use for US macro grounding."
    ),
    parameters={
        "type": "object",
        "properties": {
            "series": {
                "type": "string",
                "description": "FRED series id, e.g. 'DGS10' or 'CPIAUCSL'",
            }
        },
    },
    func=get_fred_series,
)

_PREDICTION_MARKET_TOOL = Tool(
    name="get_prediction_market_odds",
    description=(
        "Get read-only prediction-market implied odds (percent) from Polymarket for a "
        "free-text query, e.g. 'ECB rate cut 2026'. Decision-support only — reads "
        "market-implied probabilities as a signal; never trades or uses a wallet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "free-text market search"},
            "limit": {
                "type": "integer",
                "description": "max markets to return (1-10)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    func=get_prediction_market_odds,
)

_STOCKTWITS_TOOL = Tool(
    name="get_stocktwits_sentiment",
    description=(
        "Get recent retail sentiment (Bullish/Bearish counts) for a ticker from "
        "StockTwits' public stream. Use to gauge short-term retail mood; it is noisy, "
        "so treat it as a weak signal alongside stronger evidence."
    ),
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "ticker, e.g. 'AAPL'"},
            "limit": {
                "type": "integer",
                "description": "recent messages to scan (1-30)",
                "default": 30,
            },
        },
        "required": ["symbol"],
    },
    func=get_stocktwits_sentiment,
)

_AV_OVERVIEW_TOOL = Tool(
    name="get_av_overview",
    description=(
        "Get company fundamentals (P/E, PEG, price/book, profit margin, EPS, market "
        "cap, 52-week range) for a ticker from Alpha Vantage. Use for valuation and "
        "profitability context. Requires ALPHA_VANTAGE_API_KEY (free tier)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "ticker, e.g. 'AAPL'"},
        },
        "required": ["symbol"],
    },
    func=get_av_overview,
)

_REDDIT_TOOL = Tool(
    name="get_reddit_sentiment",
    description=(
        "Get recent Reddit chatter for a query in a subreddit with a naive "
        "bullish/bearish keyword tally. Weak, noisy retail-mood signal — treat as "
        "colour, not evidence. Requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search term, e.g. 'AAPL'"},
            "subreddit": {
                "type": "string",
                "description": "subreddit to search",
                "default": "wallstreetbets",
            },
            "limit": {
                "type": "integer",
                "description": "recent posts to scan (1-50)",
                "default": 25,
            },
        },
        "required": ["query"],
    },
    func=get_reddit_sentiment,
)


def default_data_tools() -> List[Tool]:
    """Return the free read-only data tools (enabled set from firm.yaml defaults)."""
    return [
        _PRICES_TOOL,
        _INDICATORS_TOOL,
        _ECB_TOOL,
        _WORLDBANK_TOOL,
        _EDGAR_TOOL,
        _RISK_TOOL,
        _FRED_TOOL,
        _PREDICTION_MARKET_TOOL,
        _STOCKTWITS_TOOL,
        _AV_OVERVIEW_TOOL,
        _REDDIT_TOOL,
    ]
