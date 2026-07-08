"""Rule-based strategy backtester over the shared indicator engine.

Signals come from :mod:`investment_firm.data.indicators` (the same whitelisted
stockstats catalog that feeds the web charts and ``get_indicators``), so a
backtested rule always agrees with the values an analyst can see plotted.

Historical compute only — long/flat position simulation on closes, no orders,
no portfolio state, never a trade instruction. Network-free by design: every
function takes an OHLCV ``pandas`` DataFrame; fetching lives in the callers.

No-lookahead convention: the signal computed on day ``t`` earns the return
from ``t`` to ``t+1`` (positions are shifted by one bar).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import indicators
from .risk import returns_from_prices, risk_summary

# Curated strategy catalog: name -> human description (shown in tool schemas).
STRATEGIES: Dict[str, str] = {
    "sma_crossover": (
        "Long while the 50-period SMA is above the 200-period SMA (golden-cross "
        "regime), flat otherwise."
    ),
    "macd_crossover": (
        "Long while the MACD line is above its signal line, flat otherwise."
    ),
    "rsi_reversion": (
        "Mean reversion: enter long when RSI(14) drops below 30, exit when it "
        "rises above 70."
    ),
    "bollinger_reversion": (
        "Mean reversion: enter long when the close falls below the lower "
        "Bollinger band, exit when it recovers above the middle band."
    ),
}

_TRADING_DAYS = 252.0
_ROUND_DP = 4


class BacktestError(ValueError):
    """Raised for unknown strategies or uncomputable input."""


def available_strategies() -> Dict[str, str]:
    """Return a copy of the strategy catalog (name -> description)."""
    return dict(STRATEGIES)


def _above(fast: List[Optional[float]], slow: List[Optional[float]]) -> List[int]:
    """1 while ``fast > slow`` (missing values are flat)."""
    return [
        1 if (f is not None and s is not None and f > s) else 0
        for f, s in zip(fast, slow)
    ]


def _threshold_state(
    trigger: List[Optional[float]],
    enter_below: List[Optional[float]],
    exit_above: List[Optional[float]],
) -> List[int]:
    """Stateful long/flat: enter when trigger < enter_below, exit when > exit_above."""
    signals: List[int] = []
    in_market = False
    for value, low, high in zip(trigger, enter_below, exit_above):
        if value is not None:
            if not in_market and low is not None and value < low:
                in_market = True
            elif in_market and high is not None and value > high:
                in_market = False
        signals.append(1 if in_market else 0)
    return signals


def _signals(df, strategy: str) -> List[int]:
    """Return the 0/1 long/flat signal series for ``strategy`` over ``df``."""
    closes = [float(v) for v in df["Close"].tolist()]
    if strategy == "sma_crossover":
        series = indicators.compute(df, ["close_50_sma", "close_200_sma"])
        return _above(series["close_50_sma"], series["close_200_sma"])
    if strategy == "macd_crossover":
        series = indicators.compute(df, ["macd", "macds"])
        return _above(series["macd"], series["macds"])
    if strategy == "rsi_reversion":
        rsi = indicators.compute(df, ["rsi"])["rsi"]
        return _threshold_state(rsi, [30.0] * len(rsi), [70.0] * len(rsi))
    if strategy == "bollinger_reversion":
        series = indicators.compute(df, ["boll", "boll_lb"])
        return _threshold_state(closes, series["boll_lb"], series["boll"])
    raise BacktestError(
        f"unknown strategy {strategy!r}; valid: {', '.join(sorted(STRATEGIES))}"
    )


def _annualize(total_return: float, n_returns: int) -> float:
    return (1.0 + total_return) ** (_TRADING_DAYS / max(n_returns, 1)) - 1.0


def run_strategy(
    df,
    strategy: str,
    *,
    cost_bps: float = 0.0,
    level: float = 0.99,
) -> Dict[str, object]:
    """Backtest ``strategy`` long/flat on ``df`` closes; return raw fractions.

    ``cost_bps`` is deducted from the strategy return on every position change
    (one side per change). Risk metrics are computed on the strategy's equity
    curve via :func:`investment_firm.data.risk.risk_summary`; a buy-and-hold
    benchmark over the same window is included for comparison.
    """
    if strategy not in STRATEGIES:
        raise BacktestError(
            f"unknown strategy {strategy!r}; valid: {', '.join(sorted(STRATEGIES))}"
        )
    if df is None or getattr(df, "empty", True) or len(df) < 3:
        raise BacktestError("insufficient price history to backtest")

    try:
        signals = _signals(df, strategy)
    except indicators.IndicatorError as exc:
        raise BacktestError(str(exc)) from exc

    closes = [float(v) for v in df["Close"].tolist()]
    rets = returns_from_prices(closes)  # rets[i] = close[i+1]/close[i] - 1
    positions = signals[:-1]  # signal on day t earns the t -> t+1 return
    cost = max(float(cost_bps), 0.0) / 10_000.0

    equity = [1.0]
    n_trades = 0
    prev_pos = 0
    for pos, ret in zip(positions, rets):
        step = pos * ret
        if pos != prev_pos:
            n_trades += 1
            step -= cost
        equity.append(equity[-1] * (1.0 + step))
        prev_pos = pos
    if prev_pos != 0:  # close the final open position (exit cost)
        n_trades += 1
        equity[-1] *= 1.0 - cost

    total_return = equity[-1] - 1.0
    benchmark_total = closes[-1] / closes[0] - 1.0 if closes[0] else 0.0
    summary = risk_summary(equity, level=level)

    return {
        "strategy": strategy,
        "rule": STRATEGIES[strategy],
        "n_obs": len(rets),
        "total_return": round(total_return, _ROUND_DP),
        "annualized_return": round(_annualize(total_return, len(rets)), _ROUND_DP),
        "benchmark_total_return": round(benchmark_total, _ROUND_DP),
        "benchmark_annualized_return": round(
            _annualize(benchmark_total, len(rets)), _ROUND_DP
        ),
        "n_trades": n_trades,
        "time_in_market": round(
            sum(positions) / len(positions) if positions else 0.0, _ROUND_DP
        ),
        "cost_bps": float(cost_bps),
        "ann_vol": summary["ann_vol"],
        "max_drawdown": summary["max_drawdown"],
        "hist_var_1d": summary["hist_var_1d"],
        "es_1d": summary["es_1d"],
        "var_level": summary["var_level"],
    }
