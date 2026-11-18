"""B5 regression re-run: re-execute the pre-freeze notebooks in place and diff key figures.

Usage (from notebooks/backtest):  ../../.venv/Scripts/python.exe rerun_regression.py [--dry-run]
Writes regression_report.md next to this file.  Notebooks whose imports are missing
(e.g. timesfm/torch) are skipped and reported, never treated as failures.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
NOTEBOOKS = [
    HERE / "sma" / "sma200_regime_analysis.ipynb",
    HERE / "sma" / "sma_trend_backtest.ipynb",
    HERE / "timesfm" / "timesfm_forecast_backtest.ipynb",
]
OPTIONAL_IMPORTS = {"timesfm_forecast_backtest.ipynb": ["timesfm", "torch"]}
KEY = re.compile(r"[Ss]harpe|CAGR|max DD|switches", re.I)
REPORT = HERE / "regression_report.md"


def key_lines(nb) -> list[str]:
    out: list[str] = []
    for c in nb.cells:
        if c.cell_type != "code":
            continue
        for o in c.get("outputs", []):
            if o.get("output_type") == "stream":
                txt = "".join(o.get("text", ""))
            elif "data" in o and "text/plain" in o["data"]:
                txt = "".join(o["data"]["text/plain"])
            else:
                continue
            out += [ln.rstrip() for ln in txt.splitlines() if KEY.search(ln)]
    return out


def missing_imports(path: Path) -> list[str]:
    missing = []
    for mod in OPTIONAL_IMPORTS.get(path.name, []):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    return missing


def execute(path: Path) -> tuple[str, list[str], list[str]]:
    """Return (status, before_lines, after_lines)."""
    nb = nbformat.read(path, as_version=4)
    before = key_lines(nb)
    miss = missing_imports(path)
    if miss:
        return f"skipped (missing {', '.join(miss)})", before, before
    client = NotebookClient(
        nb,
        timeout=1800,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
        allow_errors=True,
    )
    client.execute()
    errors = [
        o
        for c in nb.cells
        if c.cell_type == "code"
        for o in c.get("outputs", [])
        if o.get("output_type") == "error"
    ]
    nbformat.write(nb, path)
    status = (
        "ok" if not errors else f"{len(errors)} cell error(s): {errors[0].get('ename')}"
    )
    return status, before, key_lines(nb)


def diff(before: list[str], after: list[str]) -> list[str]:
    b, a = set(before), set(after)
    lines = [f"- removed: `{x}`" for x in before if x not in a]
    lines += [f"+ added:   `{x}`" for x in after if x not in b]
    return lines


def main(dry_run: bool) -> int:
    report = ["# B5 regression re-run", ""]
    for path in NOTEBOOKS:
        rel = path.relative_to(HERE).as_posix()
        if dry_run:
            nb = nbformat.read(path, as_version=4)
            status, before, after = "dry-run", key_lines(nb), key_lines(nb)
        else:
            status, before, after = execute(path)
        changes = diff(before, after)
        print(
            f"{rel}: {status} | key lines {len(before)} -> {len(after)} | changed {len(changes)}"
        )
        report += [f"## {rel}", f"status: **{status}**", ""]
        report += changes or ["key figures unchanged"]
        report += ["", "<details><summary>key lines after</summary>", ""]
        report += [f"    {x}" for x in after] + ["", "</details>", ""]
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
