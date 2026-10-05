"""Portfolio analytics endpoints (in-memory registry).

Routes
------
POST /api/portfolio/analyze               Parse + analyse + backtest (free, no LLM).
GET  /api/portfolio/{id}                  Stored analysis (+ suggestion if any).
GET  /api/portfolio/{id}/report.html      Self-contained HTML report.
POST /api/portfolio/{id}/suggest          Advisor suggestions (spends tokens).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import investment_firm
from investment_firm.core import portfolio_advisor
from investment_firm.core.horizon import HORIZONS
from investment_firm.data.backtest import STRATEGIES
from investment_firm.data.portfolio import (
    PortfolioError,
    analyze_portfolio,
    parse_portfolio,
)
from investment_firm.interfaces.report.portfolio_html import render_portfolio_report
from investment_firm.llm.costs import RunTracker

from . import portfolio_data, runs
from .market_data import MarketDataProviderError, MarketDataValidationError

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_lock = threading.Lock()
_analyses: Dict[str, Dict[str, Any]] = {}
_REGISTRY_CAP = 50
_DIGEST_MAX_CHARS = 8000

_PCT_KEYS = (
    "total_return",
    "cagr",
    "ann_vol",
    "max_drawdown",
    "hist_var_1d",
    "param_var_1d",
    "es_1d",
    "var_10d_sqrt_scaled",
    "best_day",
    "worst_day",
    "pct_positive_days",
    "tracking_error",
    "benchmark_cagr",
    "excess_cagr",
    "downside_dev",
)
_RATIO_KEYS = (
    "sharpe",
    "sortino",
    "calmar",
    "beta",
    "correlation",
    "information_ratio",
    "skew",
    "excess_kurtosis",
)


class AnalyzeRequest(BaseModel):
    portfolio_text: str = Field(..., max_length=100_000)
    format: Literal["auto", "csv", "json"] = "auto"
    horizon: Literal["short", "medium", "long"] = "short"
    period: Optional[Literal["6mo", "1y", "2y", "5y", "10y", "max"]] = None
    benchmark: str = Field("SPY", pattern=r"^[A-Za-z0-9.^=_-]{1,24}$")
    var_level: float = Field(0.99, gt=0.5, lt=1.0)
    rf_annual: float = Field(0.0, ge=-0.05, le=0.25)
    rebalance: Literal["none", "monthly", "daily"] = "none"
    cost_bps: float = Field(0.0, ge=0, le=500)
    strategies: List[str] = Field(default_factory=lambda: sorted(STRATEGIES))


class SuggestRequest(BaseModel):
    run_id: Optional[str] = None
    model: Optional[str] = None


def _pct(x: Any) -> Optional[float]:
    return None if x is None else round(float(x) * 100, 2)


def _ratio(x: Any) -> Optional[float]:
    return None if x is None else round(float(x), 2)


def _present(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Headline stats as rounded percent / ratio figures so nobody misreads fractions."""
    stats = analysis.get("stats") or {}
    out: Dict[str, Any] = {f"{k}_pct": _pct(stats.get(k)) for k in _PCT_KEYS}
    out.update({k: _ratio(stats.get(k)) for k in _RATIO_KEYS})
    out.update(
        {
            "peak_date": stats.get("peak_date"),
            "trough_date": stats.get("trough_date"),
            "recovery_date": stats.get("recovery_date"),
            "duration_days": stats.get("duration_days"),
            "level_pct": _pct(stats.get("level")),
            "rf_annual_pct": _pct(stats.get("rf_annual")),
            "n_obs": stats.get("n_obs"),
        }
    )
    return out


def build_digest(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Compact advisor input (no full series), capped at ~8000 JSON characters."""
    analysis = entry["analysis"]
    div = analysis.get("diversification") or {}
    overlays = sorted(
        analysis.get("strategy_overlays") or [],
        key=lambda o: (o.get("stats") or {}).get("sharpe") or float("-inf"),
        reverse=True,
    )
    digest: Dict[str, Any] = {
        "positions": [
            {"ticker": p["ticker"], "weight_pct": _pct(p["weight"])}
            for p in analysis.get("positions") or []
        ],
        "window": analysis.get("window"),
        "benchmark": (analysis.get("params") or {}).get("benchmark"),
        "stats": entry["display"],
        "rebalance_comparison": {
            mode: (
                {
                    "cagr_pct": _pct(s.get("cagr")),
                    "ann_vol_pct": _pct(s.get("ann_vol")),
                    "max_drawdown_pct": _pct(s.get("max_drawdown")),
                    "sharpe": _ratio(s.get("sharpe")),
                }
                if s
                else None
            )
            for mode, s in (analysis.get("rebalance_comparison") or {}).items()
        },
        "strategy_overlays": [
            {
                "strategy": o["strategy"],
                "cagr_pct": _pct(o["stats"].get("cagr")),
                "max_drawdown_pct": _pct(o["stats"].get("max_drawdown")),
                "sharpe": _ratio(o["stats"].get("sharpe")),
            }
            for o in overlays[:4]
        ],
        "diversification": {
            "hhi": _ratio(div.get("hhi")),
            "effective_n": _ratio(div.get("effective_n")),
            "avg_pairwise_corr": _ratio(div.get("avg_pairwise_corr")),
        },
        "warnings": list(analysis.get("warnings") or [])[:10],
    }
    while (
        len(json.dumps(digest, default=str)) > _DIGEST_MAX_CHARS and digest["positions"]
    ):
        digest["positions"] = digest["positions"][:-1]
        digest["positions_truncated"] = True
    return digest


def _store(entry: Dict[str, Any]) -> None:
    with _lock:
        _analyses[entry["analysis_id"]] = entry
        while len(_analyses) > _REGISTRY_CAP:
            del _analyses[next(iter(_analyses))]


def _get(analysis_id: str) -> Dict[str, Any]:
    with _lock:
        entry = _analyses.get(analysis_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="portfolio analysis not found")
    return entry


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "analysis_id": entry["analysis_id"],
        "analysis": entry["analysis"],
        "display": entry["display"],
        "suggestion": entry.get("suggestion"),
        "suggestion_cost": entry.get("suggestion_cost"),
        "report_url": f"/api/portfolio/{entry['analysis_id']}/report.html",
        "generated_at": entry["generated_at"],
        "disclaimer": investment_firm.DISCLAIMER,
    }


@router.post("/analyze")
def analyze(body: AnalyzeRequest) -> Dict[str, Any]:
    """Parse the upload, fetch prices and compute analytics + backtests (no LLM)."""
    period = body.period or HORIZONS[body.horizon].portfolio_period
    unknown = [s for s in body.strategies if s not in STRATEGIES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown strategy {', '.join(unknown)[:80]}; valid: "
            f"{', '.join(sorted(STRATEGIES))}",
        )
    try:
        portfolio = parse_portfolio(body.portfolio_text, body.format)
        tickers = [p.ticker for p in portfolio.positions]
        payloads, bench, fetch_warnings = portfolio_data.load_portfolio_prices(
            tickers, period, benchmark=body.benchmark
        )
        frames = None
        if body.strategies:
            try:
                frames = {
                    t: portfolio_data.payload_to_ohlcv_frame(p)
                    for t, p in payloads.items()
                }
            except MarketDataProviderError:
                frames = None
        portfolio.warnings.extend(fetch_warnings)
        analysis = analyze_portfolio(
            portfolio,
            {t: portfolio_data.payload_to_series(p) for t, p in payloads.items()},
            benchmark_series=portfolio_data.payload_to_series(bench) or None,
            benchmark=body.benchmark.upper(),
            ohlcv_frames=frames,
            level=body.var_level,
            rf_annual=body.rf_annual,
            rebalance=body.rebalance,
            cost_bps=body.cost_bps,
            strategies=body.strategies,
            horizon=body.horizon,
        )
    except (PortfolioError, MarketDataValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MarketDataProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"market data provider unavailable: {str(exc)[:120]}",
        ) from exc
    analysis["params"]["period"] = period
    entry = {
        "analysis_id": uuid.uuid4().hex[:12],
        "analysis": analysis,
        "display": _present(analysis),
        "suggestion": None,
        "suggestion_cost": None,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _store(entry)
    return _public(entry)


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str) -> Dict[str, Any]:
    return _public(_get(analysis_id))


@router.get("/{analysis_id}/report.html")
def portfolio_report(analysis_id: str) -> HTMLResponse:
    entry = _get(analysis_id)
    return HTMLResponse(
        render_portfolio_report(entry),
        headers={
            "Content-Disposition": (
                f'attachment; filename="portfolio-report-{entry["analysis_id"]}.html"'
            )
        },
    )


@router.post("/{analysis_id}/suggest")
def suggest(analysis_id: str, body: SuggestRequest) -> Dict[str, Any]:
    """Ask the advisor LLM for options and trade-offs (spends tokens)."""
    entry = _get(analysis_id)
    memo = None
    if body.run_id:
        try:
            memo = runs.completed_memo(body.run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail="run is not finished") from exc
    tracker = RunTracker()
    suggestion = portfolio_advisor.suggest(
        build_digest(entry),
        market_context=memo,
        horizon=(entry["analysis"].get("params") or {}).get("horizon", "short"),
        model=body.model or None,
        tracker=tracker,
    )
    cost = {
        "cost_usd": round(tracker.total_usd, 6),
        "total_tokens": tracker.total_tokens,
        "by_model": tracker.by_model(),
    }
    with _lock:
        entry["suggestion"] = suggestion
        entry["suggestion_cost"] = cost
    return {
        "analysis_id": analysis_id,
        "suggestion": suggestion,
        "suggestion_cost": cost,
        "disclaimer": investment_firm.DISCLAIMER,
    }
