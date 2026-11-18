"""FastAPI routes for chart-ready market data."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from .market_data import (
    MarketDataProviderError,
    MarketDataValidationError,
    attach_indicators,
    attach_technicals,
    get_price_history,
)
from ...core.tools import forecast_tools
from ...core.tools.base import ToolError
from ...data.indicators import available_indicators

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/forecast")
def forecast(
    ticker: str = Query(
        ...,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Za-z0-9.^=_-]+$",
        description="Yahoo Finance ticker symbol, e.g. AAPL or ^GSPC.",
    ),
    horizon_days: int = Query(
        default=20, ge=1, le=60, description="Bars ahead (1-60) of `interval`."
    ),
    period: Optional[str] = Query(
        default=None,
        pattern=r"^(6mo|1y|2y|5y|10y|max)$",
        description="Yahoo Finance lookback used as model context "
        "(default 1y / 10y / max for 1d / 1wk / 1mo).",
    ),
    interval: str = Query(
        default="1d",
        pattern=r"^(1d|1wk|1mo)$",
        description="Bar size of the history and of the forecast steps.",
    ),
    method: str = Query(
        default="timesfm",
        pattern=r"^(timesfm|arima|arima_garch)$",
        description="timesfm (TimesFM, else random-walk baseline), arima "
        "(ARIMA(1,1,1) on log price) or arima_garch (same with GARCH(1,1) errors).",
    ),
) -> Dict[str, Any]:
    """Quantile price cone (q10/q25/q50/q75/q90) for charting.

    ``method=timesfm`` (default) always returns a cone: the TimesFM model when
    ``.[forecast]`` is installed, otherwise the random-walk baseline
    (``is_model`` tells which).  ``arima`` / ``arima_garch`` fit an
    ARIMA(1,1,1) on the log price (optionally with GARCH(1,1) errors) and add
    ``model_params`` / ``fit`` / ``step_vol_pct``.  ``available`` reports
    whether TimesFM is installed at all.
    """
    try:
        payload = forecast_tools.forecast_quantiles(
            ticker,
            horizon_days=horizon_days,
            period=period,
            interval=interval,
            method=method,
        )
    except ToolError as exc:
        text = str(exc)
        status = 502 if "provider" in text or "no price data" in text else 400
        raise HTTPException(status_code=status, detail=text[:200]) from exc
    payload["available"] = forecast_tools.timesfm_available()
    return payload


@router.get("/price-history")
def price_history(
    ticker: str = Query(
        ...,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Za-z0-9.^=_-]+$",
        description="Yahoo Finance ticker symbol, e.g. AAPL or ^GSPC.",
    ),
    period: str = Query(
        default="1y",
        pattern=r"^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd|max)$",
        description="Yahoo Finance lookback period.",
    ),
    interval: str = Query(
        default="1d",
        pattern=r"^(1d|1wk|1mo)$",
        description="Daily-or-slower bar interval for charting.",
    ),
    cache: bool = Query(default=True, description="Use saved fetched data when fresh."),
    force_refresh: bool = Query(
        default=False, description="Bypass saved data and fetch again."
    ),
    ttl_seconds: int = Query(
        default=900,
        ge=0,
        le=86_400,
        description="Freshness window for saved fetched data.",
    ),
    indicators: str = Query(
        default="",
        max_length=200,
        pattern=r"^[A-Za-z0-9_,]*$",
        description="Optional comma-separated technical indicators to overlay, e.g. 'close_50_sma,rsi'.",
    ),
    technicals: bool = Query(
        default=False,
        description="Attach an investing.com-style technical-summary gauge block.",
    ),
) -> Dict[str, Any]:
    """Return chart-ready Yahoo Finance price history with cache metadata."""
    requested = [name.strip().lower() for name in indicators.split(",") if name.strip()]
    if requested:
        valid = set(available_indicators())
        unknown = [name for name in requested if name not in valid]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown indicator(s): {', '.join(unknown)}; "
                    f"valid: {', '.join(sorted(valid))}"
                ),
            )
    try:
        payload = get_price_history(
            ticker=ticker,
            period=period,
            interval=interval,
            cache_enabled=cache,
            force_refresh=force_refresh,
            ttl_seconds=ttl_seconds,
        )
        if requested:
            payload = attach_indicators(payload, requested)
        if technicals:
            payload = attach_technicals(payload)
        return payload
    except MarketDataValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MarketDataProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"market data provider unavailable: {str(exc)[:120]}",
        ) from exc
