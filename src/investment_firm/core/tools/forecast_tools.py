"""Optional zero-shot price-path forecast tool backed by Google TimesFM.

The heavy dependencies (``timesfm`` + ``torch``, installed via the ``.[forecast]``
extra) are imported lazily and only when :func:`timesfm_available` says they are
present.  Without them :func:`default_forecast_tools` returns ``[]`` so the model
is never advertised a tool that could only fail, while :func:`forecast_quantiles`
itself still works and ships the random-walk baseline cone (``is_model: false``)
so the web endpoint can always draw *something* honest.

All cone arithmetic lives in :mod:`investment_firm.data.forecast` (pure, network
free).  This module only fetches closes (yfinance, like ``get_prices``), runs the
model when available, and adapts shapes.  Decision support only — a cone is a
statistical range, never a trade instruction.

Environment (read lazily so tests can monkeypatch):

* ``IFA_FORECAST_MODEL``  — HF repo of the weights (default
  ``google/timesfm-2.5-200m-pytorch``, Apache-2.0).  TimesFM 3.0 weights are
  non-commercial and are deliberately *not* the default.
* ``IFA_FORECAST_DEVICE`` — ``cpu`` (default) or a torch device string.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import Tool, ToolError
from ...data import arima_garch as ag
from ...data import forecast as fc

DEFAULT_MODEL_REPO = "google/timesfm-2.5-200m-pytorch"
MODEL_SOURCE = "TimesFM 2.5 200M zero-shot (experimental)"
MAX_CONTEXT = 1024
_MODEL_MAX_HORIZON = 256
# TimesFM 2.5 returns ``(n_series, horizon, 10)``: index 0 is the mean, 1..9 the
# deciles q10..q90.  q25/q75 are not deciles, so they are the midpoint of the
# neighbouring deciles (q20/q30 and q70/q80).
_QUANTILE_INDEX = {"q10": 1, "q50": 5, "q90": 9}
_INTERPOLATED_INDEX = {"q25": (2, 3), "q75": (7, 8)}
_QUANTILE_WIDTH = 10
# History fed to the model per bar interval (TimesFM needs >= 64 bars).
DEFAULT_PERIOD = {"1d": "1y", "1wk": "10y", "1mo": "max"}
# ``timesfm`` = TimesFM when installed, else the random-walk baseline.
METHODS: Tuple[str, ...] = ("timesfm", *ag.METHODS)


def forecast_model_repo() -> str:
    return os.getenv("IFA_FORECAST_MODEL", "").strip() or DEFAULT_MODEL_REPO


def forecast_device() -> str:
    return os.getenv("IFA_FORECAST_DEVICE", "").strip() or "cpu"


def timesfm_available() -> bool:
    """True when both ``timesfm`` and ``torch`` can be imported (no import yet)."""
    try:
        return (
            importlib.util.find_spec("timesfm") is not None
            and importlib.util.find_spec("torch") is not None
        )
    except (ImportError, ValueError):  # pragma: no cover - broken partial installs
        return False


# ---------------------------------------------------------------------------
# Model loading (cached once per process)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_model(repo: str, device: str) -> Any:
    """Download/compile TimesFM 2.5 once.  Raises ``ToolError`` on any failure."""
    try:
        import timesfm  # type: ignore
    except ImportError as exc:  # pragma: no cover - gated by timesfm_available
        raise ToolError(
            'TimesFM not installed; run: pip install -e ".[forecast]"'
        ) from exc
    try:
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(repo)
        config = timesfm.ForecastConfig(
            max_context=MAX_CONTEXT,
            max_horizon=_MODEL_MAX_HORIZON,
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=True,
            fix_quantile_crossing=True,
        )
        model.compile(config)
    except ToolError:
        raise
    except Exception as exc:  # network, HF auth, API drift
        raise ToolError(f"could not load TimesFM weights {repo!r}: {exc}") from exc
    if device != "cpu":
        inner = getattr(model, "model", None)
        try:
            if hasattr(inner, "to"):
                inner.to(device)
        except Exception as exc:  # pragma: no cover - device specific
            raise ToolError(f"could not move TimesFM to {device!r}: {exc}") from exc
    return model


def reset_model_cache() -> None:
    """Drop the cached model (tests / env changes)."""
    _load_model.cache_clear()


# ---------------------------------------------------------------------------
# Shape adaptation
# ---------------------------------------------------------------------------


def _to_nested_list(obj: Any) -> Any:
    tolist = getattr(obj, "tolist", None)
    if callable(tolist):
        return tolist()
    return obj


def _extract_quantiles(quantiles: Any, horizon: int) -> Dict[str, List[float]]:
    """Map the TimesFM ``(1, horizon, 10)`` tensor to q10/q25/q50/q75/q90 paths."""
    rows = _to_nested_list(quantiles)
    try:
        series = rows[0]
        if len(series) < horizon:
            raise ValueError(f"model returned {len(series)} steps, need {horizon}")
        out: Dict[str, List[float]] = {
            k: [] for k in (*_QUANTILE_INDEX, *_INTERPOLATED_INDEX)
        }
        for step in series[:horizon]:
            if len(step) != _QUANTILE_WIDTH:
                raise ValueError(
                    f"expected {_QUANTILE_WIDTH} quantile columns, got {len(step)}"
                )
            for key, idx in _QUANTILE_INDEX.items():
                out[key].append(float(step[idx]))
            for key, (lo, hi) in _INTERPOLATED_INDEX.items():
                out[key].append((float(step[lo]) + float(step[hi])) / 2.0)
    except (TypeError, IndexError, KeyError, ValueError) as exc:
        raise ToolError(f"unexpected TimesFM output shape: {exc}") from exc
    return out


def _model_quantiles(closes: Sequence[float], horizon: int) -> Dict[str, List[float]]:
    model = _load_model(forecast_model_repo(), forecast_device())
    context = list(closes)[-MAX_CONTEXT:]
    try:
        import numpy as np  # type: ignore

        inputs: Any = [np.asarray(context, dtype=float)]
    except ImportError:  # pragma: no cover - numpy ships with torch
        inputs = [context]
    try:
        _point, quantiles = model.forecast(horizon=horizon, inputs=inputs)
    except Exception as exc:
        raise ToolError(f"TimesFM inference failed: {exc}") from exc
    return _extract_quantiles(quantiles, horizon)


# ---------------------------------------------------------------------------
# Price fetch (same provider path as get_prices)
# ---------------------------------------------------------------------------


def _close_series(
    ticker: str, period: str, interval: str = "1d"
) -> Tuple[List[float], str]:
    """Return ``(closes, last_date_iso)`` from Yahoo Finance via yfinance."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover - only without the data extra
        raise ToolError(
            "provider 'yfinance' not installed; run: pip install -e \".[data]\""
        ) from exc

    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    if hist is None or getattr(hist, "empty", True):
        raise ToolError(f"no price data for {ticker!r}")
    close = hist["Close"].dropna()
    if close.empty:
        raise ToolError(f"no usable closes for {ticker!r}")
    closes = [float(v) for v in close.tolist()]
    last = close.index[-1]
    try:
        last_iso = last.date().isoformat()
    except AttributeError:
        last_iso = str(last)[:10]
    return closes, last_iso


# ---------------------------------------------------------------------------
# Tool function
# ---------------------------------------------------------------------------


def forecast_quantiles(
    ticker: str,
    horizon_days: int = 20,
    period: Optional[str] = None,
    interval: str = "1d",
    method: str = "timesfm",
) -> Dict[str, Any]:
    """Quantile cone (q10/q25/q50/q75/q90) of future closes for ``ticker``.

    ``horizon_days`` counts bars of ``interval`` (days, weeks or months); the
    model sees closes sampled at that interval.  ``method``:

    * ``timesfm`` (default) -- TimesFM 2.5 zero-shot when installed, otherwise
      the driftless random-walk baseline.  A model failure is reported in
      ``model_error`` and the payload degrades to the baseline.
    * ``arima`` -- ARIMA(1,1,1) on the log price, constant error variance.
    * ``arima_garch`` -- the same mean with GARCH(1,1) error variance.

    The baseline is always included for comparison; ``is_model`` tells whether
    a model populates ``q10..q90`` and ``method`` which one.
    """
    if interval not in fc.INTERVALS:
        raise ToolError(f"interval must be one of {fc.INTERVALS}; got {interval!r}")
    if method not in METHODS:
        raise ToolError(f"method must be one of {METHODS}; got {method!r}")
    period = period or DEFAULT_PERIOD[interval]
    try:
        horizon = fc.clamp_horizon(horizon_days)
    except fc.ForecastError as exc:
        raise ToolError(str(exc)) from exc
    closes, last_iso = _close_series(ticker, period, interval)
    try:
        closes = fc.validate_series(closes)
    except fc.ForecastError as exc:
        raise ToolError(f"{ticker}: {exc}") from exc

    model_q: Optional[Dict[str, List[float]]] = None
    model_error = ""
    econ: Optional[Dict[str, Any]] = None
    if method in ag.METHODS:
        try:
            econ = ag.arima_garch_quantiles(
                closes, horizon, garch=method == "arima_garch"
            )
        except fc.ForecastError as exc:
            raise ToolError(f"{ticker}: {exc}") from exc
        model_q = econ["quantiles"]
        source = ag.METHOD_LABELS[method]
    else:
        if timesfm_available():
            try:
                model_q = _model_quantiles(closes, horizon)
            except ToolError as exc:
                model_error = str(exc)
        source = MODEL_SOURCE if model_q else "random-walk baseline"

    try:
        payload = fc.cone_payload(
            ticker=ticker,
            closes=closes,
            last_date_iso=last_iso,
            horizon=horizon,
            model_quantiles=model_q,
            source=source,
            interval=interval,
        )
    except fc.ForecastError as exc:
        raise ToolError(str(exc)) from exc
    payload["period"] = period
    if econ is not None:
        payload["method"] = method
        payload["context_points"] = len(closes)
        payload["model_repo"] = None
        payload["model_params"] = econ["params"]
        payload["fit"] = econ["fit"]
        payload["step_vol_pct"] = econ["step_vol_pct"]
    else:
        payload["method"] = "timesfm" if model_q else "baseline"
        payload["context_points"] = min(len(closes), MAX_CONTEXT)
        payload["model_repo"] = forecast_model_repo() if model_q else None
    if model_error:
        payload["model_error"] = model_error
    payload["price_source"] = "yfinance (Yahoo Finance)"
    return payload


_FORECAST_TOOL = Tool(
    name="forecast_quantiles",
    description=(
        "EXPERIMENTAL statistical price-path cone (10/25/50/75/90th percentile of "
        "future closes) for a ticker from a zero-shot time-series foundation model "
        "(TimesFM), alongside a random-walk baseline cone. Use only to size the "
        "range of plausible outcomes over 1-60 bars of the chosen interval; it "
        "carries no view on fundamentals or news. Always quote the caveat and "
        "compare with the baseline."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "e.g. 'AAPL' or 'SPY'"},
            "horizon_days": {
                "type": "integer",
                "description": "bars ahead (days, weeks or months per interval), 1-60",
                "default": 20,
            },
            "interval": {
                "type": "string",
                "enum": list(fc.INTERVALS),
                "description": "bar size of the history and the forecast steps",
                "default": "1d",
            },
            "period": {
                "type": "string",
                "description": "history window fed to the model, e.g. '1y','5y','max' "
                "(default depends on interval)",
            },
        },
        "required": ["ticker"],
    },
    func=forecast_quantiles,
)


def default_forecast_tools() -> List[Tool]:
    """``[forecast_quantiles]`` when TimesFM is installed, else ``[]``."""
    if not timesfm_available():
        return []
    return [_FORECAST_TOOL]
