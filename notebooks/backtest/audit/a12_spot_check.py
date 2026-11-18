"""A12 - spot-check every number quoted in PLAN-stage2.md section 6 and in the
notebooks' interpretation cells against registry.csv / executed outputs."""

import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
BT = HERE.parent
sys.path.insert(0, str(HERE))
from _audit_common import banner, record  # noqa: E402

REG = pd.read_csv(BT / "registry.csv")
FINAL = REG[REG["status"].isin(["fail", "pass"])].copy()
FINAL["sid"] = FINAL["trial_id"].str.extract(r"^(S\d\d[a-z]?)(?=[-/])")

ROW_RE = re.compile(
    r"^\| (S\d\d[a-z]?) \| (\S+) \| (\S+) \| ([-\d.]+) / ([-\d.]+) / ([-\d.]+) \| "
    r"([-+\d.]+) / ([-+\d.]+) / ([-+\d.]+) \| ([-\d.]+) / ([-\d.]+) \| ([-\d.]+) \((\d+)\)"
)


def plan_rows():
    for line in (BT / "PLAN-stage2.md").read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if m:
            yield m.groups()


def reg_value(sid, period, col):
    r = FINAL[(FINAL["sid"] == sid) & (FINAL["period"] == period)]
    return float(r[col].iloc[0]) if len(r) else float("nan")


def check_plan():
    mism = []
    n = 0
    for g in plan_rows():
        sid = g[0]
        quoted = {
            ("dev", "sharpe"): g[3],
            ("val", "sharpe"): g[4],
            ("holdout", "sharpe"): g[5],
            ("dev", "d_sma200"): g[6],
            ("val", "d_sma200"): g[7],
            ("holdout", "d_sma200"): g[8],
            ("dev", "p_vs_sma200"): g[9],
            ("val", "p_vs_sma200"): g[10],
            ("full", "dsr"): g[11],
            ("full", "n_trials"): g[12],
        }
        for (period, col), q in quoted.items():
            n += 1
            actual = reg_value(sid, period, col)
            if col == "n_trials":
                ok = int(q) == int(actual)
            else:
                ok = abs(float(q) - round(actual, 2)) < 0.006
            if not ok:
                mism.append((sid, period, col, q, actual))
    return n, mism


def notebook_numbers(path: Path):
    """Yield (cell_idx, text) for markdown cells that quote decimals."""
    nb = json.loads(path.read_text(encoding="utf-8"))
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] == "markdown":
            txt = "".join(c["source"])
            if re.search(r"\d\.\d{2}", txt):
                yield i, txt


NOTEBOOKS = {
    "S01": "valuation/cape_excess_yield.ipynb",
    "S02": "macro/credit_term_spread.ipynb",
    "S03": "macro/sahm_rule.ipynb",
    "S04": "volatility/vol_managed.ipynb",
    "S05": "trend/tsmom.ipynb",
    "S06": "seasonality/halloween_tom.ipynb",
    "S07b": "fundamentals/edgar_earnings_breadth_q.ipynb",
    "S08": "ml/ml_walkforward.ipynb",
    "S09": "volatility/vix_term_structure.ipynb",
    "S10": "ensemble/sma200_cape.ipynb",
}


def interpretation_text(path: Path) -> str:
    for _, txt in notebook_numbers(path):
        if "Interpretation" in txt:
            return txt
    return ""


def fmt(x):
    return f"{x:.2f}"


def check_notebooks():
    """For each notebook, derive the headline numbers from registry.csv and see
    whether the Interpretation cell quotes them (as 2dp strings).  Numbers the
    text quotes but that match no registry-derived value are listed so they
    can be checked by hand."""
    report = []
    for sid, rel in NOTEBOOKS.items():
        txt = interpretation_text(BT / rel)
        if not txt:
            report.append((sid, "no interpretation cell", ""))
            continue
        expected = {}
        for period in ("dev", "val", "holdout"):
            s = reg_value(sid, period, "sharpe")
            if s != s:
                continue
            expected[f"{period} sharpe"] = fmt(s)
            expected[f"{period} sma200"] = fmt(s - reg_value(sid, period, "d_sma200"))
            expected[f"{period} bh"] = fmt(s - reg_value(sid, period, "d_bh"))
            if period != "holdout":
                expected[f"{period} p"] = fmt(reg_value(sid, period, "p_vs_sma200"))
        found = {k: v for k, v in expected.items() if v in txt}
        missing = {k: v for k, v in expected.items() if v not in txt}
        quoted = set(re.findall(r"(?<![\d.])-?\d\.\d{2}(?!\d)", txt))
        unexplained = sorted(
            q for q in quoted if q.lstrip("-+") not in set(expected.values())
        )
        report.append(
            (
                sid,
                f"{len(found)}/{len(expected)} registry numbers quoted; "
                f"missing {missing}",
                f"other decimals in text: {unexplained}",
            )
        )
    return report


def main():
    banner("A12 spot-check of quoted numbers")
    n, mism = check_plan()
    print(f"PLAN-stage2 section 6: {n} cells checked, {len(mism)} mismatches")
    for m in mism:
        print("  MISMATCH", m)
    bench = pd.read_csv(BT / "benchmarks" / "benchmarks.csv")
    sma = bench[bench["benchmark"] == "sma200"].set_index("period")["Sharpe"]
    print(
        "benchmarks.csv sma200:",
        {k: fmt(v) for k, v in sma.items()},
        "(PLAN quotes dev 0.64, val 0.57, holdout 0.66)",
    )
    for sid, a, b in check_notebooks():
        print(f"{sid}: {a}\n      {b}")
    record(
        id="A12-01",
        area="reporting",
        strategy="S01-S10",
        severity="none" if not mism else "minor",
        finding="PLAN-stage2 section 6 results table agrees with registry.csv finals",
        evidence=f"audit/a12_spot_check.py: {n} table cells compared at 2dp, {len(mism)} mismatches",
        effect="No transcription error in the summary table" if not mism else str(mism),
        fixed="no",
        file="PLAN-stage2.md",
    )


if __name__ == "__main__":
    main()
