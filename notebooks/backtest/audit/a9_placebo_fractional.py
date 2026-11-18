"""A9 - placebo test with fractional weights (S04 vol-managed, S10 avg).

`bt_stats.placebo_test` binarises the signal at > 0.5, so a 0.5 weight becomes 0
and the placebo chains inherit a *lower* time-in-market than the real strategy.
Here we re-run the placebo with (a) the frozen implementation, (b) a threshold
at > 0 and (c) a binary chain whose share equals the real *mean weight*, so the
placebo earns the same equity beta.  No frozen code is changed.
"""

import pickle
import sys

import numpy as np
import pandas as pd

from _audit_common import BT, HERE, banner, record

sys.path.insert(0, str(BT))
import bt_common as bc  # noqa: E402
import bt_long  # noqa: E402
import bt_stats as bs  # noqa: E402

N_PLACEBO = 200


def placebo_variant(px, signal, cash, *, share, mean_len, rebalance, rng):
    """Markov on/off placebos with a chosen share and regime length."""
    real = bc.backtest_signal(px, signal, cash, 5.0, "next_close", None, rebalance)
    real_stat = bc.perf_stats(real["r_strat"], real["r_cash"])["Sharpe"]
    p_stay = 1 - 1 / mean_len
    n = len(px.index)
    vals = np.empty(N_PLACEBO)
    for k in range(N_PLACEBO):
        chain = np.empty(n, dtype=int)
        chain[0] = rng.random() < share
        u = rng.random(n)
        for t in range(1, n):
            chain[t] = chain[t - 1] if u[t] < p_stay else (rng.random() < share)
        fake = pd.Series(chain.astype(float), index=px.index)
        df = bc.backtest_signal(px, fake, cash, 5.0, "next_close", None, rebalance)
        vals[k] = bc.perf_stats(df["r_strat"], df["r_cash"])["Sharpe"]
    vals = vals[np.isfinite(vals)]
    return dict(
        real=float(real_stat),
        placebo_mean=float(vals.mean()),
        placebo_q95=float(np.percentile(vals, 95)),
        p_one_sided=float((vals >= real_stat).mean()),
        share=float(share),
        mean_len=float(mean_len),
    )


def regime_len(s):
    runs = max(1, int((np.diff(s) != 0).sum()))
    return len(s) / (runs + 1)


def main():
    banner("A9 placebo test with fractional weights")
    cache = pickle.load(open(HERE / "a8_returns.pkl", "rb"))
    sample = bt_long.long_sample()
    px, cash = sample["px"], sample["cash"]
    rows = []
    for sid in ("S04", "S10"):
        sig = cache[sid]["signal"].reindex(px.index).ffill().fillna(0.0)
        reb = cache[sid]["rebalance"]
        arr = sig.to_numpy()
        b05 = (arr > 0.5).astype(int)
        b00 = (arr > 0).astype(int)
        specs = {
            "frozen (>0.5)": (b05.mean(), regime_len(b05)),
            "threshold >0": (b00.mean(), regime_len(b00)),
            "share = mean weight": (arr.mean(), regime_len(b05)),
        }
        for name, (share, ml) in specs.items():
            rng = np.random.default_rng(bs.SEED)
            out = placebo_variant(
                px, sig, cash, share=share, mean_len=ml, rebalance=reb, rng=rng
            )
            out.update(strategy=sid, variant=name, mean_weight=float(arr.mean()))
            rows.append(out)
            print(
                sid,
                name,
                {k: round(v, 4) for k, v in out.items() if isinstance(v, float)},
            )
    tab = pd.DataFrame(rows)
    tab.to_csv(HERE / "a9_placebo.csv", index=False)
    return tab


def summarise(tab):
    def pick(sid, var, col):
        return float(tab[(tab.strategy == sid) & (tab.variant == var)][col].iloc[0])

    s04 = {v: pick("S04", v, "p_one_sided") for v in tab.variant.unique()}
    s10 = {v: pick("S10", v, "p_one_sided") for v in tab.variant.unique()}
    s04_share = (
        pick("S04", "frozen (>0.5)", "share"),
        pick("S04", "share = mean weight", "share"),
    )
    s10_share = (
        pick("S10", "frozen (>0.5)", "share"),
        pick("S10", "share = mean weight", "share"),
    )
    record(
        id="A9-01",
        area="statistics",
        strategy="S04;S10",
        severity="minor",
        finding=(
            "placebo_test binarises the signal at >0.5, so fractional weights are "
            "misrepresented: S10 avg 0.5 weights become 0 (placebo time-in-market "
            f"{s10_share[0]:.3f} vs real mean weight {s10_share[1]:.3f}); S04 weights "
            f"below 0.5 become 0 (placebo share {s04_share[0]:.3f} vs mean weight "
            f"{s04_share[1]:.3f}). Placebo chains therefore carry less equity beta "
            "than the strategy, which flatters the real Sharpe in the comparison."
        ),
        evidence=(
            "audit/a9_placebo_fractional.py: placebo p (one-sided) frozen / >0 / "
            f"share=mean-weight: S04 {s04['frozen (>0.5)']:.3f} / {s04['threshold >0']:.3f} / "
            f"{s04['share = mean weight']:.3f}; S10 {s10['frozen (>0.5)']:.3f} / "
            f"{s10['threshold >0']:.3f} / {s10['share = mean weight']:.3f} (200 placebos, seed bt_stats.SEED)"
        ),
        effect=(
            "Placebo is robustness-only (not part of the frozen PASS rule); no verdict "
            "changes. S04 and S10 notebooks already caveat the binarisation."
        ),
        fixed="no",
        file="bt_stats.py:placebo_test",
    )


if __name__ == "__main__":
    summarise(main())
