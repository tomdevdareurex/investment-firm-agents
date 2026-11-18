"""Long-history data loaders for the Stage 1 backtest programme (notebooks/backtest/).

Ports the long S&P 500 sample construction of ``sma/sma200_regime_analysis.ipynb``
into reusable functions: Shiller monthly data (P, D, E, CPI, GS10, CAPE), keyless
FRED series, a synthetic S&P 500 total-return series (price + Shiller dividends until
^SP500TR starts in 1988) and a 1934+ T-bill yield series (FRED TB3MS spliced with ^IRX).

Research / decision-support only. Never places orders.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bt_common import CACHE_DIR, fetch_file, load_history

SHILLER_URLS = [
    "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/downloads/ie_data.xls",
    "http://www.econ.yale.edu/~shiller/data/ie_data.xls",
]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

# Shiller ie_data.xls "Data" sheet column positions (header rows skipped).
_SHILLER_COLS = {0: "date", 1: "P", 2: "D", 3: "E", 4: "CPI", 6: "GS10", 12: "CAPE"}


def _requests_fallback(url: str, path: Path) -> Path:
    """Plain ``requests`` download without TLS verification (corporate proxy hosts).

    Only used when the shared curl_cffi session fails and no cache exists.
    """
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = requests.get(url, timeout=60, verify=False)
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def fetch_file_lenient(urls, path: Path, max_age_days: float = 30, refresh=False):
    """``fetch_file`` with a verify=False ``requests`` fallback when every mirror fails."""
    try:
        return fetch_file(urls, path, max_age_days=max_age_days, refresh=refresh)
    except RuntimeError:
        last = None
        for url in urls:
            try:
                return _requests_fallback(url, path)
            except Exception as exc:  # try next mirror
                last = exc
        raise RuntimeError(f"could not download {path.name}: {last!r}")


def shiller_period_index(date_col: pd.Series) -> pd.PeriodIndex:
    """Shiller dates are ``year.month`` floats (1871.1 == 1871.10)."""
    f = date_col.astype(float)
    year = f.astype(int)
    month = ((f - year) * 100).round().astype(int)
    return pd.PeriodIndex.from_fields(year=year, month=month, freq="M")


def load_shiller(refresh: bool = False, max_age_days: float = 30) -> pd.DataFrame:
    """Shiller monthly data: P, D (annual dividend rate), E (annual earnings rate),
    CPI, GS10, CAPE. Monthly ``PeriodIndex``; footnote rows dropped."""
    path = fetch_file_lenient(
        SHILLER_URLS, CACHE_DIR / "shiller_ie_data.xls", max_age_days, refresh
    )
    raw = pd.read_excel(
        path, sheet_name="Data", header=None, skiprows=8, usecols=list(_SHILLER_COLS)
    )
    raw.columns = [_SHILLER_COLS[c] for c in raw.columns]
    raw = raw[pd.to_numeric(raw["date"], errors="coerce").notna()]
    raw = raw[pd.to_numeric(raw["P"], errors="coerce").notna()]
    out = raw.drop(columns="date").apply(pd.to_numeric, errors="coerce")
    out.index = shiller_period_index(raw["date"])
    return out[~out.index.duplicated(keep="last")].sort_index()


def fred_series(sid: str, refresh: bool = False, max_age_days: float = 7) -> pd.Series:
    """Keyless FRED csv download -> float Series indexed by observation date."""
    path = fetch_file_lenient(
        [FRED_CSV.format(sid=sid)], CACHE_DIR / f"fred_{sid}.csv", max_age_days, refresh
    )
    df = pd.read_csv(path)
    s = pd.Series(
        pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(),
        index=pd.to_datetime(df.iloc[:, 0]),
        name=sid,
    )
    return s.dropna().sort_index()


def load_long_sp500_tr(refresh: bool = False) -> pd.DataFrame:
    """Daily S&P 500 price (``close``) and total-return (``tr_close``) since 1927.

    Total return = ^SP500TR where available (1988+); before that, synthetic
    ``(P_t + D_annual/252) / P_{t-1} - 1`` using Shiller's annual dividend rate
    (month-end known value, forward-filled). Validation 1989-2023 vs the official
    index: mean annual difference -0.06 %, tracking error 0.10 %.
    """
    gspc = load_history("^GSPC", refresh=refresh)["Close"]
    sptr = load_history("^SP500TR", refresh=refresh)["Close"]
    div_annual = load_shiller(refresh=refresh)["D"].astype(float)
    d_daily = div_annual.reindex(gspc.index.to_period("M")).ffill().to_numpy()
    r_syn = (gspc + d_daily / 252) / gspc.shift(1) - 1
    r_off = sptr.pct_change(fill_method=None).reindex(gspc.index)
    splice = sptr.index[1]
    r_tr = r_syn.where(gspc.index < splice, r_off).dropna()
    px = pd.DataFrame({"close": gspc, "tr_close": (1 + r_tr).cumprod()}).dropna()
    px["tr_close"] /= px["tr_close"].iloc[0]
    px.attrs["splice_date"] = splice
    return px


def load_long_tbill_yield(refresh: bool = False) -> pd.Series:
    """Daily 3-month T-bill yield (%, bond-equivalent) 1934+.

    FRED TB3MS (monthly average, known at the start of the following month) spliced
    with ^IRX (daily) from the first ^IRX observation onwards.
    """
    tb = fred_series("TB3MS", refresh=refresh)
    tb_known = pd.Series(
        tb.to_numpy(), index=tb.index + pd.offsets.MonthBegin(1), name="yield"
    )
    irx = load_history("^IRX", refresh=refresh)["Close"].rename("yield")
    yld = pd.concat([tb_known[tb_known.index < irx.index[0]], irx]).sort_index()
    return yld[~yld.index.duplicated(keep="last")]


def long_cash_returns(index: pd.DatetimeIndex, yld: pd.Series) -> pd.Series:
    """Daily T-bill return for each interval ending at ``index[t]``: the yield known at
    the previous bar compounded over the calendar days of the interval."""
    days = pd.Series(index, index=index).diff().dt.days
    y = yld.reindex(index.union(yld.index)).ffill().reindex(index).shift(1)
    return ((1 + y / 100) ** (days / 365) - 1).rename("r_cash")


def long_sample(start: str = "1934-01-01", refresh: bool = False) -> dict:
    """Convenience bundle: ``px`` (close/tr_close), ``cash`` (daily T-bill return),
    ``yld`` (daily yield %) and ``shiller`` (monthly), all from ``start``."""
    px = load_long_sp500_tr(refresh=refresh)
    yld = load_long_tbill_yield(refresh=refresh)
    px = px[px.index >= max(pd.Timestamp(start), yld.index[0])]  # cash must be known
    cash = long_cash_returns(px.index, yld)
    return {"px": px, "cash": cash, "yld": yld, "shiller": load_shiller(refresh)}


def shiller_to_daily(monthly: pd.Series, index: pd.DatetimeIndex, lag_months: int = 0):
    """Map a monthly Shiller series onto a daily index.

    Value for month M is treated as known from the first day of month ``M + 1 + lag``
    (Shiller publishes with roughly a one-month delay; use ``lag_months`` to add the
    documented release lag). Forward-filled; NaN before the first known value.
    """
    if not isinstance(monthly.index, pd.PeriodIndex):
        raise TypeError("expected a monthly PeriodIndex")
    known = monthly.copy()
    known.index = (monthly.index + 1 + lag_months).to_timestamp(how="start")
    known = known[~known.index.duplicated(keep="last")].sort_index()
    return known.reindex(index.union(known.index)).ffill().reindex(index)


__all__ = [
    "SHILLER_URLS",
    "FRED_CSV",
    "fetch_file_lenient",
    "shiller_period_index",
    "load_shiller",
    "fred_series",
    "load_long_sp500_tr",
    "load_long_tbill_yield",
    "long_cash_returns",
    "long_sample",
    "shiller_to_daily",
]
