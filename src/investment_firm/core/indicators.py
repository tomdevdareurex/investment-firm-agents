"""Shared technical-indicator engine (stockstats).

One source of truth for BOTH the web chart overlays and the agent
``get_indicators`` tool, so a value an analyst cites always matches the value
plotted on the chart (mirrors TradingAgents' "verified snapshot" idea).

Network-free by design: every function takes an OHLCV ``pandas`` DataFrame with
``Open/High/Low/Close/Volume`` columns (a ``Date`` column is used for ``as_of``
when present). Fetching lives in the callers — the web ``market_data`` layer and
the ``get_indicators`` tool — not here.

Indicator names are validated against :data:`INDICATORS` before touching
stockstats, so the model (or a chart query) can never trigger arbitrary
attribute access on the underlying frame.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Union

# Curated catalog: stockstats-resolvable name -> human description. Doubles as
# the whitelist. Descriptions are shown to the model in the tool schema.
INDICATORS: Dict[str, str] = {
    "close_10_ema": "10-period EMA — short-term trend and responsiveness.",
    "close_50_sma": "50-period SMA — medium-term trend confirmation.",
    "close_200_sma": "200-period SMA — long-term regime check.",
    "macd": "MACD line — momentum direction.",
    "macds": "MACD signal line — crossover status.",
    "macdh": "MACD histogram — momentum strength.",
    "rsi": "RSI (14) — momentum breadth without being extreme.",
    "boll": "Bollinger middle band (20 SMA) — range center.",
    "boll_ub": "Bollinger upper band — stretch / breakout reference.",
    "boll_lb": "Bollinger lower band — stretch / support reference.",
    "atr": "ATR (14) — volatility and position-sizing context.",
    "vwma": "Volume-weighted moving average — volume-aware trend.",
    "mfi": "Money Flow Index — volume-weighted momentum.",
}

_ROUND_DP = 6

Names = Union[str, Sequence[str]]


class IndicatorError(ValueError):
    """Raised for unknown indicators or uncomputable input."""


def available_indicators() -> Dict[str, str]:
    """Return a copy of the indicator catalog (name -> description)."""
    return dict(INDICATORS)


def _validate(names: Names) -> List[str]:
    """Normalise, whitelist, and de-duplicate requested indicator names."""
    if isinstance(names, str):
        raw = names.split(",")
    else:
        raw = list(names)
    cleaned: List[str] = []
    for item in raw:
        text = str(item).strip().lower()
        if text and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        raise IndicatorError("no indicators requested")
    unknown = [n for n in cleaned if n not in INDICATORS]
    if unknown:
        raise IndicatorError(
            f"unknown indicator(s): {', '.join(unknown)}; "
            f"valid: {', '.join(sorted(INDICATORS))}"
        )
    return cleaned


def _is_missing(value: object) -> bool:
    """True for NaN / None / non-finite values that should render as a gap."""
    if value is None:
        return True
    try:
        return math.isnan(float(value)) or math.isinf(float(value))
    except (TypeError, ValueError):
        return True


def _wrap(df):
    """Return a stockstats-wrapped copy of ``df`` or raise :class:`IndicatorError`."""
    try:
        from stockstats import wrap  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without extras
        raise IndicatorError(
            'stockstats not installed; run: pip install -e ".[data]"'
        ) from exc
    if df is None or getattr(df, "empty", True):
        raise IndicatorError("no OHLCV rows to compute indicators from")
    if "Close" not in df.columns and "close" not in df.columns:
        raise IndicatorError("OHLCV frame is missing a Close column")
    # Copy so we never mutate the caller's frame (stockstats retypes columns).
    return wrap(df.copy())


def compute(df, names: Names) -> Dict[str, List[Optional[float]]]:
    """Return full-length indicator series aligned to ``df`` rows.

    Each value is rounded; NaN / non-finite entries become ``None`` (a chart
    gap). The list length equals ``len(df)`` so callers can zip it with their
    existing OHLC/time arrays.
    """
    cols = _validate(names)
    sdf = _wrap(df)
    result: Dict[str, List[Optional[float]]] = {}
    for name in cols:
        try:
            series = sdf[name]
        except Exception as exc:  # noqa: BLE001 - surface as a clean indicator error
            raise IndicatorError(f"could not compute {name!r}: {exc}") from exc
        result[name] = [
            None if _is_missing(v) else round(float(v), _ROUND_DP) for v in series
        ]
    return result


def _last_date(df) -> Optional[str]:
    """Best-effort ``YYYY-MM-DD`` of the last row (Date column or DatetimeIndex)."""
    try:
        import pandas as pd  # type: ignore
    except ImportError:  # pragma: no cover
        return None
    if "Date" in df.columns:
        parsed = pd.to_datetime(df["Date"], errors="coerce").dropna()
        if not parsed.empty:
            return parsed.iloc[-1].strftime("%Y-%m-%d")
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index):
        return df.index[-1].strftime("%Y-%m-%d")
    return None


def latest_snapshot(df, names: Names) -> Dict[str, object]:
    """Return the latest value per indicator plus an ``as_of`` date.

    The returned values are the last element of :func:`compute`, so a chart
    overlay built from ``compute`` and this snapshot are guaranteed to agree.
    """
    series = compute(df, names)
    indicators = {name: (vals[-1] if vals else None) for name, vals in series.items()}
    return {"indicators": indicators, "as_of": _last_date(df)}


def overlay_series(
    df, names: Names, times: Sequence
) -> Dict[str, List[Dict[str, object]]]:
    """Return chart-ready ``{time, value}`` points per indicator.

    ``times`` must align 1:1 with ``df`` rows (e.g. the chart's OHLC time axis).
    Gap values (``None``) are dropped so line series stay continuous.
    """
    series = compute(df, names)
    times = list(times)
    overlays: Dict[str, List[Dict[str, object]]] = {}
    for name, values in series.items():
        points: List[Dict[str, object]] = []
        for time_value, value in zip(times, values):
            if value is not None:
                points.append({"time": time_value, "value": value})
        overlays[name] = points
    return overlays
