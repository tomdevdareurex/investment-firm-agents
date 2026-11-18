"""Shared bootstrap for audit scripts: sys.path, repo root, CSV append helper."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BT = HERE.parent
if str(BT) not in sys.path:
    sys.path.insert(0, str(BT))

AUDIT_CSV = BT / "audit.csv"
FIELDS = [
    "id",
    "area",
    "strategy",
    "severity",
    "finding",
    "evidence",
    "effect",
    "fixed",
    "file",
]


def repo_root() -> Path:
    p = HERE
    while not (p / "pyproject.toml").exists():
        p = p.parent
    return p


def record(row: dict | None = None, **kw) -> None:
    """Append (or replace by id) one finding in audit.csv."""
    row = {**(row or {}), **kw}
    rows = []
    if AUDIT_CSV.exists():
        with AUDIT_CSV.open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["id"] != row["id"]]
    rows.append({k: str(row.get(k, "")) for k in FIELDS})
    rows.sort(key=lambda r: r["id"])
    with AUDIT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def banner(title: str) -> None:
    print("\n=== " + title + " ===")
