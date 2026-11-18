"""A8: statistics audit -- paired block bootstrap, deflated Sharpe recomputation,
fuller trial count, benchmark selection bias.  Uses the return cache from
a8_build_returns.py (run that first)."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

from _audit_common import BT, HERE, banner, record

sys.path.insert(0, str(BT))
import bt_common as bc  # noqa: E402
import bt_periods as bp  # noqa: E402
import bt_stats as bs  # noqa: E402
import bt_long  # noqa: E402

CACHE = pd.read_pickle(HERE / "a8_returns.pkl")
REG = pd.read_csv(BT / "registry.csv")
ANN = 252


def check_bootstrap():
    """Synthetic check: paired indices, block length, one-sided direction."""
    banner("A8-01 paired block bootstrap")
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2000-01-03", periods=2520)
    r_b = pd.Series(rng.normal(0.0004, 0.01, len(idx)), index=idx)
    # A identical to B except a constant premium -> diff always > 0 if paired
    r_a = r_b + 0.0002
    rf = pd.Series(0.0, index=idx)
    res = bs.sharpe_diff_bootstrap(r_a, r_b, rf, n_boot=2000, block=126, rng=rng)
    p_pair = res.p_value
    # unpaired resample (independent indices) for contrast
    ia = bc.block_indices(len(idx), 2000, 126, rng)
    ib = bc.block_indices(len(idx), 2000, 126, rng)
    diffs = bs._sharpe_np(r_a.to_numpy()[ia]) - bs._sharpe_np(r_b.to_numpy()[ib])
    p_unpaired = float(np.mean(diffs <= 0))
    # direction: a worse strategy must give p near 1
    res2 = bs.sharpe_diff_bootstrap(
        r_b - 0.0002, r_b, rf, n_boot=2000, block=126, rng=rng
    )
    print(f"paired p (A better by construction) = {p_pair:.4f}")
    print(f"unpaired p for contrast            = {p_unpaired:.4f}")
    print(f"paired p (A worse by construction)  = {res2.p_value:.4f}")
    ok = p_pair == 0.0 and res2.p_value > 0.9
    record(
        id="A8-01",
        area="statistics",
        strategy="all",
        severity="none" if ok else "major",
        finding="Paired block bootstrap: both series resampled with the same block "
        "indices (block=126), one-sided p = share of resampled Sharpe differences "
        "<= 0 (H1: strategy > SMA200).",
        evidence=f"synthetic A=B+2bp/day: paired p={p_pair:.4f} (unpaired would be "
        f"{p_unpaired:.3f}); A=B-2bp/day: p={res2.p_value:.4f}; bt_stats.py:75-105",
        effect="none" if ok else "p-values unreliable",
        fixed="n/a",
        file="bt_stats.py",
    )


def _bench():
    sample = bt_long.long_sample()
    px, cash = sample["px"], sample["cash"]
    return bp.benchmark_returns(px, cash)


def _daily_sr(ret, rf):
    x = (ret - rf.reindex(ret.index).fillna(0.0)).dropna()
    return float(x.mean() / x.std(ddof=1)), len(x), x


def dsr_table(bench: pd.DataFrame, n_full: int) -> pd.DataFrame:
    """Recompute the deflated Sharpe three ways for every final strategy, on
    the development period (the period that the frozen metric gates on) and
    on the full sample."""
    banner("A8-02 deflated Sharpe recomputation")
    # cross-trial variance of the 34 distinct registry trials (dev Sharpe)
    fin = REG[(REG["status"] != "benchmark") & (REG["period"] == "dev")]
    fin = fin.drop_duplicates("sharpe")  # final rows repeat the chosen variant
    srs = fin["sharpe"].astype(float) / np.sqrt(ANN)  # daily units
    var_x = float(srs.var(ddof=1))
    print(f"cross-trial variance of daily Sharpe (n={len(srs)}): {var_x:.3e}")
    rows = []
    for sid, c in CACHE.items():
        per = c["periods"]
        for pname in ("dev", "full"):
            if pname not in per:
                continue
            lo, hi = per[pname]
            r = c["r_strat"].loc[lo:hi]
            rf = c["r_cash"].loc[lo:hi]
            b = bench["sma200"].reindex(r.index)
            nt = REG.loc[REG["trial_id"] == f"{sid}/{pname}", "n_trials"]
            if nt.empty or pd.isna(nt.iloc[0]):
                nt = REG.loc[REG["trial_id"] == f"{sid}/dev", "n_trials"]
            n_reg = int(float(nt.iloc[0]))
            orig = bs.deflated_sharpe(r, n_reg, rf)["dsr"]
            # (a) versus SMA200: excess over the benchmark, own variance
            vs_b = bs.deflated_sharpe(r - b, n_reg, None)["dsr"]
            # (b) cross-trial variance, registry count
            sr, T, x = _daily_sr(r, rf)
            sr0 = bs.expected_max_sharpe(n_reg, var_x)
            sk, ku = float(x.skew()), float(x.kurt() + 3)
            den = np.sqrt(1 - sk * sr + (ku - 1) / 4 * sr**2)
            d_x = float(norm.cdf((sr - sr0) * np.sqrt(T - 1) / den))
            # (c) cross-trial variance, fuller count
            sr0f = bs.expected_max_sharpe(n_full, var_x)
            d_xf = float(norm.cdf((sr - sr0f) * np.sqrt(T - 1) / den))
            rows.append(
                dict(
                    strategy=sid,
                    period=pname,
                    n_reg=n_reg,
                    sr_ann=sr * np.sqrt(ANN),
                    sr0_own=bs.expected_max_sharpe(
                        n_reg, (1 - sk * sr + (ku - 1) / 4 * sr**2) / (T - 1)
                    )
                    * np.sqrt(ANN),
                    sr0_cross=sr0 * np.sqrt(ANN),
                    sr0_cross_full=sr0f * np.sqrt(ANN),
                    dsr_orig=orig,
                    dsr_vs_sma200=vs_b,
                    dsr_cross=d_x,
                    dsr_cross_full=d_xf,
                )
            )
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(out.round(4).to_string(index=False))
    out.to_csv(HERE / "a8_dsr.csv", index=False)
    return out


# Sweep grids run in the earlier (pre-registry) notebooks, read from their
# source cells: sma/sma_trend_backtest.ipynb and timesfm/timesfm_forecast_backtest.ipynb.
SMA_WINDOWS = [5, 10, 20, 30, 50, 75, 100, 150, 200, 250, 300, 350, 400]
SMA_REBAL = ["daily", "weekly", "monthly", "quarterly", "yearly"]
SMA_COSTS = [0, 5, 20]
TIMESFM_RULES = 4
TIMESFM_R2_THRESH = 7
TIMESFM_R3_THRESH = 9


def fuller_trial_count() -> dict:
    banner("A8-03 fuller trial count")
    reg_distinct = 34
    sma_grid = len(SMA_WINDOWS) * len(SMA_REBAL)
    sma_cost = len(SMA_WINDOWS) * len(SMA_COSTS)
    tfm = TIMESFM_RULES + TIMESFM_R2_THRESH + TIMESFM_R3_THRESH
    signal_distinct = reg_distinct + sma_grid + tfm
    with_costs = signal_distinct + sma_cost
    out = dict(
        registry=reg_distinct,
        sma_window_x_rebalance=sma_grid,
        sma_window_x_cost=sma_cost,
        timesfm_rules_and_thresholds=tfm,
        signal_distinct=signal_distinct,
        incl_cost_sweeps=with_costs,
    )
    for k, v in out.items():
        print(f"{k:32s} {v}")
    return out


def benchmark_selection_bias(bench: pd.DataFrame):
    """SMA200/monthly was chosen from the 13x5 grid on 1993+ data, i.e. it is
    itself the best of ~65 trials. Quantify what that implies for the hurdle:
    E[max SR] of 65 null trials given the cross-window dispersion of SMA
    Sharpes on the development period."""
    banner("A8-04 benchmark selection bias")
    sample = bt_long.long_sample()
    px, cash = sample["px"], sample["cash"]
    rows = []
    for w in SMA_WINDOWS:
        sig = (px["close"] > px["close"].rolling(w).mean()).astype(float)
        for rb in ("monthly", "daily"):
            runs = bp.run_periods(px, sig, cash, rebalance=rb)
            d, v = runs["dev"], runs["val"]
            rows.append(
                dict(
                    window=w,
                    rebalance=rb,
                    dev=bs.excess_sharpe(d["r_strat"], d["r_cash"]),
                    val=bs.excess_sharpe(v["r_strat"], v["r_cash"]),
                )
            )
    grid = pd.DataFrame(rows)
    print(grid.round(4).to_string(index=False))
    grid.to_csv(HERE / "a8_sma_grid.csv", index=False)
    pick = grid[(grid.window == 200) & (grid.rebalance == "monthly")].iloc[0]
    rank_dev = int((grid["dev"] > pick["dev"]).sum()) + 1
    rank_val = int((grid["val"] > pick["val"]).sum()) + 1
    print(
        f"SMA200/monthly rank in dev: {rank_dev}/{len(grid)}, val: {rank_val}/{len(grid)}"
    )
    print(f"grid dev Sharpe: median {grid.dev.median():.4f} max {grid.dev.max():.4f}")
    return grid, rank_dev, rank_val


def main():
    check_bootstrap()
    bench = _bench()
    counts = fuller_trial_count()
    dsr = dsr_table(bench, counts["signal_distinct"])
    dev = dsr[dsr.period == "dev"]
    n_pass_orig = int((dev.dsr_orig >= bs.DSR_MIN).sum())
    n_pass_vs = int((dev.dsr_vs_sma200 >= bs.DSR_MIN).sum())
    n_pass_x = int((dev.dsr_cross >= bs.DSR_MIN).sum())
    n_pass_xf = int((dev.dsr_cross_full >= bs.DSR_MIN).sum())
    record(
        id="A8-02",
        area="statistics",
        strategy="all",
        severity="major",
        finding="deflated_sharpe uses the trial's own sampling variance "
        "(~1/T) as var_sr, so the expected-max hurdle SR0 is ~0.02-0.05 annualised "
        "and DSR collapses to a test of Sharpe>0; it does not deflate for the "
        "34 trials and does not compare against SMA200.",
        evidence=f"dev period: DSR>=0.95 for {n_pass_orig}/10 (original), "
        f"{n_pass_vs}/10 when computed on r_strat-r_sma200, {n_pass_x}/10 with "
        f"cross-trial variance (n=34), {n_pass_xf}/10 with n={counts['signal_distinct']}"
        "; see a8_dsr.csv",
        effect="no verdict change (every strategy already fails on p_vs_sma200); "
        "the DSR gate as implemented is non-binding.",
        fixed="no (frozen metric; reported)",
        file="bt_stats.py:182-220",
    )
    record(
        id="A8-03",
        area="statistics",
        strategy="all",
        severity="minor",
        finding="Registry counts 34 distinct trials; the SMA window x rebalance "
        "grid (13x5) and the TimesFM rules R1-R4 plus threshold sweeps (7+9) in the "
        "earlier notebooks were not registered.",
        evidence=f"signal-distinct count {counts['signal_distinct']} "
        f"({counts['incl_cost_sweeps']} incl. cost sweeps); sma/sma_trend_backtest.ipynb, "
        "timesfm/timesfm_forecast_backtest.ipynb",
        effect=f"with cross-trial variance the dev DSR hurdle rises; passes {n_pass_x}->{n_pass_xf}; "
        "no verdict change",
        fixed="no",
        file="REGISTRY.md",
    )
    grid, rd, rv = benchmark_selection_bias(bench)
    record(
        id="A8-04",
        area="statistics",
        strategy="benchmark",
        severity="major",
        finding="SMA200/monthly benchmark was chosen after inspecting the 13x5 "
        "window x rebalance grid on 1993+ data, so the hurdle is itself the "
        "survivor of ~65 trials and is in-sample on the validation/holdout years.",
        evidence=f"SMA200/monthly ranks {rd}/{len(grid)} on dev and {rv}/{len(grid)} on val "
        f"among window x {{monthly,daily}} variants; grid dev median "
        f"{grid.dev.median():.3f}, max {grid.dev.max():.3f} (a8_sma_grid.csv)",
        effect="biases the test against the candidates; conservative in direction "
        "(makes PASS harder), so the 'none passes' conclusion is not weakened by it",
        fixed="no",
        file="PLAN.md section 2",
    )


if __name__ == "__main__":
    main()
