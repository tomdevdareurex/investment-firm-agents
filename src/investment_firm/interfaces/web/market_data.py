"""Market-data fetch and cache helpers for the web UI.

This module is intentionally separate from the agent tools. The web UI needs
chart-ready time series and cache metadata; the LLM tools should keep returning
small, provenance-tagged summaries unless a richer evidence contract is added.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

_CACHE_SCHEMA_VERSION = 1
_DEFAULT_CACHE_TTL_SECONDS = 900
_MAX_CACHE_TTL_SECONDS = 86_400
_TICKER_RE = re.compile(r"^[A-Za-z0-9.^=_-]{1,24}$")
_VALID_PERIODS = {
    "1d",
    "5d",
    "1mo",
    "3mo",
    "6mo",
    "1y",
    "2y",
    "5y",
    "10y",
    "ytd",
    "max",
}
_VALID_INTERVALS = {"1d", "1wk", "1mo"}


class MarketDataError(Exception):
    """Base error for market-data operations."""


class MarketDataProviderError(MarketDataError):
    """Raised when an upstream data provider cannot return usable data."""


class MarketDataValidationError(MarketDataError):
    """Raised when requested market-data parameters are invalid."""


@dataclass(frozen=True)
class CacheRecord:
    """A cached market-data payload with freshness metadata."""

    payload: Dict[str, Any]
    fetched_at: str
    expires_at: str
    ttl_seconds: int


def utc_now_iso() -> str:
    """Return the current UTC time as a compact ISO-8601 string."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def default_cache_path() -> Path:
    """Return the SQLite cache path, overrideable via environment."""
    configured = os.environ.get("INVESTMENT_FIRM_MARKET_CACHE")
    if configured:
        return Path(configured)
    return Path(".cache") / "investment_firm" / "market_data.sqlite"


def _resolve_verify_ssl() -> Union[bool, str]:
    """Return the TLS ``verify`` value for Yahoo Finance fetches.

    Precedence (corporate Zscaler TLS inspection needs one of these):
      1. ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE`` — path to a corporate CA bundle.
      2. ``INVESTMENT_FIRM_MARKET_VERIFY_SSL`` — ``false`` disables verification
         (explicit opt-out only), anything else keeps it on.
      3. Default: ``True`` (full verification).
    """
    for env in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        bundle = os.environ.get(env, "").strip()
        if bundle:
            return bundle
    raw = os.environ.get("INVESTMENT_FIRM_MARKET_VERIFY_SSL", "").strip().lower()
    if raw in {"false", "0", "no", "off"}:
        return False
    return True


def _build_yfinance_session() -> Optional[Any]:
    """Return a curl_cffi session honouring the resolved TLS setting, or ``None``.

    ``None`` means "let yfinance use its default transport" — used when full
    verification applies or when curl_cffi is unavailable.
    """
    verify = _resolve_verify_ssl()
    if verify is True:
        return None
    try:
        from curl_cffi import requests as curl_requests  # type: ignore
    except ImportError:
        return None
    return curl_requests.Session(impersonate="chrome", verify=verify)


def fetch_yfinance_price_history(
    ticker: str, period: str, interval: str
) -> Dict[str, Any]:
    """Fetch chart-ready OHLC and volume data from Yahoo Finance via yfinance.

    Args:
        ticker: Yahoo Finance ticker symbol, e.g. ``"AAPL"``.
        period: yfinance lookback period, e.g. ``"5d"`` or ``"1y"``.
        interval: yfinance interval, currently intended for daily-or-slower bars.

    Returns:
        Dict containing Lightweight-Charts-ready ``ohlc`` and ``volume`` arrays.

    Raises:
        MarketDataProviderError: If yfinance is missing or returns no usable rows.
    """
    try:
        importlib.import_module("yfinance")
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover - only exercised without extras
        raise MarketDataProviderError(
            "provider 'yfinance' not installed; run: "
            '.venv\\Scripts\\python.exe -m pip install -e ".[data,api]"'
        ) from exc

    try:
        session = _build_yfinance_session()
        ticker_obj = (
            yf.Ticker(ticker, session=session)
            if session is not None
            else yf.Ticker(ticker)
        )
        hist = ticker_obj.history(
            period=period,
            interval=interval,
            auto_adjust=False,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        raise MarketDataProviderError(
            f"Yahoo Finance fetch failed ({type(exc).__name__})"
        ) from exc

    if hist is None or hist.empty:
        raise MarketDataProviderError("no price history returned")

    ohlc = []
    volume = []
    for index_value, row in hist.iterrows():
        time_label = _time_label(index_value)
        open_price = _finite_float(row.get("Open"))
        high_price = _finite_float(row.get("High"))
        low_price = _finite_float(row.get("Low"))
        close_price = _finite_float(row.get("Close"))
        if None in (open_price, high_price, low_price, close_price):
            continue

        ohlc.append(
            {
                "time": time_label,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
            }
        )
        volume.append({"time": time_label, "value": _volume_value(row.get("Volume"))})

    if not ohlc:
        raise MarketDataProviderError("no usable OHLC rows returned")

    return {
        "provider": "yfinance",
        "ticker": ticker.upper(),
        "period": period,
        "interval": interval,
        "source": "yfinance (Yahoo Finance)",
        "as_of": ohlc[-1]["time"],
        "ohlc": ohlc,
        "volume": volume,
    }


def get_price_history(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    *,
    cache_enabled: bool = True,
    force_refresh: bool = False,
    ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS,
    cache_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return chart-ready price history, using the SQLite cache when allowed.

    Args:
        ticker: Yahoo Finance ticker symbol.
        period: yfinance lookback period.
        interval: yfinance bar interval.
        cache_enabled: Whether to read/write the saved response cache.
        force_refresh: If true, bypass any saved cache entry and fetch again.
        ttl_seconds: Freshness window for cache hits.
        cache_path: Optional explicit SQLite cache path for tests or operators.

    Returns:
        Dict with provider data plus a ``cache`` metadata block.

    Raises:
        MarketDataValidationError: If TTL is invalid.
        MarketDataProviderError: If provider data cannot be fetched.
    """
    normalized_ticker = ticker.strip().upper()
    normalized_period = period.strip()
    normalized_interval = interval.strip()
    _validate_price_history_params(
        normalized_ticker,
        normalized_period,
        normalized_interval,
        ttl_seconds,
    )
    params = {
        "ticker": normalized_ticker,
        "period": normalized_period,
        "interval": normalized_interval,
    }
    cache_key = _cache_key("yfinance", "price-history", params)
    resolved_cache_path = cache_path or default_cache_path()

    if cache_enabled and not force_refresh:
        cached = read_cache(resolved_cache_path, cache_key, ttl_seconds=ttl_seconds)
        if cached is not None:
            return _with_cache_metadata(
                cached.payload,
                enabled=True,
                hit=True,
                stored=True,
                ttl_seconds=cached.ttl_seconds,
                fetched_at=cached.fetched_at,
                expires_at=cached.expires_at,
            )

    fetched_at_epoch = time.time()
    fetched_at = _epoch_to_iso(fetched_at_epoch)
    expires_at_epoch = fetched_at_epoch + ttl_seconds
    expires_at = _epoch_to_iso(expires_at_epoch)
    payload = fetch_yfinance_price_history(
        normalized_ticker,
        normalized_period,
        normalized_interval,
    )

    stored = False
    if cache_enabled:
        stored = write_cache(
            resolved_cache_path,
            cache_key,
            provider="yfinance",
            dataset="price-history",
            params=params,
            payload=payload,
            fetched_at=fetched_at,
            fetched_at_epoch=fetched_at_epoch,
            expires_at=expires_at,
            expires_at_epoch=expires_at_epoch,
            ttl_seconds=ttl_seconds,
        )

    return _with_cache_metadata(
        payload,
        enabled=cache_enabled,
        hit=False,
        stored=stored,
        ttl_seconds=ttl_seconds,
        fetched_at=fetched_at,
        expires_at=expires_at,
    )


def attach_indicators(payload: Dict[str, Any], names: Any) -> Dict[str, Any]:
    """Return a copy of ``payload`` with chart-ready indicator overlays attached.

    Uses the shared :mod:`investment_firm.core.indicators` engine on the payload's
    own OHLC rows, so the overlay values match exactly what the ``get_indicators``
    agent tool reports for the same bars. ``names`` is a comma-separated string or
    a sequence of catalog indicator names (assumed already validated by the route).

    The overlays are computed post-cache and are NOT persisted with the base OHLC
    cache entry, so the indicator selection can vary per request cheaply.
    """
    if not names:
        return payload
    ohlc = payload.get("ohlc") or []
    if not ohlc:
        return payload

    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - only without the data extra
        raise MarketDataProviderError(
            "indicator overlays require pandas; run: "
            '.venv\\Scripts\\python.exe -m pip install -e ".[data,api]"'
        ) from exc

    from ...core.indicators import IndicatorError, overlay_series

    times = [row["time"] for row in ohlc]
    volume_by_time = {v["time"]: v.get("value", 0) for v in payload.get("volume", [])}
    frame = pd.DataFrame(
        {
            "Date": times,
            "Open": [row["open"] for row in ohlc],
            "High": [row["high"] for row in ohlc],
            "Low": [row["low"] for row in ohlc],
            "Close": [row["close"] for row in ohlc],
            "Volume": [volume_by_time.get(t, 0) for t in times],
        }
    )
    try:
        overlays = overlay_series(frame, names, times)
    except IndicatorError as exc:
        raise MarketDataValidationError(str(exc)) from exc

    result = dict(payload)
    result["indicators"] = overlays
    return result


def attach_technicals(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``payload`` with a technical-summary block attached.

    Computes the investing.com-style gauge rows from the payload's own OHLC bars
    via :func:`investment_firm.core.technicals.technical_summary`, so no extra
    network fetch happens. If there is too little history (or pandas is missing),
    the summary is simply omitted rather than failing the whole chart request.
    """
    ohlc = payload.get("ohlc") or []
    if not ohlc:
        return payload

    from ...core.technicals import TechnicalsError, technical_summary

    try:
        summary = technical_summary(ohlc)
    except TechnicalsError:
        return payload

    result = dict(payload)
    result["technicals"] = summary
    return result


def read_cache(
    cache_path: Path, cache_key: str, *, ttl_seconds: int
) -> Optional[CacheRecord]:
    """Read a non-expired cache record, returning ``None`` on miss/corruption."""
    if not cache_path.exists():
        return None

    try:
        with sqlite3.connect(str(cache_path)) as conn:
            _ensure_cache_table(conn)
            row = conn.execute(
                """
                SELECT payload_json, fetched_at, fetched_at_epoch
                FROM market_data_cache
                WHERE cache_key = ? AND schema_version = ?
                """,
                (cache_key, _CACHE_SCHEMA_VERSION),
            ).fetchone()
    except sqlite3.Error:
        return None

    if row is None:
        return None

    payload_json, fetched_at, fetched_at_epoch = row
    try:
        fetched_at_epoch_float = float(fetched_at_epoch)
    except (TypeError, ValueError):
        return None

    expires_at_epoch = fetched_at_epoch_float + ttl_seconds
    if ttl_seconds == 0 or expires_at_epoch <= time.time():
        return None

    try:
        payload = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    if not _is_valid_price_history_payload(payload):
        return None

    return CacheRecord(
        payload=payload,
        fetched_at=str(fetched_at),
        expires_at=_epoch_to_iso(expires_at_epoch),
        ttl_seconds=ttl_seconds,
    )


def write_cache(
    cache_path: Path,
    cache_key: str,
    *,
    provider: str,
    dataset: str,
    params: Dict[str, Any],
    payload: Dict[str, Any],
    fetched_at: str,
    fetched_at_epoch: float,
    expires_at: str,
    expires_at_epoch: float,
    ttl_seconds: int,
) -> bool:
    """Persist a market-data response, returning whether the write succeeded."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(cache_path)) as conn:
            _ensure_cache_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO market_data_cache (
                    cache_key,
                    provider,
                    dataset,
                    params_json,
                    payload_json,
                    fetched_at,
                    fetched_at_epoch,
                    expires_at,
                    expires_at_epoch,
                    ttl_seconds,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    provider,
                    dataset,
                    _json_dumps(params),
                    _json_dumps(payload),
                    fetched_at,
                    fetched_at_epoch,
                    expires_at,
                    expires_at_epoch,
                    ttl_seconds,
                    _CACHE_SCHEMA_VERSION,
                ),
            )
            conn.commit()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False
    return True


def _ensure_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_data_cache (
            cache_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            dataset TEXT NOT NULL,
            params_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            fetched_at_epoch REAL NOT NULL,
            expires_at TEXT NOT NULL,
            expires_at_epoch REAL NOT NULL,
            ttl_seconds INTEGER NOT NULL,
            schema_version INTEGER NOT NULL
        )
        """)
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(market_data_cache)").fetchall()
    }
    if "fetched_at_epoch" not in columns:
        conn.execute("ALTER TABLE market_data_cache ADD COLUMN fetched_at_epoch REAL")


def _validate_price_history_params(
    ticker: str,
    period: str,
    interval: str,
    ttl_seconds: int,
) -> None:
    if not _TICKER_RE.fullmatch(ticker):
        raise MarketDataValidationError(
            "ticker must be 1-24 safe Yahoo Finance characters"
        )
    if period not in _VALID_PERIODS:
        raise MarketDataValidationError("period is not supported")
    if interval not in _VALID_INTERVALS:
        raise MarketDataValidationError("interval is not supported")
    if ttl_seconds < 0:
        raise MarketDataValidationError("ttl_seconds must be non-negative")
    if ttl_seconds > _MAX_CACHE_TTL_SECONDS:
        raise MarketDataValidationError("ttl_seconds must be at most 86400")


def _is_valid_price_history_payload(payload: Dict[str, Any]) -> bool:
    ohlc = payload.get("ohlc")
    volume = payload.get("volume")
    if not isinstance(ohlc, list) or not ohlc:
        return False
    if not isinstance(volume, list):
        return False
    return all(_is_valid_ohlc_bar(bar) for bar in ohlc) and all(
        _is_valid_volume_bar(bar) for bar in volume
    )


def _is_valid_ohlc_bar(bar: object) -> bool:
    if not isinstance(bar, dict):
        return False
    if not isinstance(bar.get("time"), str):
        return False
    return all(
        _finite_float(bar.get(name)) is not None
        for name in ("open", "high", "low", "close")
    )


def _is_valid_volume_bar(bar: object) -> bool:
    if not isinstance(bar, dict):
        return False
    if not isinstance(bar.get("time"), str):
        return False
    return _finite_float(bar.get("value")) is not None


def _with_cache_metadata(
    payload: Dict[str, Any],
    *,
    enabled: bool,
    hit: bool,
    stored: bool,
    ttl_seconds: int,
    fetched_at: str,
    expires_at: str,
) -> Dict[str, Any]:
    response = copy.deepcopy(payload)
    response["cache"] = {
        "enabled": enabled,
        "hit": hit,
        "stored": stored,
        "ttl_seconds": ttl_seconds,
        "fetched_at": fetched_at,
        "expires_at": expires_at,
    }
    return response


def _cache_key(provider: str, dataset: str, params: Dict[str, Any]) -> str:
    raw = _json_dumps(
        {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "provider": provider,
            "dataset": dataset,
            "params": params,
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _epoch_to_iso(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _time_label(index_value: object) -> str:
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()  # type: ignore[union-attr]
    text = str(index_value)
    return text[:10]


def _finite_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 6)


def _volume_value(value: object) -> int:
    number = _finite_float(value)
    if number is None:
        return 0
    return int(number)
