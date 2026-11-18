"""Shared helpers for the backtest research notebooks under ``notebooks/backtest/``.

Notebooks add this folder to ``sys.path`` and import from here: plotly renderer,
repo root / cache / yfinance session, Yahoo data loading, T-bill returns, the
long/flat backtest engine (any 0/1 signal), performance stats, the per-decision
panel and the inference helpers (Newey-West, block bootstrap).

Research / decision-support only: simulates holding an equity ETF or T-bills on
historical data and never places orders. Not part of the installed package.
"""

from __future__ import annotations

import math
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.io as pio
import yfinance as yf
from plotly.io._base_renderers import MimetypeRenderer
from plotly.offline import get_plotlyjs, get_plotlyjs_version

# ---------------------------------------------------------------------------
# Environment: repo root, cache, yfinance session, plotly renderer
# ---------------------------------------------------------------------------


def find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists():
            return p
    return start


REPO_ROOT = find_repo_root(Path(__file__).resolve().parent)
CACHE_DIR = REPO_ROOT / ".cache" / "notebooks"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _build_session():
    # Corporate TLS inspection: reuse the app's yfinance session settings
    # (REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE / INVESTMENT_FIRM_MARKET_VERIFY_SSL from env or .env).
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    try:
        from investment_firm.interfaces.web.market_data import (
            _build_yfinance_session,
        )

        return _build_yfinance_session()
    except ImportError:
        return None


SESSION = _build_session()

# "cdn" = load plotly.js from cdn.plot.ly | "inline" = embed it (offline, ~4.6 MB per chart)
PLOTLY_JS = "cdn"


class HtmlRenderer(MimetypeRenderer):
    """fig.show() emits plain HTML, so charts render in VS Code without the
    "Jupyter Notebook Renderers" extension (which handles plotly's
    application/vnd.plotly.v1+json output)."""

    def to_mimebundle(self, fig_dict):
        div_id = f"fig-{uuid.uuid4().hex}"
        height = fig_dict.get("layout", {}).get("height") or 450
        cdn = f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js"
        inline = f"<script>{get_plotlyjs()}</script>" if PLOTLY_JS == "inline" else ""
        html = f"""{inline}<div id="{div_id}" style="width:100%;height:{height}px;"></div>
<script>(function () {{
  var fig = {pio.to_json(fig_dict)};
  function draw() {{ Plotly.newPlot("{div_id}", fig.data, fig.layout, {{responsive: true}}); }}
  if (window.Plotly) {{ draw(); return; }}
  var s = document.createElement("script");
  s.src = "{cdn}";
  s.onload = draw;
  s.onerror = function () {{ document.getElementById("{div_id}").innerText =
    "Could not load plotly.js from the CDN - call setup_plotly('inline') in the setup cell."; }};
  document.head.appendChild(s);
}})();</script>"""
        return {"text/html": html}


def setup_plotly(plotly_js: str = "cdn") -> None:
    """Register the HTML renderer as default and use the plotly_white template."""
    global PLOTLY_JS
    if plotly_js not in ("cdn", "inline"):
        raise ValueError(f"plotly_js must be 'cdn' or 'inline'; got {plotly_js!r}")
    PLOTLY_JS = plotly_js
    pio.templates.default = "plotly_white"
    pio.renderers["vscode_html"] = HtmlRenderer()
    pio.renderers.default = "vscode_html"


def pct(x, d=2):
    return "" if pd.isna(x) else f"{x:.{d}%}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_history(
    ticker: str, refresh: bool = False, max_age_hours: float = 12
) -> pd.DataFrame:
    """Full daily history from Yahoo Finance, cached under .cache/notebooks/."""
    path = CACHE_DIR / f"{ticker.replace('^', 'IDX_')}_1d.pkl"
    fresh = (
        path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600
    )
    if fresh and not refresh:
        return pd.read_pickle(path)
    tk = (
        yf.Ticker(ticker, session=SESSION) if SESSION is not None else yf.Ticker(ticker)
    )
    hist = tk.history(period="max", interval="1d", auto_adjust=False, timeout=30)
    if hist is None or hist.empty:
        raise RuntimeError(f"no data returned for {ticker}")
    hist.index = pd.DatetimeIndex(hist.index).tz_localize(None).normalize()
    hist = hist[~hist.index.duplicated(keep="last")].sort_index()
    hist.to_pickle(path)
    return hist


def fetch_file(
    urls, path: Path, max_age_days: float = 30, refresh: bool = False
) -> Path:
    """Download the first reachable URL to ``path`` (cached for ``max_age_days``)."""
    if (
        path.exists()
        and not refresh
        and (time.time() - path.stat().st_mtime) < max_age_days * 86400
    ):
        return path
    last_err = None
    for url in urls:
        try:
            if SESSION is not None:
                r = SESSION.get(url, timeout=60)
            else:
                import requests

                r = requests.get(url, timeout=60)
            r.raise_for_status()
            path.write_bytes(r.content)
            return path
        except Exception as exc:  # try the next mirror
            last_err = exc
    if path.exists():
        print(f"download failed ({last_err!r}); using cached {path.name}")
        return path
    raise RuntimeError(f"could not download {path.name}: {last_err!r}")


def total_return_frame(hist: pd.DataFrame) -> pd.DataFrame:
    adj = (hist["Adj Close"] / hist["Close"]).replace([np.inf, -np.inf], np.nan).ffill()
    return pd.DataFrame(
        {
            "open": hist["Open"],
            "close": hist["Close"],
            "tr_open": hist["Open"] * adj,  # dividend-adjusted open
            "tr_close": hist["Adj Close"],
        }
    ).dropna()


def cash_returns(
    index: pd.DatetimeIndex,
    field: str,
    source: str,
    irx: pd.Series,
    bil_px: pd.DataFrame | None = None,
) -> pd.Series:
    """Risk-off return per interval (previous bar -> this bar), same convention as the equity leg.

    ``source``: ``irx`` (13-week T-bill yield accrual), ``bil`` (BIL ETF, ``irx`` before 2007)
    or ``zero`` (plain cash).
    """
    if source == "zero":
        return pd.Series(0.0, index=index)
    days = pd.Series(index, index=index).diff().dt.days
    lag = (
        2 if field == "tr_open" else 1
    )  # use only a yield published before the interval starts
    yld = irx.reindex(index.union(irx.index)).ffill().reindex(index).shift(lag)
    r_irx = (1 + yld / 100.0) ** (days / 365.0) - 1
    if source == "irx":
        return r_irx
    if source == "bil":
        r_bil = bil_px[field].reindex(index).pct_change(fill_method=None)
        return r_bil.combine_first(r_irx)
    raise ValueError(f"unknown cash source {source!r}")


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

EXECUTIONS = {
    # name: (price field for returns, signal lag in bars)
    "next_open": ("tr_open", 2),
    "next_close": ("tr_close", 2),
    "same_close": ("tr_close", 1),
}
REBALANCE_FREQ = {
    "daily": None,
    "weekly": "W-FRI",
    "monthly": "M",
    "quarterly": "Q",
    "yearly": "Y",
}


def check_days(index: pd.DatetimeIndex, rebalance: str) -> pd.Series:
    """True on the dates where the rule is evaluated: every bar, or the last bar of each period."""
    freq = REBALANCE_FREQ[rebalance]
    if freq is None:
        return pd.Series(True, index=index)
    per = index.to_period(freq)
    is_last = np.empty(len(index), dtype=bool)
    is_last[:-1] = per[1:] != per[:-1]
    # Latest bar: a period end only if the next business day falls into a new period.
    is_last[-1] = (index[-1] + pd.offsets.BDay(1)).to_period(freq) != per[-1]
    return pd.Series(is_last, index=index)


def backtest_signal(
    px: pd.DataFrame,
    signal: pd.Series,
    cash,
    cost_bps: float = 0.0,
    execution: str = "next_open",
    start=None,
    rebalance: str = "daily",
    extra: dict | None = None,
) -> pd.DataFrame:
    """Long/flat backtest of a 0/1 ``signal`` (1 = equity, 0 = T-bills, NaN = unknown).

    The signal is read only on check dates (see :func:`check_days`); the first valid
    signal always enters. ``cash`` is a Series or a ``{price field: Series}`` dict.
    ``extra`` columns (e.g. the SMA) are inserted after ``close`` for plotting.
    """
    field, lag = EXECUTIONS[execution]
    cash_s = cash[field] if isinstance(cash, dict) else cash
    close = px["close"]
    signal = signal.reindex(close.index)
    check = check_days(close.index, rebalance) & signal.notna()
    check.loc[signal.first_valid_index()] = True  # enter on the first valid signal
    target = signal.where(check).ffill()  # position decided at the last check date
    df = pd.DataFrame(
        {
            "close": close,
            **(extra or {}),
            "signal": signal,
            "check": check,
            "target": target,
            "pos": target.shift(lag),
            "r_eq": px[field].pct_change(fill_method=None),
            "r_cash": cash_s,
        }
    )
    if start is not None:
        df = df.loc[start:]
    df = df.dropna(subset=["pos", "r_eq", "r_cash"]).copy()
    df["turnover"] = df["pos"].diff().abs()
    df.iloc[0, df.columns.get_loc("turnover")] = df["pos"].iloc[0]  # initial entry
    df["cost"] = df["turnover"] * cost_bps / 1e4
    df["r_gross"] = df["pos"] * df["r_eq"] + (1 - df["pos"]) * df["r_cash"]
    df["r_strat"] = df["r_gross"] - df["cost"]
    df["r_bh"] = df["r_eq"]
    return df


def sma_signal(close: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    """(signal, sma): 1 while the close is above its ``window``-bar SMA, NaN during warm-up."""
    sma = close.rolling(window, min_periods=window).mean()
    return (close > sma).astype(float).where(sma.notna()), sma


def sma_backtest(
    px,
    cash,
    window=30,
    cost_bps=0.0,
    execution="next_open",
    start=None,
    rebalance="daily",
) -> pd.DataFrame:
    """Price-vs-SMA rule: hold equity while the close is above its SMA, T-bills otherwise."""
    signal, sma = sma_signal(px["close"], window)
    return backtest_signal(
        px, signal, cash, cost_bps, execution, start, rebalance, extra={"sma": sma}
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def perf_stats(ret: pd.Series, rf: pd.Series) -> dict:
    ret = ret.dropna()
    rf = rf.reindex(ret.index).fillna(0.0)
    eq = (1 + ret).cumprod()
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / years) - 1
    ex = ret - rf
    ann = 252
    sharpe = ex.mean() / ex.std() * math.sqrt(ann) if ex.std() > 0 else np.nan
    downside = math.sqrt((np.minimum(ex, 0) ** 2).mean()) * math.sqrt(ann)
    dd = eq / eq.cummax() - 1
    max_dd = dd.min()
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    after = eq.loc[trough:]
    rec = after[after >= eq.loc[peak]]
    return {
        "CAGR": cagr,
        "Vol": ret.std() * math.sqrt(ann),
        "Sharpe": sharpe,
        "Sortino": ex.mean() * ann / downside if downside > 0 else np.nan,
        "Max DD": max_dd,
        "Calmar": (
            cagr / abs(max_dd) if max_dd < -1e-3 else np.nan
        ),  # undefined for ~zero drawdown
        "Worst day": ret.min(),
        "MaxDD peak": peak.date(),
        "MaxDD recovered": rec.index[0].date() if len(rec) and max_dd < 0 else "-",
        "Final x": eq.iloc[-1],
    }


def strategy_stats(df: pd.DataFrame) -> dict:
    years = (df.index[-1] - df.index[0]).days / 365.25
    switches = int((df["turnover"] > 0).sum())
    return {
        "Time in market": df["pos"].mean(),
        "Switches": switches,
        "Switches / yr": switches / years,
        "Cost drag / yr": df["cost"].sum() / years,
    }


def trade_log(
    df: pd.DataFrame, px: pd.DataFrame, execution: str = "next_open"
) -> pd.DataFrame:
    # A position that starts earning on row d was filled at the previous bar's open (next_open) or close.
    price_col = "open" if execution == "next_open" else "close"
    rows = []
    for d in df.index[df["turnover"] > 0]:
        fill_day = px.index[px.index.get_loc(d) - 1]
        rows.append(
            {
                "filled": fill_day,
                "action": "BUY equity" if df.at[d, "pos"] == 1 else "SELL -> T-bills",
                "fill price": round(px.at[fill_day, price_col], 2),
            }
        )
    return pd.DataFrame(rows, columns=["filled", "action", "fill price"])


# ---------------------------------------------------------------------------
# Decision panel and inference
# ---------------------------------------------------------------------------


def decision_panel(
    bt: pd.DataFrame, lag: int, extra: dict | None = None
) -> pd.DataFrame:
    """One row per decision: signal at the check date, then the equity / T-bill / excess
    return over the holding period that follows (fill to next fill).

    Cut directly from the daily backtest rows, so the periods are exactly the strategy's
    holding periods. ``extra`` series are read at the decision dates (inserted after ``state``).
    """
    # Row t earns the position chosen at the latest check day at or before t - lag.
    gov = bt["check"].astype(int).cumsum().shift(lag)
    check_dates = bt.index[bt["check"].to_numpy()]
    tmp = pd.DataFrame(
        {
            "gov": gov,
            "date": bt.index,
            "l_eq": np.log1p(bt["r_eq"]),
            "l_cash": np.log1p(bt["r_cash"]),
        }
    ).dropna()
    tmp = tmp[tmp["gov"] > 0]
    g = tmp.groupby("gov").agg(
        start=("date", "first"),
        end=("date", "last"),
        days=("date", "size"),
        l_eq=("l_eq", "sum"),
        l_cash=("l_cash", "sum"),
    )
    g = g.iloc[
        1:-1
    ]  # drop the first (forced initial entry) and the last (still open) period
    dec = check_dates[g.index.astype(int) - 1]
    cols = {
        "decision": dec,
        "hold_from": g["start"].to_numpy(),  # first interval earning the new position
        "hold_to": g["end"].to_numpy(),
        "state": bt["signal"].reindex(dec).to_numpy(),
    }
    for name, series in (extra or {}).items():
        cols[name] = series.reindex(dec).to_numpy()
    cols["r_eq"] = np.expm1(g["l_eq"].to_numpy())
    cols["r_tbill"] = np.expm1(g["l_cash"].to_numpy())
    out = pd.DataFrame(cols)
    out["excess"] = out["r_eq"] - out["r_tbill"]
    assert (
        out["hold_from"] > out["decision"]
    ).all(), "look-ahead: holding period must start after the decision"
    return out.set_index("decision")


def block_indices(n, n_boot, block, rng):
    """Moving-block bootstrap indices (keeps regime persistence and vol clustering)."""
    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[
        :, :n
    ]
    return idx.astype(np.int32)


def newey_west(y, X, lags):
    """OLS coefficients with Newey-West (Bartlett) HAC standard errors."""
    y, X = np.asarray(y, float), np.asarray(X, float)
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    xu = X * (y - X @ beta)[:, None]
    S = xu.T @ xu
    for l in range(1, lags + 1):
        G = xu[l:].T @ xu[:-l]
        S += (1 - l / (lags + 1)) * (G + G.T)
    V = xtx_inv @ S @ xtx_inv
    return beta, np.sqrt(np.diag(V))


# ---------------------------------------------------------------------------
# Phase B additions live in small sibling modules; re-exported here so existing
# notebooks keep a single ``import bt_common as bc`` entry point.  Each import is
# guarded so bt_common still works if a sibling is missing (e.g. copied alone).
# ---------------------------------------------------------------------------
for _mod in ("bt_long", "bt_periods", "bt_pit", "bt_stats", "bt_ml", "bt_registry"):
    try:
        _m = __import__(_mod)
    except ImportError:  # pragma: no cover - sibling not on sys.path
        continue
    for _name in getattr(_m, "__all__", ()):
        globals().setdefault(_name, getattr(_m, _name))
del _mod, _m, _name
