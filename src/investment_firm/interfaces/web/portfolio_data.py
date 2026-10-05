"""Price loading for portfolio analytics (wraps the cached market-data fetch)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import market_data
from .market_data import MarketDataError, MarketDataProviderError


def load_portfolio_prices(
    tickers: List[str], period: str, *, benchmark: Optional[str]
) -> Tuple[Dict[str, dict], Optional[dict], List[str]]:
    """Fetch daily bars for every holding (+ benchmark); return ``(payloads, bench, warnings)``.

    A holding that cannot be fetched raises :class:`MarketDataProviderError`;
    a missing benchmark only produces a warning.
    """
    payloads: Dict[str, dict] = {}
    for ticker in tickers:
        try:
            payloads[ticker] = market_data.get_price_history(ticker, period, "1d")
        except MarketDataProviderError as exc:
            raise MarketDataProviderError(f"{ticker}: {exc}") from exc
    warnings: List[str] = []
    bench: Optional[dict] = None
    if benchmark:
        if benchmark.upper() in payloads:
            bench = payloads[benchmark.upper()]
        else:
            try:
                bench = market_data.get_price_history(benchmark, period, "1d")
            except MarketDataError as exc:
                warnings.append(
                    f"Benchmark {benchmark.upper()} could not be loaded "
                    f"({str(exc)[:80]})."
                )
    return payloads, bench, warnings


def payload_to_series(payload: Optional[Dict[str, Any]]) -> List[Tuple[str, float]]:
    """``[(time, close)]`` from a price-history payload."""
    if not payload:
        return []
    return [
        (str(row["time"]), float(row["close"])) for row in payload.get("ohlc") or []
    ]


def payload_to_ohlcv_frame(payload: Dict[str, Any]):
    """DataFrame for the strategy backtester (same columns as the chart overlays)."""
    return market_data.ohlcv_frame(payload)
