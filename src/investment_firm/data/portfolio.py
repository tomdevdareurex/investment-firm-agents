"""Portfolio parsing, analytics and backtests — pure compute, network-free.

Inputs are price series ``[(date, close)]`` per ticker; fetching lives in the
callers (``interfaces/web/portfolio_data.py``). Stdlib plus ``data.risk`` /
``data.backtest``; pandas is imported lazily inside :func:`strategy_overlays`.

Conventions: raw fractions everywhere; VaR / ES / max drawdown are positive
losses; 252 trading days per year. Historical analysis only — never a trade
instruction.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from . import risk
from .backtest import STRATEGIES, BacktestError, run_strategy

TRADING_DAYS = 252
MAX_POSITIONS = 50
MAX_INPUT_BYTES = 100_000
MIN_COMMON_DATES = 30
MAX_SERIES_POINTS = 600
_TICKER_RE = re.compile(r"^[A-Za-z0-9.^=_-]{1,24}$")
_KNOWN_COLUMNS = {"ticker", "weight", "quantity", "price"}
_REBALANCE_MODES = ("none", "monthly", "daily")
_EPS = 1e-12

Series = List[Tuple[str, float]]


class PortfolioError(ValueError):
    """Raised for invalid portfolio input or uncomputable analytics."""


@dataclass
class Position:
    ticker: str
    weight: Optional[float] = None
    quantity: Optional[float] = None
    price: Optional[float] = None


@dataclass
class Portfolio:
    positions: List[Position]
    mode: Literal["weight", "quantity"]
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_number(raw: object, column: str, ticker: str) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise PortfolioError(f"{ticker}: {column} must be a number")
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip().rstrip("%").strip()
        if not text:
            return None
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            raise PortfolioError(
                f"{ticker}: {column} {str(raw)[:20]!r} is not a number"
            ) from None
    if not math.isfinite(value):
        raise PortfolioError(f"{ticker}: {column} must be finite")
    if value < 0:
        raise PortfolioError(f"{ticker}: {column} must not be negative")
    return value


def _rows_from_csv(text: str, warnings: List[str]) -> List[Dict[str, object]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise PortfolioError("CSV needs a header row, e.g. 'ticker,weight'")
    headers = {h: (h or "").strip().lower() for h in reader.fieldnames}
    if "symbol" in headers.values() and "ticker" not in headers.values():
        headers = {k: ("ticker" if v == "symbol" else v) for k, v in headers.items()}
    if "ticker" not in headers.values():
        raise PortfolioError("CSV header must include a 'ticker' column")
    extra = sorted(v for v in headers.values() if v and v not in _KNOWN_COLUMNS)
    if extra:
        warnings.append(f"Ignored extra column(s): {', '.join(extra)}")
    rows: List[Dict[str, object]] = []
    for raw in reader:
        row = {headers[k]: v for k, v in raw.items() if k in headers}
        if not any(str(v or "").strip() for v in row.values()):
            continue
        rows.append(row)
    return rows


def _rows_from_json(text: str) -> List[Dict[str, object]]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PortfolioError(f"invalid JSON: {exc.msg}") from None
    positions = data.get("positions") if isinstance(data, dict) else data
    if not isinstance(positions, list):
        raise PortfolioError("JSON must be a list of positions or {'positions': [...]}")
    rows = []
    for item in positions:
        if not isinstance(item, dict):
            raise PortfolioError("each JSON position must be an object")
        rows.append({str(k).lower(): v for k, v in item.items()})
    return rows


def _build(rows: List[Dict[str, object]], warnings: List[str]) -> Portfolio:
    if not rows:
        raise PortfolioError("portfolio has no positions")
    if len(rows) > MAX_POSITIONS:
        raise PortfolioError(
            f"portfolio has {len(rows)} positions; the maximum is {MAX_POSITIONS}"
        )
    merged: Dict[str, Position] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not _TICKER_RE.match(ticker):
            raise PortfolioError(f"invalid ticker {ticker[:30]!r}")
        weight = _parse_number(row.get("weight"), "weight", ticker)
        quantity = _parse_number(row.get("quantity"), "quantity", ticker)
        price = _parse_number(row.get("price"), "price", ticker)
        if ticker in merged:
            prev = merged[ticker]
            warnings.append(f"Duplicate ticker {ticker} merged (amounts summed)")
            merged[ticker] = Position(
                ticker,
                None if weight is None else (prev.weight or 0.0) + weight,
                None if quantity is None else (prev.quantity or 0.0) + quantity,
                prev.price if prev.price is not None else price,
            )
        else:
            merged[ticker] = Position(ticker, weight, quantity, price)

    positions = list(merged.values())
    has_w = any(p.weight is not None for p in positions)
    has_q = any(p.quantity is not None for p in positions)
    if has_w and has_q:
        raise PortfolioError("use either weights or quantities, not both")
    if not (has_w or has_q):
        raise PortfolioError("each position needs a weight or a quantity")
    mode: Literal["weight", "quantity"] = "weight" if has_w else "quantity"
    attr = mode
    if any(getattr(p, attr) is None for p in positions):
        raise PortfolioError(f"every position needs a {attr}")
    if not any(getattr(p, attr) > 0 for p in positions):
        raise PortfolioError(f"at least one {attr} must be greater than zero")

    zero = [p.ticker for p in positions if getattr(p, attr) == 0]
    if zero:
        warnings.append(f"Dropped zero-{attr} position(s): {', '.join(zero)}")
        positions = [p for p in positions if getattr(p, attr) > 0]

    if mode == "weight":
        total = sum(p.weight or 0.0 for p in positions)
        if total > 1.5:
            warnings.append("Weights look like percentages; divided by 100.")
            positions = [
                Position(p.ticker, (p.weight or 0.0) / 100.0, None, p.price)
                for p in positions
            ]
            total /= 100.0
        if abs(total - 1.0) > 1e-6:
            warnings.append(f"Weights summed to {total:.4f}; normalised to 100%.")
    return Portfolio(positions=positions, mode=mode, warnings=warnings)


def parse_portfolio(text: str, fmt: str = "auto") -> Portfolio:
    """Parse a CSV (``ticker,weight`` / ``ticker,quantity[,price]``) or JSON portfolio."""
    text = text or ""
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise PortfolioError("portfolio file is larger than 100 KB")
    stripped = text.strip().lstrip("\ufeff")
    if not stripped:
        raise PortfolioError("portfolio is empty")
    if fmt == "auto":
        fmt = "json" if stripped[0] in "{[" else "csv"
    warnings: List[str] = []
    if fmt == "json":
        rows = _rows_from_json(stripped)
    elif fmt == "csv":
        rows = _rows_from_csv(stripped, warnings)
    else:
        raise PortfolioError(f"unknown format {fmt!r}")
    return _build(rows, warnings)


def normalize_weights(
    portfolio: Portfolio, last_prices: Dict[str, float]
) -> Dict[str, float]:
    """Return target weights summing to 1 (quantity mode values holdings at last price)."""
    if portfolio.mode == "weight":
        raw = {p.ticker: float(p.weight or 0.0) for p in portfolio.positions}
    else:
        raw = {}
        for p in portfolio.positions:
            price = p.price if p.price is not None else last_prices.get(p.ticker)
            if price is None:
                raise PortfolioError(f"{p.ticker}: no price available to value it")
            raw[p.ticker] = float(p.quantity or 0.0) * float(price)
    total = sum(raw.values())
    if total <= 0:
        raise PortfolioError("portfolio has no value")
    return {t: v / total for t, v in raw.items()}


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def align_closes(
    series: Dict[str, Series],
) -> Tuple[List[str], Dict[str, List[float]], int]:
    """Inner-join price series on date; return ``(dates, closes, dropped_count)``."""
    maps: Dict[str, Dict[str, float]] = {}
    for ticker, points in series.items():
        clean = {}
        for d, v in points or []:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv) and fv > 0:
                clean[str(d)] = fv
        maps[ticker] = clean
    if not maps:
        raise PortfolioError("no price series supplied")
    all_dates = set().union(*(m.keys() for m in maps.values()))
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    if len(common) < MIN_COMMON_DATES:
        raise PortfolioError(
            f"only {len(common)} dates are shared by all holdings; need at least "
            f"{MIN_COMMON_DATES}"
        )
    closes = {t: [m[d] for d in common] for t, m in maps.items()}
    return common, closes, len(all_dates) - len(common)


def _returns(values: Sequence[float]) -> List[float]:
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values))]


def portfolio_equity(
    dates: Sequence[str],
    closes: Dict[str, List[float]],
    weights: Dict[str, float],
    rebalance: str = "none",
) -> Tuple[List[float], List[float], Dict[str, float]]:
    """Value of 1 unit invested at ``dates[0]``; return ``(equity, returns, final_weights)``.

    ``none`` = buy-and-hold (weights drift), ``daily`` = constant mix, ``monthly`` =
    reset to target weights on the first date of each new calendar month.
    """
    if rebalance not in _REBALANCE_MODES:
        raise PortfolioError(f"unknown rebalance mode {rebalance!r}")
    tickers = [t for t in weights if weights[t] > 0]
    n = len(dates)
    holdings = {t: weights[t] for t in tickers}
    equity = [sum(holdings.values())]
    for i in range(1, n):
        for t in tickers:
            holdings[t] *= closes[t][i] / closes[t][i - 1]
        value = sum(holdings.values())
        equity.append(value)
        new_month = str(dates[i])[:7] != str(dates[i - 1])[:7]
        if rebalance == "daily" or (rebalance == "monthly" and new_month):
            holdings = {t: weights[t] * value for t in tickers}
    final = sum(holdings.values()) or 1.0
    return equity, _returns(equity), {t: h / final for t, h in holdings.items()}


def _day_gap(a: str, b: str, fallback: int) -> int:
    try:
        return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
    except ValueError:
        return fallback


def drawdown_details(dates: Sequence[str], equity: Sequence[float]) -> Dict[str, Any]:
    """Max drawdown with its peak / trough / recovery dates and the underwater series."""
    peak_i = 0
    best = (0.0, 0, 0)  # (drawdown, peak index, trough index)
    underwater: List[float] = []
    for i, v in enumerate(equity):
        if v > equity[peak_i]:
            peak_i = i
        dd = (equity[peak_i] - v) / equity[peak_i]
        underwater.append(-dd)
        if dd > best[0]:
            best = (dd, peak_i, i)
    mdd = risk.max_drawdown(equity) if len(equity) >= 2 else 0.0
    if best[0] <= 0:
        return {
            "max_drawdown": mdd,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "duration_days": 0,
            "drawdown_series": underwater,
        }
    _, p, t = best
    recovery = next(
        (j for j in range(t + 1, len(equity)) if equity[j] >= equity[p]), None
    )
    end = recovery if recovery is not None else len(equity) - 1
    return {
        "max_drawdown": mdd,
        "peak_date": str(dates[p]),
        "trough_date": str(dates[t]),
        "recovery_date": str(dates[recovery]) if recovery is not None else None,
        "duration_days": _day_gap(dates[p], dates[end], end - p),
        "drawdown_series": underwater,
    }


def _cagr(total_return: float, n_returns: int) -> float:
    if n_returns <= 0 or total_return <= -1.0:
        return -1.0
    return (1.0 + total_return) ** (TRADING_DAYS / n_returns) - 1.0


def _moments(returns: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    m = statistics.fmean(returns)
    var = statistics.fmean((r - m) ** 2 for r in returns)
    if var <= _EPS**2:
        return None, None
    skew = statistics.fmean((r - m) ** 3 for r in returns) / var**1.5
    kurt = statistics.fmean((r - m) ** 4 for r in returns) / var**2 - 3.0
    return skew, kurt


def _ratio(num: float, den: Optional[float]) -> Optional[float]:
    return num / den if den is not None and den > _EPS else None


def _benchmark_stats(
    returns: Sequence[float], bench: Sequence[float], cagr: float
) -> Dict[str, Optional[float]]:
    n = len(returns)
    mr, mb = statistics.fmean(returns), statistics.fmean(bench)
    cov = sum((r - mr) * (b - mb) for r, b in zip(returns, bench)) / n
    var_r = sum((r - mr) ** 2 for r in returns) / n
    var_b = sum((b - mb) ** 2 for b in bench) / n
    diff = [r - b for r, b in zip(returns, bench)]
    te = statistics.stdev(diff) * math.sqrt(TRADING_DAYS) if n >= 2 else 0.0
    te = 0.0 if te < _EPS else te
    growth = 1.0
    for b in bench:
        growth *= 1.0 + b
    bench_cagr = _cagr(growth - 1.0, n)
    corr = cov / math.sqrt(var_r * var_b) if var_r > 0 and var_b > 0 else None
    return {
        "beta": cov / var_b if var_b > 0 else None,
        "correlation": corr,
        "tracking_error": te,
        "information_ratio": _ratio(cagr - bench_cagr, te),
        "benchmark_cagr": bench_cagr,
        "excess_cagr": cagr - bench_cagr,
    }


_BENCH_KEYS = (
    "beta",
    "correlation",
    "tracking_error",
    "information_ratio",
    "benchmark_cagr",
    "excess_cagr",
)


def performance_stats(
    dates: Sequence[str],
    equity: Sequence[float],
    returns: Sequence[float],
    *,
    level: float = 0.99,
    rf_annual: float = 0.0,
    benchmark_returns: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Return / risk / risk-adjusted statistics for one value curve."""
    n = len(returns)
    if n < 2:
        raise PortfolioError("need at least 2 returns to compute statistics")
    total = equity[-1] / equity[0] - 1.0
    cagr = _cagr(total, n)
    vol = risk.annualized_vol(returns, TRADING_DAYS)
    vol = 0.0 if vol < _EPS else vol
    rf_daily = (1.0 + rf_annual) ** (1.0 / TRADING_DAYS) - 1.0
    downside = math.sqrt(
        statistics.fmean(min(r - rf_daily, 0.0) ** 2 for r in returns)
    ) * math.sqrt(TRADING_DAYS)
    dd = drawdown_details(dates, equity)
    hist_var = risk.historical_var(returns, level)
    skew, kurt = _moments(returns)
    stats: Dict[str, Any] = {
        "total_return": total,
        "cagr": cagr,
        "ann_vol": vol,
        "sharpe": _ratio(cagr - rf_annual, vol),
        "downside_dev": downside,
        "sortino": _ratio(cagr - rf_annual, downside),
        "calmar": _ratio(cagr, dd["max_drawdown"]),
        "hist_var_1d": hist_var,
        "param_var_1d": risk.parametric_var(returns, level),
        "es_1d": risk.expected_shortfall(returns, level),
        "var_10d_sqrt_scaled": hist_var * math.sqrt(10),
        "best_day": max(returns),
        "worst_day": min(returns),
        "pct_positive_days": sum(1 for r in returns if r > 0) / n,
        "skew": skew,
        "excess_kurtosis": kurt,
        "n_obs": n,
        "level": level,
        "rf_annual": rf_annual,
    }
    stats.update({k: v for k, v in dd.items() if k != "drawdown_series"})
    if benchmark_returns is not None and len(benchmark_returns) == n:
        stats.update(_benchmark_stats(returns, benchmark_returns, cagr))
    else:
        stats.update({k: None for k in _BENCH_KEYS})
    return stats


def position_stats(
    dates: Sequence[str], closes: Dict[str, List[float]], weights: Dict[str, float]
) -> List[Dict[str, Any]]:
    """Per-holding stats; ``contribution_to_return`` is a buy-and-hold approximation."""
    out = []
    for ticker, w in weights.items():
        prices = closes[ticker]
        rets = _returns(prices)
        total = prices[-1] / prices[0] - 1.0
        out.append(
            {
                "ticker": ticker,
                "weight": w,
                "total_return": total,
                "cagr": _cagr(total, len(rets)),
                "ann_vol": risk.annualized_vol(rets, TRADING_DAYS),
                "max_drawdown": risk.max_drawdown(prices),
                "contribution_to_return": w * total,
            }
        )
    return sorted(out, key=lambda r: r["weight"], reverse=True)


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def diversification(
    weights: Dict[str, float], returns_by_ticker: Dict[str, List[float]]
) -> Dict[str, Any]:
    """Concentration (HHI, effective number of holdings) and correlations."""
    tickers = list(weights)
    hhi = sum(w * w for w in weights.values())
    matrix = [
        [
            1.0 if a == b else _pearson(returns_by_ticker[a], returns_by_ticker[b])
            for b in tickers
        ]
        for a in tickers
    ]
    pairs = [
        matrix[i][j]
        for i in range(len(tickers))
        for j in range(i + 1, len(tickers))
        if matrix[i][j] is not None
    ]
    return {
        "hhi": hhi,
        "effective_n": 1.0 / hhi if hhi > 0 else None,
        "largest_weight": max(weights.values()) if weights else None,
        "avg_pairwise_corr": statistics.fmean(pairs) if pairs else None,
        "correlation_matrix": {"tickers": tickers, "values": matrix},
    }


def rolling_vol(
    dates: Sequence[str], returns: Sequence[float], window: int = 63
) -> Series:
    """Annualised volatility over a trailing ``window`` of daily returns."""
    out: Series = []
    for end in range(window, len(returns) + 1):
        chunk = returns[end - window : end]
        out.append((str(dates[end]), statistics.stdev(chunk) * math.sqrt(TRADING_DAYS)))
    return out


def _downsample(points: Sequence[Any], cap: int = MAX_SERIES_POINTS) -> List[Any]:
    n = len(points)
    if n <= cap:
        return list(points)
    step = math.ceil((n - 1) / (cap - 1))
    idx = list(range(0, n - 1, step)) + [n - 1]
    return [points[i] for i in idx]


def _validate_strategies(strategies: Iterable[str]) -> List[str]:
    names = list(strategies)
    unknown = [s for s in names if s not in STRATEGIES]
    if unknown:
        raise PortfolioError(
            f"unknown strategy {', '.join(unknown)}; valid: {', '.join(sorted(STRATEGIES))}"
        )
    return [s for s in STRATEGIES if s in names]


def strategy_overlays(
    ohlcv_frames: Dict[str, Any],
    weights: Dict[str, float],
    strategies: Iterable[str],
    *,
    cost_bps: float = 0.0,
    level: float = 0.99,
    rf_annual: float = 0.0,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Apply each rule to every holding and combine the sleeves by target weight.

    Returns ``(overlays, warnings)``; a failing holding drops that strategy only.
    """
    warnings: List[str] = []
    try:
        import pandas  # noqa: F401  (run_strategy needs DataFrames)
    except ImportError:
        return [], ["Strategy backtests skipped: pandas is not installed."]
    overlays: List[Dict[str, Any]] = []
    for name in _validate_strategies(strategies):
        curves: Dict[str, Dict[str, float]] = {}
        per_ticker = []
        try:
            for ticker, w in weights.items():
                frame = ohlcv_frames.get(ticker)
                if frame is None:
                    raise BacktestError(f"{ticker}: no OHLCV data")
                res = run_strategy(
                    frame, name, cost_bps=cost_bps, level=level, return_curve=True
                )
                curves[ticker] = dict(zip(res["dates"], res["equity"]))
                per_ticker.append(
                    {
                        "ticker": ticker,
                        "total_return": res["total_return"],
                        "n_trades": res["n_trades"],
                        "time_in_market": res["time_in_market"],
                    }
                )
        except BacktestError as exc:
            warnings.append(f"Strategy {name} skipped: {exc}")
            continue
        common = sorted(set.intersection(*(set(c) for c in curves.values())))
        if len(common) < MIN_COMMON_DATES:
            warnings.append(f"Strategy {name} skipped: too few shared dates")
            continue
        equity = [
            sum(w * curves[t][d] / curves[t][common[0]] for t, w in weights.items())
            for d in common
        ]
        rets = _returns(equity)
        overlays.append(
            {
                "strategy": name,
                "rule": STRATEGIES[name],
                "stats": performance_stats(
                    common, equity, rets, level=level, rf_annual=rf_annual
                ),
                "equity": _downsample(list(zip(common, equity))),
                "per_ticker": per_ticker,
            }
        )
    return overlays, warnings


def _summary(stats: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("total_return", "cagr", "ann_vol", "sharpe", "max_drawdown")
    return {k: stats.get(k) for k in keys}


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _align_benchmark(
    dates: List[str],
    closes: Dict[str, List[float]],
    benchmark_series: Optional[Series],
    benchmark: str,
    warnings: List[str],
) -> Tuple[List[str], Dict[str, List[float]], Optional[List[float]]]:
    if not benchmark_series:
        warnings.append(
            f"Benchmark {benchmark} unavailable; benchmark comparisons are omitted."
        )
        return dates, closes, None
    b_map = {str(d): float(v) for d, v in benchmark_series if v and float(v) > 0}
    keep = [i for i, d in enumerate(dates) if d in b_map]
    if len(keep) < MIN_COMMON_DATES:
        warnings.append(
            f"Benchmark {benchmark} shares too few dates with the portfolio; omitted."
        )
        return dates, closes, None
    if len(keep) < len(dates):
        warnings.append(
            f"{len(dates) - len(keep)} date(s) without benchmark prices were dropped."
        )
        dates = [dates[i] for i in keep]
        closes = {t: [c[i] for i in keep] for t, c in closes.items()}
    return dates, closes, [b_map[d] for d in dates]


def analyze_portfolio(
    portfolio: Portfolio,
    series: Dict[str, Series],
    *,
    benchmark_series: Optional[Series] = None,
    benchmark: str = "SPY",
    ohlcv_frames: Optional[Dict[str, Any]] = None,
    level: float = 0.99,
    rf_annual: float = 0.0,
    rebalance: str = "none",
    cost_bps: float = 0.0,
    strategies: Optional[Iterable[str]] = None,
    horizon: str = "short",
) -> Dict[str, Any]:
    """Full analytics bundle (JSON-safe primitives only)."""
    if rebalance not in _REBALANCE_MODES:
        raise PortfolioError(f"unknown rebalance mode {rebalance!r}")
    chosen_strategies = _validate_strategies(
        STRATEGIES if strategies is None else strategies
    )
    warnings = list(portfolio.warnings)
    tickers = [p.ticker for p in portfolio.positions]
    missing = [t for t in tickers if not series.get(t)]
    if missing:
        raise PortfolioError(f"no price history for {', '.join(missing)}")

    dates, closes, dropped = align_closes({t: series[t] for t in tickers})
    if dropped:
        warnings.append(
            f"{dropped} date(s) where not every holding traded were dropped."
        )
    weights = normalize_weights(portfolio, {t: c[-1] for t, c in closes.items()})
    dates, closes, bench_closes = _align_benchmark(
        dates, closes, benchmark_series, benchmark, warnings
    )
    bench_equity = [c / bench_closes[0] for c in bench_closes] if bench_closes else None
    bench_rets = _returns(bench_equity) if bench_equity else None

    curves = {
        mode: portfolio_equity(dates, closes, weights, mode)
        for mode in _REBALANCE_MODES
    }
    stats_by_mode = {
        mode: performance_stats(
            dates,
            eq,
            rets,
            level=level,
            rf_annual=rf_annual,
            benchmark_returns=bench_rets,
        )
        for mode, (eq, rets, _) in curves.items()
    }
    comparison = {mode: _summary(s) for mode, s in stats_by_mode.items()}
    comparison["benchmark"] = (
        _summary(
            performance_stats(
                dates, bench_equity, bench_rets, level=level, rf_annual=rf_annual
            )
        )
        if bench_equity
        else None
    )

    equity, returns, final_weights = curves[rebalance]
    dd = drawdown_details(dates, equity)
    returns_by_ticker = {t: _returns(c) for t, c in closes.items()}

    overlays: List[Dict[str, Any]] = []
    if chosen_strategies:
        if ohlcv_frames:
            overlays, ow = strategy_overlays(
                ohlcv_frames,
                weights,
                chosen_strategies,
                cost_bps=cost_bps,
                level=level,
                rf_annual=rf_annual,
            )
            warnings.extend(ow)
        else:
            warnings.append("Strategy backtests skipped: no OHLCV data supplied.")

    positions = [
        {
            "ticker": p.ticker,
            "weight": weights[p.ticker],
            "final_weight": final_weights.get(p.ticker),
            "input_weight": p.weight,
            "quantity": p.quantity,
            "price": p.price,
        }
        for p in portfolio.positions
    ]
    result = {
        "positions": positions,
        "weights": weights,
        "mode": portfolio.mode,
        "window": {
            "start": dates[0],
            "end": dates[-1],
            "n_obs": len(returns),
            "dropped_dates": dropped,
        },
        "as_of": dates[-1],
        "stats": stats_by_mode[rebalance],
        "rebalance_comparison": comparison,
        "series": {
            "equity": _downsample(list(zip(dates, equity))),
            "benchmark_equity": (
                _downsample(list(zip(dates, bench_equity))) if bench_equity else []
            ),
            "drawdown": _downsample(list(zip(dates, dd["drawdown_series"]))),
            "rolling_vol": _downsample(rolling_vol(dates, returns)),
        },
        "position_stats": position_stats(dates, closes, weights),
        "diversification": diversification(weights, returns_by_ticker),
        "strategy_overlays": overlays,
        "warnings": warnings,
        "params": {
            "level": level,
            "rf_annual": rf_annual,
            "rebalance": rebalance,
            "cost_bps": cost_bps,
            "strategies": chosen_strategies,
            "horizon": horizon,
            "benchmark": benchmark,
        },
    }
    return _json_safe(result)
