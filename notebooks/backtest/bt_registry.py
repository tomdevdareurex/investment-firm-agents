"""Trial registry: every backtest trial is appended to ``registry.csv`` and
rendered to ``REGISTRY.md``.  The trial count feeds the deflated Sharpe.

A *trial* is one (strategy, parameter set, period) evaluation whose Sharpe was
looked at by a human.  Registering before looking at the result is the rule.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REGISTRY_CSV = HERE / "registry.csv"
REGISTRY_MD = HERE / "REGISTRY.md"

COLUMNS = [
    "trial_id",
    "date",
    "strategy",
    "notebook",
    "params",
    "period",
    "sharpe",
    "d_sma200",
    "d_bh",
    "p_vs_sma200",
    "dsr",
    "n_trials",
    "passes",
    "status",
    "note",
]

STATUSES = ("planned", "run", "pass", "fail", "dropped", "benchmark")


def _norm(row: dict) -> dict:
    out = {c: row.get(c, "") for c in COLUMNS}
    if not out["trial_id"]:
        raise ValueError("trial_id is required")
    if not out["date"]:
        out["date"] = dt.date.today().isoformat()
    if out["status"] and out["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {out['status']!r}")
    for k in ("sharpe", "d_sma200", "d_bh", "p_vs_sma200", "dsr"):
        v = out[k]
        if v not in ("", None) and not (isinstance(v, float) and pd.isna(v)):
            out[k] = f"{float(v):.4f}"
        else:
            out[k] = ""
    if out["n_trials"] not in ("", None):
        out["n_trials"] = str(int(out["n_trials"]))
    if out["passes"] not in ("", None):
        out["passes"] = str(bool(out["passes"]))
    return {k: ("" if v is None else str(v)) for k, v in out.items()}


def load_registry(path: Path = REGISTRY_CSV) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS]


def append_trial(
    row: dict, path: Path = REGISTRY_CSV, *, replace: bool = True
) -> pd.DataFrame:
    """Append one trial (dict with COLUMNS keys).  Existing ``trial_id`` is
    replaced when ``replace`` else a ValueError is raised.  Returns the frame.
    """
    new = _norm(row)
    df = load_registry(path)
    if (df["trial_id"] == new["trial_id"]).any():
        if not replace:
            raise ValueError(f"trial_id {new['trial_id']!r} already registered")
        df = df[df["trial_id"] != new["trial_id"]]
    df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    return df


def append_trials(rows: list[dict], path: Path = REGISTRY_CSV) -> pd.DataFrame:
    df = load_registry(path)
    for r in rows:
        df = append_trial(r, path)
    return df


def trial_count(path: Path = REGISTRY_CSV, *, include_benchmarks: bool = False) -> int:
    """Number of distinct (strategy, params) combinations evaluated so far.

    Used as ``n_trials`` for the deflated Sharpe: each parameter set counts once
    regardless of how many periods it was scored on.  Benchmarks and merely
    planned trials are excluded unless requested.
    """
    df = load_registry(path)
    if df.empty:
        return 0
    mask = ~df["status"].isin(["planned"])
    if not include_benchmarks:
        mask &= df["status"] != "benchmark"
    sub = df[mask]
    return int(sub[["strategy", "params"]].drop_duplicates().shape[0])


def rows_from_primary(
    trial_id: str,
    strategy: str,
    notebook: str,
    params: str,
    res,
    *,
    status: str | None = None,
    note: str = "",
) -> list[dict]:
    """Expand a ``bt_stats.PrimaryResult`` into one registry row per period."""
    rows = []
    st = status or ("pass" if res.passes else "fail")
    for p in res.sharpe:
        rows.append(
            {
                "trial_id": f"{trial_id}/{p}",
                "strategy": strategy,
                "notebook": notebook,
                "params": params,
                "period": p,
                "sharpe": res.sharpe[p],
                "d_sma200": res.d_sma200.get(p),
                "d_bh": res.d_bh.get(p),
                "p_vs_sma200": res.p_vs_sma200.get(p),
                "dsr": res.dsr if p == "full" else None,
                "n_trials": res.n_trials,
                "passes": res.passes,
                "status": st,
                "note": note,
            }
        )
    return rows


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_registry(
    path: Path = REGISTRY_CSV,
    md_path: Path | None = REGISTRY_MD,
    *,
    title: str | None = None,
) -> str:
    """Render the CSV as a markdown table (and write it to ``md_path`` if given)."""
    df = load_registry(path)
    n = trial_count(path)
    lines = [
        f"# {title or 'Backtest trial registry'}",
        "",
        f"_Rendered {dt.datetime.now().isoformat(timespec='minutes')} from `{Path(path).name}`._",
        "",
        f"Distinct strategy/parameter trials counted for the deflated Sharpe: **{n}**.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join(["---"] * len(COLUMNS)) + "|",
    ]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(_md_escape(r[c]) for c in COLUMNS) + " |")
    text = "\n".join(lines) + "\n"
    if md_path is not None:
        Path(md_path).write_text(text, encoding="utf-8")
    return text


__all__ = [
    "REGISTRY_CSV",
    "REGISTRY_MD",
    "COLUMNS",
    "STATUSES",
    "load_registry",
    "append_trial",
    "append_trials",
    "trial_count",
    "rows_from_primary",
    "render_registry",
]
