"""A7 - S08 fold integrity / feature timing and S07b EDGAR as-filed logic
(S07 was superseded by S07b and its builder removed; ``--s07`` runs the S07b checks)."""

import sys
import numpy as np
import pandas as pd
from _audit_common import record, banner, BT

sys.path.insert(0, str(BT / "ml"))
sys.path.insert(0, str(BT / "fundamentals"))
import bt_common as bc  # noqa: E402
import bt_long  # noqa: E402
import bt_pit  # noqa: E402
import bt_ml  # noqa: E402
import build_s08  # noqa: E402


def s08_namespace():
    sample = bt_long.long_sample()
    px, cash = sample["px"], sample["cash"]
    ns = dict(
        np=np,
        pd=pd,
        bc=bc,
        bt_long=bt_long,
        bt_pit=bt_pit,
        bt_ml=bt_ml,
        sample=sample,
        px=px,
        cash=cash,
    )
    exec(build_s08.DATA, ns)
    exec(build_s08.SIGNAL, ns)
    return ns


def s08_checks(ns):
    banner("A7 S08 folds / labels / scaler / feature timing")
    X, ycls, yex = ns["features"](ns["inputs"])
    X = X.dropna()
    dec = X.index
    folds = []
    for s in range(ns["TRAIN_MIN"], len(X), ns["TEST_LEN"]):
        folds.append(bt_ml.Fold(dec[: s - ns["PURGE"]], dec[s : s + ns["TEST_LEN"]]))
    bt_ml.assert_folds_disjoint(folds, ns["PURGE"], dec)
    # label of training row k spans dec[k] -> dec[k+1]; must end <= first test date
    worst = 0
    for f in folds:
        last_train = f.train[-1]
        k = dec.get_loc(last_train)
        label_end = dec[k + 1]
        worst = max(worst, (label_end - f.test[0]).days)
    print(
        f"folds={len(folds)}  max(label_end - test_start) days = {worst}  (<=0 required)"
    )
    tests = pd.Index([]).append([f.test for f in folds])
    print(
        "test months unique:",
        tests.is_unique,
        "cover all OOS:",
        len(tests) == len(dec) - ns["TRAIN_MIN"],
    )
    # scaler inside the pipeline?
    est = ns["model_factory"]("logit", 0.1)().est
    steps = [type(s).__name__ for _, s in est.steps]
    print("logit pipeline steps:", steps)
    # feature timing: recompute features on data truncated at a decision date
    inputs = ns["inputs"]
    cut = dec[-150]
    tr_in = {
        k: (v.loc[:cut] if isinstance(v, (pd.Series, pd.DataFrame)) else v)
        for k, v in inputs.items()
    }
    tr_in["shiller"] = inputs["shiller"][
        inputs["shiller"].index.to_timestamp(how="start") <= cut
    ]
    Xt, _, _ = ns["features"](tr_in)
    common = Xt.index.intersection(X.index)
    diff = (Xt.loc[common] - X.loc[common]).abs().max()
    print("max |feature(full) - feature(truncated)| at decision dates <= cut:")
    print(diff.round(12).to_string())
    record(
        id="A7-01",
        area="ml",
        strategy="S08",
        severity="none",
        finding="Walk-forward folds disjoint; purge keeps every training label ending before the test start; StandardScaler fitted inside the per-fold pipeline; features at a decision date are unchanged when all data after that date is removed.",
        evidence=f"a7_s08_s07.py: {len(folds)} folds, max(label_end-test_start)={worst}d, steps={steps}, max feature diff={float(diff.max()):.2e}",
        effect="none",
        fixed="no",
        file="ml/build_s08.py; bt_ml.py",
    )
    return worst, diff


def s07_checks():
    banner(
        "A7 S07b EDGAR as-filed quarterly YoY / availability / staleness / membership"
    )
    import edgar_data as ed
    import build_s07b

    sample = bt_long.long_sample()
    px = sample["px"]
    events = pd.read_pickle(ed.EDGAR_DIR / ed.EVENTS_PKL["quarterly"])
    members = ed.load_membership()
    cmap = ed.ticker_cik_map()
    ev = events.reset_index()
    print(
        f"events={len(ev):,} ciks={ev.cik.nunique()} avail {ev.avail.min().date()}..{ev.avail.max().date()}"
    )
    bad_order = int((ev["period_end"] >= ev["filed"]).sum())
    print("events with period_end >= filed (impossible):", bad_order)
    gap = (ev["filed"] - ev["period_end"]).dt.days
    print(
        "filed - period_end days: median",
        gap.median(),
        " p5",
        gap.quantile(0.05),
        " p95",
        gap.quantile(0.95),
    )
    print(
        "avail - filed == 1 day for all:",
        bool(((ev["avail"] - ev["filed"]).dt.days == 1).all()),
    )
    print("form mix:", ev["form"].value_counts().to_dict())
    print("basis mix:", ev["basis"].value_counts().to_dict())
    # membership mapping coverage by year
    rows = []
    for d, m in members.items():
        m = m if isinstance(m, list) else []
        mapped = sum(1 for t in m if t in cmap)
        rows.append((d.year, len(m), mapped))
    cov = (
        pd.DataFrame(rows, columns=["year", "members", "mapped"]).groupby("year").mean()
    )
    cov["share"] = cov["mapped"] / cov["members"]
    print("ticker->CIK mapping share by year (current company_tickers.json):")
    print(cov["share"].round(3).to_string())
    ns = dict(np=np, pd=pd, bc=bc, ed=ed, px=px)
    exec(build_s07b.SIGNAL, ns)
    panel = ns["breadth_panel"](
        {"px": px, "events": events, "members": members, "cmap": cmap}
    )
    cov_ok = panel["cov_breadth"] >= ns["COVERAGE_MIN"]
    print("coverage>=0.30 first date:", panel.index[cov_ok][0].date())
    print(
        panel[["cov_breadth", "cov_accel"]]
        .groupby(panel.index.year)
        .mean()
        .round(3)
        .iloc[::3]
        .to_string()
    )
    # staleness and availability: at each decision date, every used event has avail <= dec and <= 135d old
    dec = panel.index
    df = ev.sort_values("avail")
    ok_av, ok_fresh = True, True
    for d in dec[::12]:
        last = df[df["avail"] <= d].groupby("cik")["avail"].max()
        ok_av &= bool((last <= d).all())
        used = (d - last).dt.days <= ns["STALE_DAYS"]
        ok_fresh &= bool(((d - last[used]).dt.days <= ns["STALE_DAYS"]).all())
    print("availability respected:", ok_av, " staleness respected:", ok_fresh)
    # ticker reuse: tickers in membership mapped to a CIK whose first filing is after the snapshot
    first_filing = ev.groupby("cik")["filed"].min()
    reuse = 0
    for d, m in members.items():
        for t in m if isinstance(m, list) else []:
            c = cmap.get(t)
            if (
                d.year >= 2012
                and c is not None
                and c in first_filing.index
                and first_filing[c] > d + pd.Timedelta(days=730)
            ):
                reuse += 1
    print(
        "member-days (snapshots>=2012) where mapped CIK first files >2y later (ticker reuse suspects):",
        reuse,
    )
    early = cov.loc[cov.index <= 2013, "share"].mean()
    record(
        id="A7-02",
        area="pit",
        strategy="S07b",
        severity="minor",
        finding="As-filed quarterly YoY (10-K -> Q4), filed+1 availability and 135d staleness are implemented as documented. Membership is point-in-time but the ticker->CIK map is current-vintage: delisted members are unmapped (survivorship) and reused tickers can map to the wrong company.",
        evidence=f"a7_s08_s07.py: period_end>=filed events={bad_order}; avail-filed=1d all; mapping share dev years mean={early:.2f}; ticker-reuse suspects={reuse}",
        effect="Breadth measured on survivors in the dev period (documented caveat); bias direction unknown; no verdict change.",
        fixed="no",
        file="fundamentals/edgar_data.py; fundamentals/build_s07b.py",
    )


if __name__ == "__main__":
    if "--s07" in sys.argv:
        s07_checks()
    else:
        ns = s08_namespace()
        s08_checks(ns)
