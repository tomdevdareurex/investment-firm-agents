"""FastAPI routes for chart-ready market data."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from .market_data import (
    MarketDataProviderError,
    MarketDataValidationError,
    attach_indicators,
    attach_technicals,
    get_price_history,
)
from ...core.indicators import available_indicators

router = APIRouter(prefix="/api/market", tags=["market"])


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
