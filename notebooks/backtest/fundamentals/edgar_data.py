"""SEC EDGAR data for S07b: ticker->CIK map, net-income facts and point-in-time YoY events.

Fair-access rules (https://www.sec.gov/os/accessing-edgar-data): descriptive User-Agent,
<= 10 requests/s (we use ~5/s), every response cached under .cache/notebooks/edgar/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import bt_common as bc

EDGAR_DIR = bc.CACHE_DIR / "edgar"
HEADERS = {
    "User-Agent": "investment-firm-agents backtest research (non-commercial)",
    "Accept-Encoding": "gzip, deflate",
}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{concept}.json"
)
MEMBERS_CSV = bc.CACHE_DIR / "research_samples" / "sp500_members_fja05680.csv"


def _get(url: str, path: Path, max_age_days: float = 30) -> Path | None:
    """Cached GET; returns None on 404 (concept not reported)."""
    miss = path.with_suffix(".missing")
    for p in (path, miss):
        if p.exists() and time.time() - p.stat().st_mtime < max_age_days * 86400:
            return path if p == path else None
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        r = bc.SESSION.get(url, headers=HEADERS, timeout=60)
        time.sleep(0.2)
        if r.status_code == 404:
            miss.write_text("404")
            return None
        if r.status_code == 200:
            path.write_bytes(r.content)
            return path
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"EDGAR {r.status_code} for {url}")


def ticker_cik_map() -> dict[str, int]:
    p = _get(TICKERS_URL, EDGAR_DIR / "company_tickers.json", max_age_days=7)
    data = json.loads(p.read_text())
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


def load_membership() -> pd.Series:
    """Index constituents by snapshot date (fja05680/sp500, MIT): Series of ticker lists."""
    df = pd.read_csv(MEMBERS_CSV, parse_dates=["date"])
    tick = df["tickers"].str.replace(".", "-", regex=False).str.upper().str.split(",")
    return pd.Series(
        tick.to_numpy(), index=pd.DatetimeIndex(df["date"]), name="members"
    )


def load_facts(
    ciks, concept: str = "NetIncomeLoss", progress: bool = True
) -> pd.DataFrame:
    """USD facts of one us-gaap concept for many CIKs (downloaded once, then cached)."""
    rows = []
    for i, cik in enumerate(sorted(set(ciks))):
        p = _get(
            CONCEPT_URL.format(cik=cik, concept=concept),
            EDGAR_DIR / concept / f"{cik}.json",
        )
        if progress and i % 100 == 0:
            print(f"  {i}/{len(set(ciks))} companies", flush=True)
        if p is None:
            continue
        for f in json.loads(p.read_text()).get("units", {}).get("USD", []):
            if f.get("form") in ("10-Q", "10-K", "10-Q/A", "10-K/A") and "start" in f:
                rows.append(
                    (
                        cik,
                        f["start"],
                        f["end"],
                        f["val"],
                        f["form"],
                        f["filed"],
                        f["accn"],
                    )
                )
    df = pd.DataFrame(
        rows, columns=["cik", "start", "end", "val", "form", "filed", "accn"]
    )
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    df["days"] = (df["end"] - df["start"]).dt.days
    return df


def yoy_events(facts: pd.DataFrame) -> pd.DataFrame:
    """One event per filing: latest-period net income vs the same period a year earlier,
    both as reported *in that filing* (comparatives restated within the filing only).
    Quarterly (80-100 day) facts from 10-Q, annual (350-380 day) facts from 10-K."""
    out = []
    q = facts["days"].between(80, 100)
    a = facts["days"].between(350, 380)
    for (cik, accn), g in facts[q | a].groupby(["cik", "accn"]):
        form = g["form"].iloc[0]
        g = (
            g[g["days"].between(80, 100)]
            if form.startswith("10-Q")
            else g[g["days"].between(350, 380)]
        )
        if g.empty:
            continue
        cur_end = g["end"].max()
        cur = g.loc[g["end"] == cur_end, "val"].iloc[-1]
        prior = g[(cur_end - g["end"]).dt.days.between(340, 390)]
        if prior.empty:
            continue
        out.append(
            (
                cik,
                g["filed"].max(),
                cur_end,
                form,
                float(cur),
                float(prior["val"].iloc[-1]),
            )
        )
    ev = pd.DataFrame(
        out, columns=["cik", "filed", "period_end", "form", "ni", "ni_prior"]
    )
    ev["avail"] = ev["filed"] + pd.Timedelta(
        days=1
    )  # EDGAR acceptance can be after the close
    return ev.sort_values("avail").set_index("avail")


# ---------------------------------------------------------------------------
# S07b: quarterly YoY events (Q4 instead of fiscal-year comparisons in 10-Ks)
# ---------------------------------------------------------------------------

_Q = (80, 100)  # 3-month fact
_Y = (350, 380)  # fiscal-year fact
_YTD9 = (260, 285)  # 9-month year-to-date fact
_YEAR = (340, 390)  # "same period a year earlier"
_NEXT_Q = (75, 105)  # gap between consecutive quarter ends


def _q4_reported(g: pd.DataFrame, fy_end, prior_end):
    """3-month Q4 pair tagged inside the 10-K itself (pre-2021 quarterly data table)."""
    q = g[g["days"].between(*_Q)]
    cur = q.loc[q["end"] == fy_end, "val"]
    pri = q.loc[q["end"] == prior_end, "val"]
    if cur.empty or pri.empty:
        return None
    return float(cur.iloc[-1]), float(pri.iloc[-1])


def _q4_derived(ytd9: pd.DataFrame, filed, fy_start, fy_end, fy_cur, fy_pri):
    """Q4 = FY - 9-month YTD for both years.  Both 9-month figures come from the latest
    Q3 10-Q (or 10-Q/A) of the same fiscal year filed no later than the 10-K."""
    cand = ytd9[
        (ytd9["filed"] <= filed)
        & ((ytd9["start"] - fy_start).abs().dt.days <= 3)
        & (fy_end - ytd9["end"]).dt.days.between(*_Q)
    ]
    if cand.empty:
        return None
    last = cand.sort_values("filed", kind="stable").iloc[-1]
    in_q3 = ytd9[ytd9["accn"] == last["accn"]]
    pri9 = in_q3.loc[(last["end"] - in_q3["end"]).dt.days.between(*_YEAR), "val"]
    if pri9.empty:
        return None
    return fy_cur - float(last["val"]), fy_pri - float(pri9.iloc[-1])


def _tenk_q4(g: pd.DataFrame, ytd9: pd.DataFrame):
    """``(fy_end, reported, derived)`` for one 10-K filing; reported/derived are
    ``(q4_cur, q4_prior)`` or None.  None overall when the 10-K has no FY pair."""
    y = g[g["days"].between(*_Y)]
    if y.empty:
        return None
    fy_end = y["end"].max()
    cur_y = y[y["end"] == fy_end]
    prior_y = y[(fy_end - y["end"]).dt.days.between(*_YEAR)]
    if prior_y.empty:
        return None
    rep = _q4_reported(g, fy_end, prior_y["end"].iloc[-1])
    der = _q4_derived(
        ytd9,
        g["filed"].max(),
        cur_y["start"].iloc[-1],
        fy_end,
        float(cur_y["val"].iloc[-1]),
        float(prior_y["val"].iloc[-1]),
    )
    return fy_end, rep, der


def _split_facts(facts: pd.DataFrame):
    keep = facts[
        facts["days"].between(*_Q)
        | facts["days"].between(*_Y)
        | facts["days"].between(*_YTD9)
    ]
    is_q = keep["form"].str.startswith("10-Q")
    ytd9 = keep[is_q & keep["days"].between(*_YTD9)]
    return keep, is_q, {c: g for c, g in ytd9.groupby("cik")}, ytd9.iloc[:0]


def quarterly_yoy_events(facts: pd.DataFrame) -> pd.DataFrame:
    """Like :func:`yoy_events`, but every event compares a 3-month quarter with the
    same quarter a year earlier.  10-Q events are identical to ``yoy_events``.  For a
    10-K the event is Q4: the 3-month Q4 pair tagged in the 10-K when present
    (``basis='q4_reported'``), else fiscal year minus 9-month YTD from the same
    fiscal year's Q3 10-Q (``basis='q4_derived'``), else no event.  Available from
    filing date + 1 day, as before."""
    keep, is_q, ytd9_by_cik, empty = _split_facts(facts)
    out = []
    for (cik, accn), g in keep.groupby(["cik", "accn"]):
        form = g["form"].iloc[0]
        filed = g["filed"].max()
        if form.startswith("10-Q"):
            q = g[g["days"].between(*_Q)]
            if q.empty:
                continue
            cur_end = q["end"].max()
            prior = q[(cur_end - q["end"]).dt.days.between(*_YEAR)]
            if prior.empty:
                continue
            cur = float(q.loc[q["end"] == cur_end, "val"].iloc[-1])
            out.append(
                (
                    cik,
                    filed,
                    cur_end,
                    form,
                    cur,
                    float(prior["val"].iloc[-1]),
                    "quarter",
                )
            )
            continue
        res = _tenk_q4(g, ytd9_by_cik.get(cik, empty))
        if res is None:
            continue
        fy_end, rep, der = res
        if rep is not None:
            out.append((cik, filed, fy_end, form, *rep, "q4_reported"))
        elif der is not None:
            out.append((cik, filed, fy_end, form, *der, "q4_derived"))
    ev = pd.DataFrame(
        out, columns=["cik", "filed", "period_end", "form", "ni", "ni_prior", "basis"]
    )
    ev["avail"] = ev["filed"] + pd.Timedelta(days=1)
    return ev.sort_values(["avail", "cik"], kind="stable").set_index("avail")


def validate_q4(facts: pd.DataFrame, rel_tol: float = 0.01) -> pd.DataFrame:
    """10-Ks that both tag Q4 and allow FY - 9-month YTD: one row each with the two
    pairs.  ``match_*`` = |derived - reported| <= max(rel_tol * |reported|, $1m)."""
    keep, is_q, ytd9_by_cik, empty = _split_facts(facts)
    rows = []
    for (cik, accn), g in keep[~is_q].groupby(["cik", "accn"]):
        res = _tenk_q4(g, ytd9_by_cik.get(cik, empty))
        if res is None or res[1] is None or res[2] is None:
            continue
        fy_end, rep, der = res
        rows.append((cik, accn, fy_end, g["filed"].max(), *rep, *der))
    df = pd.DataFrame(
        rows,
        columns=[
            "cik",
            "accn",
            "fy_end",
            "filed",
            "rep_cur",
            "rep_prior",
            "der_cur",
            "der_prior",
        ],
    )
    for leg in ("cur", "prior"):
        tol = np.maximum(rel_tol * df[f"rep_{leg}"].abs(), 1e6)
        df[f"match_{leg}"] = (df[f"der_{leg}"] - df[f"rep_{leg}"]).abs() <= tol
    df["match"] = df["match_cur"] & df["match_prior"]
    df["same_direction"] = np.sign(df["rep_cur"] - df["rep_prior"]) == np.sign(
        df["der_cur"] - df["der_prior"]
    )
    return df


def add_acceleration(ev: pd.DataFrame) -> pd.DataFrame:
    """Add ``accel`` = 1.0 when this event's YoY change (ni - ni_prior) is above the
    company's previous-quarter YoY change, 0.0 when not, NaN without a previous
    quarter.  The previous quarter is the latest event of the same company that was
    available strictly earlier and whose period ended 75-105 days before."""
    e = ev.reset_index()
    e["_i"] = np.arange(len(e))
    e["d"] = e["ni"] - e["ni_prior"]
    m = e[["_i", "cik", "avail", "period_end", "d"]].merge(
        e[["cik", "avail", "period_end", "d"]], on="cik", suffixes=("", "_p")
    )
    gap = (m["period_end"] - m["period_end_p"]).dt.days
    m = m[(m["avail_p"] < m["avail"]) & gap.between(*_NEXT_Q)]
    m = m.sort_values(["_i", "avail_p"], kind="stable").drop_duplicates(
        "_i", keep="last"
    )
    acc = np.full(len(e), np.nan)
    acc[m["_i"].to_numpy()] = (m["d"] > m["d_p"]).astype(float).to_numpy()
    out = ev.copy()
    out["accel"] = acc
    return out


EVENTS_PKL = {"annual": "ni_events.pkl", "quarterly": "ni_events_q.pkl"}


def member_ciks(since: str = "2008-01-01") -> set[int]:
    """CIKs of all index members since ``since`` that map to a current SEC ticker."""
    m = load_membership()
    cmap = ticker_cik_map()
    tickers = {t for lst in m[m.index >= since] for t in lst}
    return {cmap[t] for t in tickers if t in cmap}


def build_events(kind: str = "quarterly", since: str = "2008-01-01") -> pd.DataFrame:
    """Rebuild ``EDGAR_DIR / EVENTS_PKL[kind]`` from the (cached) companyconcept files.
    ``kind='annual'`` reproduces the superseded S07 definition (``ni_events.pkl``)."""
    facts = load_facts(member_ciks(since), progress=False)
    ev = yoy_events(facts) if kind == "annual" else quarterly_yoy_events(facts)
    ev.to_pickle(EDGAR_DIR / EVENTS_PKL[kind])
    return ev
