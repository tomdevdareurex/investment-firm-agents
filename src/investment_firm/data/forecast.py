"""Pure forecasting helpers shared by the TimesFM tool and the web API (stdlib only).

This module never imports torch/timesfm and never touches the network. It
provides:

* ``validate_series`` — input hygiene for a close-price series.
* ``random_walk_quantiles`` — the *baseline* cone every model forecast is shown
  against: a driftless log-normal random walk whose volatility is the sample
  standard deviation of recent log returns, scaled by ``sqrt(t)``.
* ``business_days_after`` / ``step_dates_after`` — forecast x-axis per bar
  interval (daily = Mon–Fri without an exchange-holiday calendar, weekly = +7
  days, monthly = +1 calendar month).
* ``summarize_cone`` / ``cone_payload`` — the JSON-safe dict consumed by the
  agent tool, ``GET /api/market/forecast`` and the report.

A quantile cone is a *statistical scenario band*, not a prediction. The caveat
text travels with every payload so downstream prompts and UIs repeat it.
"""

from __future__ import annotations

import datetime as _dt
import math
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

MIN_POINTS = 64
MAX_HORIZON = 60
DEFAULT_QUANTILES: Tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)
INTERVALS: Tuple[str, ...] = ("1d", "1wk", "1mo")
_REQUIRED_KEYS = ("q10", "q50", "q90")
_OPTIONAL_KEYS = ("q25", "q75")

CAVEAT = (
    "Statistical cone, not a prediction: quantile bands describe a range of "
    "plausible paths given recent volatility and carry no view on fundamentals, "
    "news or events. Compare the model cone with the random-walk baseline; when "
    "they are similar the model adds little information. Daily dates are business "
    "days (Mon-Fri) without an exchange-holiday calendar. Decision support only."
)


class ForecastError(ValueError):
    """Raised for unusable inputs (too short, non-positive, bad horizon)."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_series(
    closes: Sequence[float], min_points: int = MIN_POINTS
) -> List[float]:
    """Return ``closes`` as a list of finite positive floats or raise ``ForecastError``."""
    out: List[float] = []
    for i, raw in enumerate(closes):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ForecastError(f"close at index {i} is not numeric: {raw!r}")
        if not math.isfinite(value) or value <= 0:
            raise ForecastError(f"close at index {i} is not a positive number: {raw!r}")
        out.append(value)
    if len(out) < min_points:
        raise ForecastError(
            f"need at least {min_points} closes for a forecast; got {len(out)}"
        )
    return out


def clamp_horizon(steps: Any, upper: int = MAX_HORIZON) -> int:
    """Coerce ``steps`` to an int in ``1..upper`` or raise ``ForecastError``."""
    try:
        h = int(steps)
    except (TypeError, ValueError):
        raise ForecastError(f"horizon must be an integer number of days; got {steps!r}")
    if h < 1 or h > upper:
        raise ForecastError(f"horizon must be between 1 and {upper} days; got {h}")
    return h


# ---------------------------------------------------------------------------
# Baseline: driftless log-normal random walk
# ---------------------------------------------------------------------------


def log_return_vol(closes: Sequence[float], lookback: int = 252) -> float:
    """Sample standard deviation of daily log returns over the last ``lookback`` closes."""
    window = list(closes)[-(lookback + 1) :]
    if len(window) < 3:
        raise ForecastError("need at least 3 closes to estimate volatility")
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    vol = statistics.stdev(rets)
    if not math.isfinite(vol):
        raise ForecastError("volatility estimate is not finite")
    return vol


def random_walk_quantiles(
    closes: Sequence[float],
    steps: int,
    quantiles: Sequence[float] = DEFAULT_QUANTILES,
    lookback: int = 252,
) -> Dict[str, List[float]]:
    """Quantile paths of a driftless log-normal random walk from the last close.

    Returns ``{"q10": [...], "q50": [...], "q90": [...]}`` (keys derived from
    ``quantiles``), each of length ``steps``. The median path is flat at the last
    close; the bands widen with ``sqrt(t)``.
    """
    series = validate_series(closes, min_points=3)
    h = clamp_horizon(steps)
    for q in quantiles:
        if not 0.0 < float(q) < 1.0:
            raise ForecastError(f"quantile must lie strictly inside (0, 1); got {q}")
    last = series[-1]
    vol = log_return_vol(series, lookback=lookback)
    normal = statistics.NormalDist()
    out: Dict[str, List[float]] = {}
    for q in quantiles:
        z = normal.inv_cdf(float(q))
        out[quantile_key(q)] = [
            last * math.exp(z * vol * math.sqrt(t)) for t in range(1, h + 1)
        ]
    return out


def quantile_key(q: float) -> str:
    """``0.1 -> "q10"``, ``0.5 -> "q50"``, ``0.95 -> "q95"``."""
    return f"q{int(round(float(q) * 100))}"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def business_days_after(last_date_iso: str, steps: int) -> List[str]:
    """``steps`` ISO dates after ``last_date_iso`` skipping Saturdays and Sundays."""
    try:
        day = _dt.date.fromisoformat(str(last_date_iso)[:10])
    except ValueError:
        raise ForecastError(f"last date is not ISO yyyy-mm-dd: {last_date_iso!r}")
    h = clamp_horizon(steps)
    out: List[str] = []
    while len(out) < h:
        day += _dt.timedelta(days=1)
        if day.weekday() < 5:
            out.append(day.isoformat())
    return out


def _add_months(day: _dt.date, months: int) -> _dt.date:
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    next_month = _dt.date(year + month // 12, month % 12 + 1, 1)
    last_day = (next_month - _dt.timedelta(days=1)).day
    return _dt.date(year, month, min(day.day, last_day))


def step_dates_after(last_date_iso: str, steps: int, interval: str = "1d") -> List[str]:
    """``steps`` future bar dates for ``interval`` (``1d`` | ``1wk`` | ``1mo``)."""
    if interval == "1d":
        return business_days_after(last_date_iso, steps)
    if interval not in INTERVALS:
        raise ForecastError(f"interval must be one of {INTERVALS}; got {interval!r}")
    try:
        day = _dt.date.fromisoformat(str(last_date_iso)[:10])
    except ValueError:
        raise ForecastError(f"last date is not ISO yyyy-mm-dd: {last_date_iso!r}")
    h = clamp_horizon(steps)
    if interval == "1wk":
        return [(day + _dt.timedelta(weeks=t)).isoformat() for t in range(1, h + 1)]
    return [_add_months(day, t).isoformat() for t in range(1, h + 1)]


# ---------------------------------------------------------------------------
# Summaries / payload
# ---------------------------------------------------------------------------


def _pct(value: float, base: float) -> float:
    return round((value / base - 1.0) * 100.0, 2)


def summarize_cone(
    q10: Sequence[float],
    q50: Sequence[float],
    q90: Sequence[float],
    last_close: float,
    q25: Optional[Sequence[float]] = None,
    q75: Optional[Sequence[float]] = None,
) -> Dict[str, float]:
    """End-of-horizon moves (percent of ``last_close``) and the band width."""
    if not (len(q10) == len(q50) == len(q90)) or not q50:
        raise ForecastError("quantile paths must be non-empty and equally long")
    if last_close <= 0:
        raise ForecastError("last close must be positive")
    out = {
        "end_q10_pct": _pct(q10[-1], last_close),
        "end_q50_pct": _pct(q50[-1], last_close),
        "end_q90_pct": _pct(q90[-1], last_close),
        "width_pct": round((q90[-1] - q10[-1]) / last_close * 100.0, 2),
    }
    if q25 and q75:
        out["end_q25_pct"] = _pct(q25[-1], last_close)
        out["end_q75_pct"] = _pct(q75[-1], last_close)
    return out


def cone_payload(
    *,
    ticker: str,
    closes: Sequence[float],
    last_date_iso: str,
    horizon: int,
    model_quantiles: Optional[Dict[str, Sequence[float]]] = None,
    source: str = "random-walk baseline",
    lookback: int = 252,
    interval: str = "1d",
) -> Dict[str, Any]:
    """JSON-safe forecast cone shared by the tool, the API and the report.

    ``horizon`` counts bars of ``interval`` (days, weeks or months). Always
    carries the random-walk baseline (``baseline_q10/q25/q50/q75/q90``). When
    ``model_quantiles`` (q10/q50/q90 required, q25/q75 optional) is given, those
    paths become ``q10..q90`` and the baseline stays alongside; without a model
    the baseline is also exposed as ``q10..q90`` so consumers have one shape.
    """
    series = validate_series(closes)
    h = clamp_horizon(horizon)
    last = series[-1]
    baseline = random_walk_quantiles(series, h, lookback=lookback)
    model = {k: [float(x) for x in v] for k, v in (model_quantiles or {}).items()}
    for key in _REQUIRED_KEYS + _OPTIONAL_KEYS:
        if model and key not in model:
            if key in _OPTIONAL_KEYS:
                continue
            raise ForecastError(f"model quantiles missing {key}")
        if model and len(model[key]) != h:
            raise ForecastError(
                f"model {key} has {len(model[key])} points, expected horizon {h}"
            )
    paths = model or baseline
    payload: Dict[str, Any] = {
        "ticker": str(ticker).upper(),
        "source": source,
        "as_of": str(last_date_iso)[:10],
        "last_close": round(last, 6),
        "interval": interval,
        "horizon_days": h,
        "dates": step_dates_after(last_date_iso, h, interval),
    }
    for key in _REQUIRED_KEYS + _OPTIONAL_KEYS:
        if key in paths:
            payload[key] = [round(x, 6) for x in paths[key]]
        payload[f"baseline_{key}"] = [round(x, 6) for x in baseline[key]]
    payload.update(
        {
            "summary": summarize_cone(
                paths["q10"],
                paths["q50"],
                paths["q90"],
                last,
                paths.get("q25"),
                paths.get("q75"),
            ),
            "baseline_summary": summarize_cone(
                baseline["q10"],
                baseline["q50"],
                baseline["q90"],
                last,
                baseline["q25"],
                baseline["q75"],
            ),
            # Volatility per bar of ``interval`` (key name kept for compatibility).
            "daily_vol_pct": round(
                log_return_vol(series, lookback=lookback) * 100.0, 3
            ),
            "is_model": bool(model),
            "caveat": CAVEAT,
        }
    )
    return payload
