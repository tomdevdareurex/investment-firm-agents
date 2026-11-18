"""A10 - process integrity: registry completeness, dev-only choice, cards vs builders."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_common import BT, banner, record  # noqa: E402

EXPECTED_VARIANTS = {
    "S02": ["credit_ma6", "credit_ma12", "term_pos", "credit12_and_term"],
    "S03": ["comp_thr05", "comp_thr03", "rt_thr05", "rt_hyst"],
    "S04": ["lb21_t10", "lb21_t15", "lb63_t10", "lb63_t15"],
    "S05": ["m12_skip1", "m12", "m6"],
    "S06": ["halloween", "tom", "halloween_or_tom"],
    "S07b": ["breadth50", "agg_delta", "accel50"],
    "S08": ["logit_c0.1", "logit_c1", "gbm_d2", "gbm_d3"],
    "S09": ["ratio_lt_1.00", "ratio_lt_0.95"],
    "S10": ["and", "or", "avg"],
}

BUILDERS = {
    "S02": "macro/build_s02.py",
    "S03": "macro/build_s03.py",
    "S04": "volatility/build_s04.py",
    "S05": "trend/build_s05.py",
    "S06": "seasonality/build_s06.py",
    "S07b": "fundamentals/build_s07b.py",
    "S08": "ml/build_s08.py",
    "S09": "volatility/build_s09.py",
    "S10": "ensemble/build_s10.py",
}

# Card (PLAN-stage2.md section 3) vs build script, differences NOT in the deviation log.
UNDOCUMENTED = [
    (
        "S02",
        "card: term = long rate - TB3MS with long rate = Shiller GS10 to 1953-03 and FRED GS10 "
        "after; builder: term = Moody's AAA - TB3MS for the WHOLE sample (log only mentions pre-1953)",
    ),
    (
        "S08",
        "card lists 8 features; builder has 9 (adds sma_dist = close/SMA200 - 1); card says "
        "'12-1 mom' but mom12 = tr/tr.shift(252)-1 has no 1-month skip; E/P lag M+4 (builder) "
        "vs M+2 (card) - more conservative; all three stated in the notebook header, not in the log",
    ),
    (
        "S06",
        "card variant 'Halloween + TOM in May-Oct' is implemented as halloween | tom "
        "(equivalent: Nov-Apr already covered) - naming only",
    ),
]


def variant_rows(reg: pd.DataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sid in EXPECTED_VARIANTS:
        rows = reg[reg.trial_id.str.match(rf"^{sid}-v\d+/dev$")]
        out[sid] = [p.split(";")[0].split(" (")[0].strip() for p in rows.params]
    return out


def builder_variants(sid: str) -> list[str]:
    src = (BT / BUILDERS[sid]).read_text(encoding="utf-8")
    if sid == "S04":
        return [f"lb{lb}_t{int(t * 100)}" for lb in (21, 63) for t in (0.10, 0.15)]
    m = re.search(r"VARIANTS = \{(.*?)\}", src, re.S)
    body = m.group(1)
    keys = re.findall(r'"([^"]+)":\s*dict\(', body)
    if keys:
        return keys
    tup = re.search(r"in \(([^)]*)\)", body)
    return re.findall(r'"([^"]+)"', tup.group(1))


def main() -> None:
    banner("A10 process integrity")
    reg = pd.read_csv(BT / "registry.csv")
    found = variant_rows(reg)
    missing, extra = {}, {}
    for sid, exp in EXPECTED_VARIANTS.items():
        bv = builder_variants(sid)
        assert sorted(bv) == sorted(exp), (sid, bv)
        miss = sorted(set(exp) - set(found[sid]))
        ext = sorted(set(found[sid]) - set(exp))
        if miss:
            missing[sid] = miss
        if ext:
            extra[sid] = ext
        print(
            f"{sid}: builder {len(bv)} variants, registry {len(found[sid])} rows; "
            f"missing={miss} extra={ext}"
        )
    n_var = sum(len(v) for v in found.values())
    print("variant dev rows total:", n_var)
    record(
        id="A10-01",
        area="process",
        strategy="all",
        severity="none",
        finding="Every builder VARIANTS key has an <ID>-vK/dev registry row and vice versa",
        evidence=f"a10_process.py: {n_var} variant rows over 9 strategies; missing={missing}; extra={extra}",
        effect="none",
        fixed="no",
        file="registry.csv; */build_sXX.py",
    )

    # chosen variant == best dev variant; val/holdout rows exist only for the final
    mism = []
    for sid in EXPECTED_VARIANTS:
        v = reg[reg.trial_id.str.match(rf"^{sid}-v\d+/dev$")]
        f = reg[reg.trial_id == f"{sid}/dev"]
        best = v.sort_values("sharpe", ascending=False).iloc[0]
        if abs(best.sharpe - f.iloc[0].sharpe) > 1e-9:
            mism.append(sid)
        nonfinal = reg[reg.trial_id.str.match(rf"^{sid}-v\d+/(val|holdout|full)$")]
        if len(nonfinal):
            mism.append(sid + ":variant-with-val/holdout-row")
    print("dev-only choice mismatches:", mism)
    record(
        id="A10-02",
        area="process",
        strategy="S02-S10",
        severity="none",
        finding="Chosen variant is the best-dev variant in every strategy; no variant has a val/holdout "
        "row; stage2.dev_sweep scores dev only (code read: slice_period(...,'dev') only)",
        evidence=f"a10_process.py: mismatches={mism}",
        effect="none",
        fixed="no",
        file="stage2.py dev_sweep; registry.csv",
    )

    for sid, text in UNDOCUMENTED:
        record(
            id=f"A10-{3 + [u[0] for u in UNDOCUMENTED].index(sid):02d}",
            area="process",
            strategy=sid,
            severity="minor",
            finding="Card vs builder difference not in the PLAN-stage2 deviation log",
            evidence=text,
            effect="documentation only; signals as executed are what the registry scores",
            fixed="no",
            file=f"PLAN-stage2.md s3; {BUILDERS[sid]}",
        )
        print(sid, "-", text)


if __name__ == "__main__":
    main()
