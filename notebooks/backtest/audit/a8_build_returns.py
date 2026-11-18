"""A8 - rebuild every final strategy signal (S01-S10, S07 as its successor S07b) and cache
its daily return series so the statistics audits (DSR, placebo, replication) can reuse them.
"""

import sys
import numpy as np
import pandas as pd
from _audit_common import banner, BT, HERE

for sub in (
    "ml",
    "fundamentals",
    "macro",
    "volatility",
    "trend",
    "ensemble",
    "valuation",
    "seasonality",
):
    sys.path.insert(0, str(BT / sub))
import bt_common as bc  # noqa: E402
import bt_long  # noqa: E402
import bt_periods as bp  # noqa: E402
import bt_pit  # noqa: E402
import bt_ml  # noqa: E402
import bt_stats as bs  # noqa: E402
import stage2 as s2  # noqa: E402

CACHE = HERE / "a8_returns.pkl"

# final (registered) variant per strategy and how it was run
FINALS = {
    "S02": ("build_s02", "term_pos", "main", "monthly"),
    "S03": ("build_s03", "comp_thr03", "main", "monthly"),
    "S04": ("build_s04", "lb21_t15", "main", "monthly"),
    "S05": ("build_s05", "m6", "main", "monthly"),
    "S06": ("build_s06", "tom", "main", "daily"),
    "S07b": ("build_s07b", "accel50", "late", "monthly"),
    "S08": ("build_s08", "logit_c0.1", "main", "monthly"),
    "S09": ("build_s09", "ratio_lt_0.95", "late", "daily"),
    "S10": ("build_s10", "avg", "main", "monthly"),
}


def namespace(sample):
    px, cash = sample["px"], sample["cash"]
    ns = dict(
        np=np,
        pd=pd,
        bc=bc,
        bt_long=bt_long,
        bt_pit=bt_pit,
        bt_ml=bt_ml,
        bs=bs,
        sample=sample,
        px=px,
        cash=cash,
        sys=sys,
        _root=BT.parents[1],
        display=lambda *a, **k: None,
        print=lambda *a, **k: None,
    )
    return ns


def s01_signal(sample):
    px, shiller = sample["px"], sample["shiller"]
    m = shiller[["CAPE", "GS10"]].dropna()
    m.index = m.index.to_timestamp(how="start")
    ey = 1 / m["CAPE"] - m["GS10"] / 100
    median = ey.expanding(min_periods=120).median().shift(1)
    sig = (ey > median).astype(float)
    sig[median.isna()] = np.nan
    return bt_pit.monthly_to_daily_pit(
        sig, px.index, **bt_pit.RELEASE_LAGS["SHILLER_CAPE"]
    )


def build_all(only=None):
    sample = bt_long.long_sample()
    px, cash = sample["px"], sample["cash"]
    out = {}
    todo = {"S01": None, **FINALS}
    for sid, spec in todo.items():
        if only and sid not in only:
            continue
        banner(f"A8 build {sid}")
        if spec is None:
            sig, proto, reb = s01_signal(sample), "main", "monthly"
        else:
            mod_name, variant, proto, reb = spec
            mod = __import__(mod_name)
            ns = namespace(sample)
            data = getattr(mod, "DATA_CELLS", None)
            for code in [c for _, c in data] if data else [mod.DATA]:
                exec(code, ns)
            exec(mod.SIGNAL, ns)
            sig = ns["build_signal"](ns["inputs"], **ns["VARIANTS"][variant])
        runs = s2.run_protocol(px, sig, cash, proto, reb)
        full = runs["full"]
        out[sid] = dict(
            signal=sig,
            r_strat=full["r_strat"],
            r_cash=full["r_cash"],
            pos=full["pos"],
            protocol=proto,
            rebalance=reb,
            periods={k: (v.index[0], v.index[-1]) for k, v in runs.items()},
        )
        print(
            sid,
            proto,
            reb,
            "full Sharpe",
            round(bs.excess_sharpe(full["r_strat"], full["r_cash"]), 4),
        )
    return out


def load():
    return pd.read_pickle(CACHE)


if __name__ == "__main__":
    only = [a for a in sys.argv[1:] if a.startswith("S")]
    res = build_all(only or None)
    if CACHE.exists() and only:
        old = load()
        old.update(res)
        res = old
    pd.to_pickle(res, CACHE)
    print("cached", sorted(res))
