"""Plain-language glossary and methodology notes for reports and the Memo tab.

Pure strings — no LLM imports. :func:`find_terms` scans text for whole-word
aliases so a report only explains the jargon it actually uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    aliases: Tuple[str, ...]
    plain: str
    how_calculated: str


def _e(term: str, aliases: Tuple[str, ...], plain: str, how: str) -> GlossaryEntry:
    return GlossaryEntry(term, (term,) + aliases, plain, how)


GLOSSARY: Dict[str, GlossaryEntry] = {
    e.term: e
    for e in (
        _e(
            "VaR",
            ("value at risk", "value-at-risk", "historical VaR", "parametric VaR"),
            "Value at Risk: a loss you should only exceed on rare days — e.g. a 99% "
            "one-day VaR of 2% means roughly 1 day in 100 loses more than 2%.",
            "Historical VaR is the 1st percentile of past daily returns (linear "
            "interpolation); parametric VaR assumes a normal curve: -(mean + z × "
            "standard deviation).",
        ),
        _e(
            "Expected Shortfall",
            ("ES", "CVaR", "conditional VaR"),
            "The average loss on the worst days — what a bad day looks like once "
            "the VaR line is crossed.",
            "Mean of the daily returns at or below the VaR quantile, shown as a "
            "positive loss.",
        ),
        _e(
            "max drawdown",
            ("maximum drawdown", "drawdown", "drawdowns", "max DD"),
            "The biggest fall from a previous high to a later low — how much you "
            "would have been down at the worst point.",
            "Track the running peak of the value curve; the largest "
            "(peak − value) / peak is the maximum drawdown.",
        ),
        _e(
            "annualised volatility",
            ("volatility", "annualized volatility", "vol", "ann vol"),
            "How much returns swing around their average over a year; higher means "
            "a bumpier ride.",
            "Standard deviation of daily returns × √252 (trading days per year).",
        ),
        _e(
            "Sharpe ratio",
            ("Sharpe",),
            "Return earned per unit of risk taken; above 1 is generally considered "
            "good.",
            "(Annual growth rate − risk-free rate) ÷ annualised volatility.",
        ),
        _e(
            "Sortino ratio",
            ("Sortino",),
            "Like Sharpe, but only counts the downside swings as risk.",
            "(Annual growth rate − risk-free rate) ÷ annualised downside deviation "
            "(volatility of below-target daily returns only).",
        ),
        _e(
            "Calmar ratio",
            ("Calmar",),
            "Annual growth compared with the worst fall — how well the return paid "
            "for the deepest loss.",
            "Annual growth rate (CAGR) ÷ maximum drawdown.",
        ),
        _e(
            "CAGR",
            ("compound annual growth rate", "annualized return", "annualised return"),
            "The steady yearly growth rate that would turn the starting value into "
            "the ending value.",
            "(End value ÷ start value)^(252 ÷ number of trading days) − 1.",
        ),
        _e(
            "beta",
            (),
            "How strongly the investment moves with the benchmark: 1 means in step, "
            "above 1 amplifies its moves, below 1 dampens them.",
            "Covariance of daily returns with the benchmark ÷ variance of the "
            "benchmark's daily returns.",
        ),
        _e(
            "correlation",
            ("correlated",),
            "How closely two investments rise and fall together, from -1 (opposite) "
            "to +1 (in lockstep).",
            "Pearson correlation of daily returns.",
        ),
        _e(
            "tracking error",
            (),
            "How far the investment's returns stray from the benchmark's over a "
            "year.",
            "Standard deviation of (portfolio − benchmark) daily returns × √252.",
        ),
        _e(
            "information ratio",
            (),
            "Extra growth over the benchmark per unit of tracking error.",
            "(Portfolio CAGR − benchmark CAGR) ÷ tracking error.",
        ),
        _e(
            "SMA",
            ("simple moving average", "moving average", "50-day SMA", "200-day SMA"),
            "The average closing price over the last N days, used to see the trend.",
            "Sum of the last N closes ÷ N.",
        ),
        _e(
            "EMA",
            ("exponential moving average",),
            "A moving average that gives more weight to recent prices.",
            "Weighted average where each older close counts a constant fraction "
            "less.",
        ),
        _e(
            "RSI",
            ("relative strength index",),
            "A 0-100 gauge of recent buying vs selling pressure; above 70 is often "
            "called stretched, below 30 washed out.",
            "100 − 100 ÷ (1 + average gain ÷ average loss) over 14 periods.",
        ),
        _e(
            "MACD",
            ("moving average convergence divergence",),
            "A trend-momentum gauge comparing a fast and a slow moving average.",
            "12-period EMA − 26-period EMA, compared with its own 9-period EMA "
            "(the signal line).",
        ),
        _e(
            "Bollinger Bands",
            ("Bollinger",),
            "A price channel around a moving average that widens when markets get "
            "jumpy.",
            "20-period SMA ± 2 standard deviations of the closes.",
        ),
        _e(
            "basis points",
            ("bps", "bp", "basis point"),
            "Hundredths of a percentage point: 100 basis points = 1%.",
            "1 bp = 0.01%.",
        ),
        _e(
            "duration",
            (),
            "How sensitive a bond's price is to interest-rate changes; a duration "
            "of 7 means roughly a 7% price fall if rates rise by 1 point.",
            "Weighted-average time to the bond's cash flows (modified duration ≈ "
            "% price change per 1% rate change).",
        ),
        _e(
            "credit spread",
            ("spread", "spreads", "credit spreads"),
            "The extra interest a riskier borrower pays over a government bond — "
            "wider spreads mean lenders see more risk.",
            "Yield of the corporate bond − yield of a comparable government bond.",
        ),
        _e(
            "conviction",
            ("confidence",),
            "How strongly a specialist (or the committee) holds its view, on a 1-5 "
            "scale.",
            "Self-reported by each model on a 1 (low) to 5 (high) scale; 0 means "
            "the step failed.",
        ),
        _e(
            "bull/bear case",
            ("bull case", "bear case", "bullish", "bearish"),
            "The optimistic (bull) and pessimistic (bear) arguments for an "
            "investment.",
            "Argued by two dedicated researcher agents, then refereed by the CIO.",
        ),
        _e(
            "rebalancing",
            ("rebalance", "rebalanced", "rebalancing comparison"),
            "Periodically resetting holdings back to their target weights.",
            "On each rebalance date the portfolio value is re-split by target "
            "weight; between dates weights drift with prices.",
        ),
        _e(
            "buy-and-hold",
            ("buy and hold",),
            "Buying once and never trading again; weights drift with prices.",
            "Each holding grows with its own price from the start date.",
        ),
        _e(
            "benchmark",
            (),
            "A reference investment (e.g. the S&P 500 fund SPY) used to judge "
            "performance.",
            "Its price series is aligned to the same dates as the portfolio.",
        ),
        _e(
            "yield curve",
            ("2s10s",),
            "Interest rates on government bonds from short to long maturities; an "
            "upward slope usually signals normal growth expectations.",
            "Plot of government bond yields by maturity; the 2s10s slope is the "
            "10-year yield − 2-year yield.",
        ),
    )
}

METHODOLOGY: List[Tuple[str, str]] = [
    (
        "Returns and annualisation",
        "Daily simple returns are close-to-close changes. Yearly figures assume 252 "
        "trading days: volatility is scaled by √252 and the compound annual growth "
        "rate (CAGR) is (end ÷ start)^(252 ÷ days) − 1.",
    ),
    (
        "Historical VaR",
        "The empirical 1st percentile (at 99% confidence) of past daily returns, "
        "using linear interpolation between neighbouring observations; reported as "
        "a positive loss.",
    ),
    (
        "Parametric VaR",
        "Assumes returns follow a normal curve: -(mean + z × standard deviation), "
        "with z the normal quantile at (1 − confidence).",
    ),
    (
        "Expected Shortfall",
        "The mean of the daily returns at or below the historical VaR quantile, "
        "reported as a positive loss.",
    ),
    (
        "10-day VaR",
        "The 1-day historical VaR × √10. This square-root-of-time scaling is an "
        "approximation that assumes independent days; real multi-day losses can be "
        "larger.",
    ),
    (
        "Drawdown",
        "The peak-to-trough fall of the value curve: at each date, (running peak − "
        "value) ÷ running peak. The maximum drawdown is the largest such fall, with "
        "its peak, trough and recovery dates.",
    ),
    (
        "Sharpe, Sortino and Calmar",
        "Sharpe = (CAGR − risk-free rate) ÷ annualised volatility. Sortino uses the "
        "downside deviation (only below-target days) instead of volatility. Calmar = "
        "CAGR ÷ maximum drawdown.",
    ),
    (
        "Beta, tracking error and information ratio",
        "Beta = covariance with the benchmark ÷ benchmark variance. Tracking error = "
        "standard deviation of (portfolio − benchmark) daily returns × √252. "
        "Information ratio = (portfolio CAGR − benchmark CAGR) ÷ tracking error.",
    ),
    (
        "Buy-and-hold vs rebalancing",
        "Buy-and-hold lets weights drift with prices. Monthly rebalancing resets to "
        "target weights on the first trading day of each month; daily rebalancing "
        "keeps a constant mix. Trading costs are not deducted from rebalancing.",
    ),
    (
        "Strategy backtests",
        "Rule-based long/flat strategies use indicators computed on closes; a signal "
        "on day t earns the return from t to t+1 (one-bar shift, no look-ahead). "
        "Historical simulation only — past results do not predict future returns.",
    ),
    (
        "Data",
        "Prices come from Yahoo Finance via the yfinance library and a local cache. "
        "Holdings are aligned on the dates they all traded; other dates are dropped.",
    ),
]

_PATTERNS: Dict[str, List[re.Pattern]] = {
    term: [
        re.compile(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", re.I)
        for alias in entry.aliases
    ]
    for term, entry in GLOSSARY.items()
}


def find_terms(*texts: str) -> List[GlossaryEntry]:
    """Return glossary entries whose aliases appear as whole words in ``texts``."""
    blob = "\n".join(str(t) for t in texts if t)
    if not blob:
        return []
    return [
        GLOSSARY[term]
        for term, patterns in _PATTERNS.items()
        if any(p.search(blob) for p in patterns)
    ]


def entries(terms: List[str]) -> List[GlossaryEntry]:
    """Return the entries for ``terms`` (unknown names are skipped)."""
    return [GLOSSARY[t] for t in terms if t in GLOSSARY]
