"""Build fundamentals/edgar_earnings_breadth_q.ipynb (S07b). Usage: python build_s07b.py [--execute]

S07b = S07 re-specified as a new trial: every event is a quarter vs the same quarter a year
earlier (10-K -> Q4 instead of the fiscal year), the 135-day staleness rule actually applied
(S07 compared datetime64[s] with datetime64[us] integers, so it never dropped anything), and an
acceleration variant.  S07's builder and notebook were removed (superseded); its registry rows
remain because they count towards the trial total.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S07b - Quarterly earnings breadth from SEC EDGAR filings (company fundamentals, late-data)

**Evaluation correction: `matched-v1`.** Only this notebook opts into common-window development
selection, matched-sample placebos, and a dev+val-only DSR acceptance gate. Future registry writes
use `S07b-matched-v1`, preserving legacy `S07b` rows; unchanged variants still count once toward
trial multiplicity because their strategy/parameter identities are unchanged.

**Hypothesis.** As S07: when a falling share of S&P 500 companies report year-on-year earnings growth,
the earnings cycle is turning down and equity risk is elevated (Kothari, Lewellen & Warner 2006).
S07b adds the *acceleration* of earnings growth, which turns earlier than the growth level.

**What changed vs S07 (new trial, S07 untouched)**

| | S07 | S07b |
|---|---|---|
| 10-K event | fiscal year vs prior fiscal year (about 4x a quarter in dollars) | **Q4** vs prior-year Q4 |
| Q4 source | - | 3-month Q4 tagged in the 10-K if present, else fiscal year - 9-month YTD from the same year's Q3 10-Q (both years), else no event |
| staleness | stated 135 days, **not applied** (seconds vs microseconds in the comparison) | 135 days, applied |
| variants | breadth50, agg_delta | breadth50, agg_delta, **accel50** |

| Variant | Risk-on (hold S&P 500) at month-end t when ... |
|---|---|
| breadth50 | > 50% of index members with a fresh filing report quarterly net income above the same quarter a year earlier |
| agg_delta | the sum over members of (quarterly net income - same quarter a year earlier) is > 0 |
| accel50 | > 50% of members with a fresh filing report a YoY change above their previous quarter's YoY change |

**Data and point-in-time handling**

| Item | Source | Point-in-time rule |
|---|---|---|
| Net income (us-gaap `NetIncomeLoss`), 3-month, 9-month YTD and fiscal-year facts from 10-Q / 10-K | SEC EDGAR XBRL `companyconcept` API | each event compares a quarter with the same quarter a year earlier **as reported in that filing** (derived Q4: the 10-K and the latest Q3 10-Q filed no later than it); usable from filing date + 1 day; ignored if older than 135 days |
| Acceleration | same events | compared with the same company's latest event available strictly earlier whose quarter ended 75-105 days before |
| Index membership by date | `fja05680/sp500` (MIT), snapshots 1996-2026 | members as of the decision date |
| Ticker -> CIK | SEC `company_tickers.json` (current tickers only) | static map |

**Survivorship.** As S07: only ~71% of the tickers that were members since 2008 map to a CIK today, so
early-sample breadth is measured on survivors. XBRL starts in 2009, hence the **late-data protocol**:
dev = data start..2013, val 2014-2017, holdout 2018+, separate leaderboard, weaker evidence.

**Sources.** SEC EDGAR APIs (https://www.sec.gov/edgar/sec-api-documentation; fair-access policy
https://www.sec.gov/os/accessing-edgar-data); Kothari, Lewellen & Warner (2006), *Stock returns,
aggregate earnings surprises, and behavioral finance*, JFE, SSRN 380127.

> Decision-support research only; never places orders."""

DATA_CELLS = [
    (
        """### 1.1 Index membership and ticker -> CIK

S&P 500 members by date come from the `fja05680/sp500` snapshots. SEC data is keyed by CIK (the SEC
company id), so every ticker that was a member since 2008 is mapped to a CIK with SEC's
`company_tickers.json`. That file lists **current** tickers only, so acquired or delisted members
cannot be mapped (survivorship, see caveats).""",
        """sys.path.insert(0, str(_root / "notebooks" / "backtest" / "fundamentals"))
import edgar_data as ed  # noqa: E402

SINCE = "2008-01-01"
members = ed.load_membership()  # Series: snapshot date -> list of tickers
cmap = ed.ticker_cik_map()  # ticker -> CIK (current tickers only)
tickers = sorted({t for lst in members[members.index >= SINCE] for t in lst})
ciks = ed.member_ciks(SINCE)
print(f"membership snapshots: {len(members):,}, {members.index[0].date()} -> {members.index[-1].date()}")
print(f"tickers that were members since {SINCE[:4]}: {len(tickers)} | map to a CIK today: "
      f"{sum(t in cmap for t in tickers)} ({sum(t in cmap for t in tickers) / len(tickers):.0%}) -> {len(ciks)} companies")
print("unmapped examples:", ", ".join([t for t in tickers if t not in cmap][:15]))""",
    ),
    (
        """### 1.2 Net-income facts from SEC EDGAR

For each CIK the XBRL `companyconcept` API returns every `NetIncomeLoss` value the company has filed
(one file per company, cached under `.cache/notebooks/edgar/`; only missing or >30-day-old files are
downloaded, at ~5 requests/s per SEC fair-access rules). Kept: 10-Q / 10-K (and amendments) facts
with a start date. One filing contains several facts: the current period, the prior-year
comparative, year-to-date figures and, in many 10-Ks before 2021, a table of quarters.""",
        """facts = ed.load_facts(ciks, progress=False)
kind = pd.Series(np.select([facts["days"].between(80, 100), facts["days"].between(260, 285),
                            facts["days"].between(350, 380)], ["3 months", "9 months YTD", "fiscal year"], "other"),
                 index=facts.index, name="period length")
print(f"{len(facts):,} facts | {facts['cik'].nunique()} companies | {facts['accn'].nunique():,} filings | "
      f"filed {facts['filed'].min().date()} -> {facts['filed'].max().date()}")
display(pd.crosstab(facts["form"], kind))

EXAMPLE = cmap["MSFT"]
ex = facts[(facts["cik"] == EXAMPLE) & (facts["form"] == "10-K") & (facts["filed"].dt.year == 2016)]
print(f"Example - every NetIncomeLoss fact in Microsoft's 10-K filed {ex['filed'].iloc[0].date()} (fiscal year ends June):")
display(ex.assign(kind=kind).sort_values(["days", "end"])[["start", "end", "days", "kind", "val"]])""",
    ),
    (
        """### 1.3 One quarterly year-on-year event per filing

* **10-Q**: the latest 3-month quarter vs the same quarter a year earlier, both as reported in that 10-Q.
* **10-K**: Q4 vs prior-year Q4. The 3-month Q4 pair tagged in the 10-K is used when present
  (`q4_reported`); otherwise Q4 = fiscal year - 9-month YTD for both years, the 9-month figures taken
  from the latest Q3 10-Q of the same fiscal year filed no later than the 10-K (`q4_derived`);
  otherwise the 10-K gives no event.
* Every event becomes usable on filing date + 1 day (`avail`, the index).""",
        """events = ed.quarterly_yoy_events(facts)
n10k = facts.loc[facts["form"].str.startswith("10-K"), "accn"].nunique()
print(f"{len(events):,} events | {events['cik'].nunique()} companies | {events.index.min().date()} -> {events.index.max().date()}")
print(f"10-K filings: {n10k:,} -> Q4 events: {(events['basis'] != 'quarter').sum():,} (rest: no tagged Q4 and no usable Q3 10-Q)")
display(pd.crosstab(events.index.year, events["basis"]).T)
print("Example - Microsoft events 2015-2017:")
display(events[events["cik"] == EXAMPLE].loc["2015":"2017"])""",
    ),
    (
        """### 1.4 Check: derived Q4 vs the Q4 tagged in the 10-K

Where a 10-K tags Q4 *and* a Q3 10-Q exists, both versions can be computed. Agreement shows that
`fiscal year - 9-month YTD` is reliable for the post-2021 filings where it is the only source. When
they disagree the tagged figure is used (agreed rule); the largest disagreements are listed.""",
        """q4check = ed.validate_q4(facts)
print(f"{len(q4check):,} 10-Ks with both | equal within 1% (or $1m) on both years: {q4check['match'].mean():.1%} | "
      f"current year {q4check['match_cur'].mean():.1%} | prior year {q4check['match_prior'].mean():.1%} | "
      f"same YoY direction: {q4check['same_direction'].mean():.1%}")
gap = (q4check["der_cur"] - q4check["rep_cur"]).abs() / q4check["rep_cur"].abs().clip(lower=1e6)
display(q4check.assign(rel_gap=gap).loc[~q4check["match"]].nlargest(8, "rel_gap")
        [["cik", "fy_end", "rep_cur", "der_cur", "rep_prior", "der_prior", "same_direction"]])""",
    ),
    (
        """### 1.5 Acceleration, saved event file and signal inputs

`accel` (used by the `accel50` variant) = 1 when an event's YoY change (`ni - ni_prior`) is above the
same company's previous-quarter YoY change. The previous quarter is the latest event available
strictly earlier whose quarter ended 75-105 days before. It is recomputed inside `build_signal`
(section 2), so the look-ahead test covers it; it is shown here only for inspection.""",
        """acc = ed.add_acceleration(events)
print(f"acceleration defined for {acc['accel'].notna().mean():.1%} of events; improving in {acc['accel'].mean():.1%} of those")
display(acc[acc["cik"] == EXAMPLE].loc["2015":"2017", ["period_end", "form", "basis", "ni", "ni_prior", "accel"]])

events.to_pickle(ed.EDGAR_DIR / ed.EVENTS_PKL["quarterly"])
print("saved", ed.EDGAR_DIR / ed.EVENTS_PKL["quarterly"])
inputs = {"px": px, "events": events, "members": members, "cmap": cmap}""",
    ),
]

SIGNAL = """STALE_DAYS = 135
COVERAGE_MIN = 0.30
MEASURES = {"breadth": "grow", "agg_delta": "delta", "accel": "accel"}


def _days(ts):
    # unit-safe day numbers: px.index is datetime64[s], EDGAR dates are datetime64[us]
    return np.asarray((pd.DatetimeIndex(ts) - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1), dtype=float)


def _latest(df, col, dec):
    sub = df.dropna(subset=[col]).drop_duplicates(["avail", "cik"], keep="last")
    wide = {}
    for c in (col, "t"):
        w = sub.pivot(index="avail", columns="cik", values=c)
        wide[c] = w.reindex(w.index.union(dec)).ffill().reindex(dec)
    return wide[col], wide["t"]


def breadth_panel(inputs):
    idx = inputs["px"].index
    dec = idx[bc.check_days(idx, "monthly").to_numpy()]
    ev = ed.add_acceleration(inputs["events"])
    df = pd.DataFrame({"cik": ev["cik"].to_numpy(), "avail": ev.index,
                       "grow": (ev["ni"] > ev["ni_prior"]).astype(float).to_numpy(),
                       "delta": (ev["ni"] - ev["ni_prior"]).to_numpy(),
                       "accel": ev["accel"].to_numpy()})
    df["t"] = _days(df["avail"])
    mem = inputs["members"]
    mem = mem.reindex(mem.index.union(dec)).ffill().reindex(dec)
    n_mem = np.array([len(m) if isinstance(m, list) else 0 for m in mem])
    mem_ciks = [[inputs["cmap"].get(x) for x in m] if isinstance(m, list) else [] for m in mem]
    now = _days(dec)[:, None]
    panel = {}
    for name, col in MEASURES.items():
        val, t = _latest(df, col, dec)
        is_mem = np.array([np.isin(val.columns, m) for m in mem_ciks])
        ok = ((now - t.to_numpy()) <= STALE_DAYS) & is_mem
        v = val.where(ok)
        panel[name] = v.sum(axis=1, min_count=1) if name == "agg_delta" else v.mean(axis=1)
        panel[f"cov_{name}"] = v.notna().sum(axis=1) / np.maximum(n_mem, 1)
    return pd.DataFrame(panel, index=dec)


def build_signal(inputs, measure="breadth"):
    p = breadth_panel(inputs)
    p = p[p[f"cov_{measure}"] >= COVERAGE_MIN]  # need a meaningful share of members with fresh filings
    raw = (p[measure] > 0) if measure == "agg_delta" else (p[measure] > 0.5)
    sig = raw.astype(float)
    idx = inputs["px"].index
    return sig.reindex(sig.index.union(idx)).ffill().reindex(idx)


VARIANTS = {"breadth50": dict(measure="breadth"), "agg_delta": dict(measure="agg_delta"),
            "accel50": dict(measure="accel")}
_BASE = ("EDGAR NetIncomeLoss quarterly YoY per filing (10-K->Q4: tagged 3m else FY-9M YTD), "
         "avail filed+1d, stale>135d dropped, coverage>=30%; monthly; next_close; 5bp")
PARAMS_TEXT = {"breadth50": f"breadth50; {_BASE}", "agg_delta": f"agg_delta; {_BASE}",
               "accel50": f"accel50 (YoY change > previous quarter's YoY change); {_BASE}"}"""

CHART = """panel = breadth_panel(inputs)
fig = go.Figure()
fig.add_trace(go.Scatter(x=panel.index, y=panel["breadth"], name="growth breadth (YoY)"))
fig.add_trace(go.Scatter(x=panel.index, y=panel["accel"], name="acceleration breadth"))
fig.add_trace(go.Scatter(x=panel.index, y=panel["cov_breadth"], name="coverage of members", line=dict(dash="dot")))
fig.add_hline(y=0.5, line_dash="dash", line_color="red")
fig.update_layout(title="Share of members with quarterly YoY net-income growth / acceleration (fresh filings) and coverage",
                  yaxis_tickformat=".0%", height=380, xaxis_range=["2009-01-01", str(panel.index[-1].date())])
fig.show()
display(panel.dropna(subset=["breadth"]).tail(4).round(3))"""

CAVEATS = """* Survivorship: delisted / acquired members cannot be mapped to a CIK, so early breadth is measured
  on companies that survived to 2026 (an upward bias in measured breadth). Current-vintage tickers can
  also map a recycled ticker to the wrong company (AUDIT A7-02).
* Q4 follows the agreed rule *reported first*: in ~2.7% of 10-Ks that tag Q4 the reported and derived
  figures differ by more than 1%, mostly from tagging errors in the reported fact (e.g. a value tagged
  in thousands); the growth direction still agrees in 99.8%.
* 10-Ks without a tagged Q4 and without a matching Q3 10-Q (fiscal-year changes, first filings) give
  no event; an amended or late filing about an older period still becomes the company's latest event.
* Only `NetIncomeLoss` is used; companies reporting under other tags drop out. One-off items and
  losses make net-income growth noisy; `agg_delta` is dominated by the largest companies.
* Very short history (one recession in sample, 2020): weak evidence by construction. This is the
  second specification tested on the same data (after S07), so the registry trial count rises accordingly."""

SPEC = dict(
    trial_id="S07b-matched-v1",
    evidence_version="matched-v1",
    strategy="edgar_earnings_breadth_q",
    folder="fundamentals",
    name="edgar_earnings_breadth_q",
    title="S07b",
    protocol="late",
    rebalance="monthly",
    header_md=HEADER,
    data_cells=DATA_CELLS,
    signal_code=SIGNAL,
    chart_code=CHART,
    caveats_md=CAVEATS,
    n_cuts=15,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
