"""Technical-analysis summary gauges (network-free, self-contained).

Builds an investing.com-style "technical summary" for a price series: one row
per indicator, each rendered as a five-zone horizontal gauge (Strong Sell →
Strong Buy for directional indicators, or a non-directional intensity scale for
trend strength / volatility).

Design notes
------------
* Pure compute: takes the chart's own OHLC rows (``time/open/high/low/close``)
  so the summary never triggers a second network fetch — the caller passes the
  already-fetched, cached bars.
* Indicator math uses standard textbook formulas (Wilder RSI/ATR/ADX, %K, %R,
  CCI, MACD, ROC) computed here rather than through stockstats, so the gauge
  orientation (which end is "sell") is explicit and testable, and never depends
  on a third-party library's sign convention.
* Decision-support only: these are descriptive gauges, not trade signals or
  orders. Directional indicators show a *lean*; ADX shows trend strength and ATR
  shows volatility — neither says buy or sell.

The heavy lifting (marker position, zone boundaries, number formatting) happens
here so the browser only has to draw rectangles and labels.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Directional five-zone scale: left = Strong Sell (red), middle = Neutral
# (grey), right = Strong Buy (green).
_DIR_LABELS = ["Strong Sell", "Sell", "Neutral", "Buy", "Strong Buy"]
_DIR_CLASSES = ["strong-sell", "sell", "neutral", "buy", "strong-buy"]

# Trend-strength scale (ADX) — intensity, not direction.
_TREND_LABELS = ["No Trend", "Weak", "Strong", "Very Strong", "Extreme"]
_TREND_CLASSES = ["strength-0", "strength-1", "strength-2", "strength-3", "strength-4"]

# Volatility scale (ATR) — intensity, not direction.
_VOL_LABELS = ["Very Low", "Low", "Normal", "High", "Very High"]
_VOL_CLASSES = ["vol-0", "vol-1", "vol-2", "vol-3", "vol-4"]

# (value, pct) control points per indicator, monotonic in pct (0..100). The four
# interior points sit at 20/40/60/80% and become the visible threshold ticks.
_CONTROL: Dict[str, List[Tuple[float, float]]] = {
    # Momentum oscillators where a HIGH reading = overbought = sell lean, so the
    # value axis runs high→low as the bar runs left(sell)→right(buy).
    "rsi": [(100, 0), (80, 20), (70, 40), (30, 60), (20, 80), (0, 100)],
    "stoch": [(100, 0), (90, 20), (80, 40), (20, 60), (10, 80), (0, 100)],
    "wr": [(0, 0), (-10, 20), (-20, 40), (-80, 60), (-90, 80), (-100, 100)],
    # Indicators where a HIGH reading = bullish, so the value axis runs low→high.
    "cci": [(-300, 0), (-200, 20), (-100, 40), (100, 60), (200, 80), (300, 100)],
    "roc": [(-15, 0), (-10, 20), (-3, 40), (3, 60), (10, 80), (15, 100)],
    # Trend strength (ADX) and volatility (% of price) — non-directional.
    "adx": [(0, 0), (20, 20), (25, 40), (40, 60), (60, 80), (75, 100)],
    "atr": [(0, 0), (1, 20), (2, 40), (3, 60), (5, 80), (6, 100)],
    # MACD histogram control points are built per-call (self-scaled to its own
    # recent range) because it lives in price units, not a fixed 0..100 band.
}


class TechnicalsError(ValueError):
    """Raised when a technical summary cannot be built from the given input."""


# ── number + gauge helpers ────────────────────────────────────────────────


def format_number(value: Optional[float], decimals: int = 2) -> str:
    """Format a number with K/M/B suffixes, e.g. ``60123`` -> ``"60.1K"``."""
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    value = float(value)
    sign = "-" if value < 0 else ""
    mag = abs(value)
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if mag >= threshold:
            return f"{sign}{mag / threshold:.{decimals}f}{suffix}"
    return f"{sign}{mag:.{decimals}f}"


def _interp_pct(value: float, control: Sequence[Tuple[float, float]]) -> float:
    """Map ``value`` to a 0..100 bar position via piecewise-linear control points.

    ``control`` is ordered by increasing pct; its value axis may run in either
    direction (ascending for bullish-high indicators, descending for
    overbought-high ones). Values outside the covered range clamp to 0 or 100.
    """
    first_v = control[0][0]
    last_v = control[-1][0]
    ascending = last_v >= first_v
    for (v0, p0), (v1, p1) in zip(control, control[1:]):
        lo, hi = (v0, v1) if v0 <= v1 else (v1, v0)
        if lo <= value <= hi:
            if v1 == v0:
                return float(p1)
            frac = (value - v0) / (v1 - v0)
            return float(p0 + frac * (p1 - p0))
    # Outside the covered value range — clamp to the nearest end.
    if ascending:
        return 0.0 if value < first_v else 100.0
    return 100.0 if value < last_v else 0.0


def _build_row(
    *,
    key: str,
    label: str,
    kind: str,
    value: float,
    control: Sequence[Tuple[float, float]],
    zone_labels: Sequence[str],
    zone_classes: Sequence[str],
    display: Optional[str] = None,
    marker_value: Optional[float] = None,
    tick_decimals: int = 1,
    tick_suffix: str = "",
    action_suffix: str = "",
) -> Dict[str, Any]:
    """Assemble one gauge row: headline value, marker position, ticks, zones."""
    pos = marker_value if marker_value is not None else value
    marker_pct = round(_interp_pct(pos, control), 2)
    zone_index = min(4, max(0, int(marker_pct // 20)))
    ticks = [
        {"pct": pct, "label": f"{format_number(v, tick_decimals)}{tick_suffix}"}
        for (v, pct) in control
        if 0 < pct < 100
    ]
    segments = [{"label": zone_labels[i], "class": zone_classes[i]} for i in range(5)]
    action = zone_labels[zone_index]
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "value": round(float(value), 6),
        "display": display if display is not None else format_number(value, 2),
        "action": f"{action}{action_suffix}",
        "action_class": zone_classes[zone_index],
        "marker_pct": marker_pct,
        "ticks": ticks,
        "segments": segments,
    }


# ── indicator computation (pandas) ────────────────────────────────────────


def _frame(ohlc: Sequence[Dict[str, Any]]):
    """Return a pandas DataFrame of finite OHLC rows, or raise TechnicalsError."""
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - only without the data extra
        raise TechnicalsError(
            "technical summary requires pandas; run: "
            '.venv\\Scripts\\python.exe -m pip install -e ".[data,api]"'
        ) from exc
    rows = []
    for bar in ohlc or []:
        try:
            rows.append(
                {
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    if len(rows) < 20:
        raise TechnicalsError("not enough price history for a technical summary")
    return pd.DataFrame(rows)


def _last(series) -> Optional[float]:
    """Return the last finite value of a pandas Series, or ``None``."""
    for value in reversed(series.tolist()):
        try:
            fv = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            return fv
    return None


def _indicator_values(df) -> Dict[str, Optional[float]]:
    """Compute the latest value of every summary indicator from an OHLC frame."""
    high, low, close = df["high"], df["low"], df["close"]
    n = 14

    # True range + Wilder ATR (used by the ATR row and by ADX).
    prev_close = close.shift(1)
    tr = (
        (high - low)
        .to_frame("hl")
        .assign(hc=(high - prev_close).abs(), lc=(low - prev_close).abs())
        .max(axis=1)
    )
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

    # Wilder RSI(14).
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)

    # Stochastic %K(14).
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    span = (hh - ll).replace(0, float("nan"))
    stoch = 100 * (close - ll) / span

    # Williams %R(14) — range -100..0.
    williams = -100 * (hh - close) / span

    # CCI(20).
    tp = (high + low + close) / 3
    tp_sma = tp.rolling(20).mean()
    tp_md = (tp - tp_sma).abs().rolling(20).mean()
    cci = (tp - tp_sma) / (0.015 * tp_md.replace(0, float("nan")))

    # MACD(12,26,9) histogram.
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    # ADX(14).
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_adx = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_adx
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_adx
    di_sum = (plus_di + minus_di).replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

    # ROC(12) as a percentage.
    roc = 100 * (close / close.shift(12) - 1)

    last_close = _last(close)
    last_atr = _last(atr)
    atr_pct = (
        (last_atr / last_close * 100)
        if last_atr is not None and last_close not in (None, 0)
        else None
    )
    # Self-scaled MACD histogram range (recent absolute peak).
    hist_abs = macd_hist.abs().tail(60).max()
    macd_scale = (
        float(hist_abs) if hist_abs and math.isfinite(float(hist_abs)) else None
    )

    return {
        "rsi": _last(rsi),
        "stoch": _last(stoch),
        "wr": _last(williams),
        "cci": _last(cci),
        "roc": _last(roc),
        "adx": _last(adx),
        "macd_hist": _last(macd_hist),
        "macd_scale": macd_scale,
        "atr": last_atr,
        "atr_pct": atr_pct,
    }


def _macd_control(scale: float) -> List[Tuple[float, float]]:
    """Symmetric self-scaled control points for the MACD histogram gauge."""
    d = scale if scale and scale > 0 else 1.0
    return [
        (-d, 0),
        (-2 * d / 3, 20),
        (-d / 3, 40),
        (d / 3, 60),
        (2 * d / 3, 80),
        (d, 100),
    ]


def technical_summary(ohlc: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the technical-summary gauge rows for a series of OHLC bars.

    Args:
        ohlc: Chart bars with ``time/open/high/low/close`` keys (the already
            fetched, cached price history — no network access happens here).

    Returns:
        ``{"rows": [...], "as_of": <last bar time>}``. Indicators without enough
        history to produce a finite value are silently omitted.

    Raises:
        TechnicalsError: If pandas is unavailable or there is too little history.
    """
    df = _frame(ohlc)
    vals = _indicator_values(df)
    as_of = ohlc[-1].get("time") if ohlc else None
    rows: List[Dict[str, Any]] = []

    def add_directional(key: str, label: str, control_key: str) -> None:
        value = vals.get(key)
        if value is None:
            return
        rows.append(
            _build_row(
                key=key,
                label=label,
                kind="momentum",
                value=value,
                control=_CONTROL[control_key],
                zone_labels=_DIR_LABELS,
                zone_classes=_DIR_CLASSES,
                display=format_number(value, 2),
            )
        )

    add_directional("rsi", "RSI(14)", "rsi")
    add_directional("stoch", "Stoch %K(14)", "stoch")
    add_directional("wr", "Williams %R(14)", "wr")
    add_directional("cci", "CCI(20)", "cci")
    add_directional("roc", "ROC(12)", "roc")

    # MACD histogram — self-scaled directional gauge.
    macd_hist = vals.get("macd_hist")
    macd_scale = vals.get("macd_scale")
    if macd_hist is not None and macd_scale is not None:
        rows.append(
            _build_row(
                key="macd",
                label="MACD(12,26)",
                kind="momentum",
                value=macd_hist,
                control=_macd_control(macd_scale),
                zone_labels=_DIR_LABELS,
                zone_classes=_DIR_CLASSES,
                display=format_number(macd_hist, 2),
            )
        )

    # ADX — trend strength (no direction).
    adx = vals.get("adx")
    if adx is not None:
        rows.append(
            _build_row(
                key="adx",
                label="ADX(14)",
                kind="trend",
                value=adx,
                control=_CONTROL["adx"],
                zone_labels=_TREND_LABELS,
                zone_classes=_TREND_CLASSES,
                display=format_number(adx, 2),
                action_suffix=" Trend",
            )
        )

    # ATR — volatility (no direction). The marker is driven by ATR as a % of
    # price so the gauge is comparable across instruments; the headline is the
    # raw ATR value.
    atr = vals.get("atr")
    atr_pct = vals.get("atr_pct")
    if atr is not None and atr_pct is not None:
        rows.append(
            _build_row(
                key="atr",
                label="ATR(14)",
                kind="volatility",
                value=atr,
                marker_value=atr_pct,
                control=_CONTROL["atr"],
                zone_labels=_VOL_LABELS,
                zone_classes=_VOL_CLASSES,
                display=format_number(atr, 2),
                tick_suffix="%",
                action_suffix=" Vol",
            )
        )

    return {"rows": rows, "as_of": as_of}
