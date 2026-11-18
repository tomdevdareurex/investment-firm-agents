"""Opt-in matched-sample placebo checks; legacy statistics remain unchanged."""

from __future__ import annotations

import numpy as np
import pandas as pd

import bt_common as bc


def placebo_test(
    px: pd.DataFrame,
    signal: pd.Series,
    cash,
    n_placebo: int = 200,
    cost_bps: float = 5.0,
    execution: str = "next_close",
    rebalance: str = "monthly",
    stat: str = "Sharpe",
    rng: np.random.Generator | None = None,
) -> dict:
    """Score real and random binary timing paths on identical executed dates.

    Retain the real signal's availability mask and the engine's execution lag,
    check dates and entry-cost policy. Calibrate the random equity probability
    from *executed* exposure, not unknown pre-signal history filled with cash.
    Exposure is matched in expectation, not exactly for each random path. The
    legacy Markov redraw persistence approximation is retained; this correction
    does not claim to exactly match realized regime lengths or turnover.
    """
    if not isinstance(n_placebo, (int, np.integer)) or n_placebo < 1:
        raise ValueError("n_placebo must be a positive integer")
    aligned = signal.reindex(px.index)
    if not aligned.notna().any():
        raise ValueError("matched placebo requires an available signal")
    if not aligned.dropna().isin([0.0, 1.0]).all():
        raise ValueError("matched placebo requires a binary signal")
    field, lag = bc.EXECUTIONS[execution]
    cash_s = cash[field] if isinstance(cash, dict) else cash
    eligible_returns = (
        aligned.ffill().shift(lag).notna()
        & px[field].pct_change(fill_method=None).notna()
        & cash_s.reindex(px.index).notna()
    )
    if eligible_returns.sum() < 2:
        raise ValueError("matched placebo requires at least two executed observations")
    real = bc.backtest_signal(px, aligned, cash, cost_bps, execution, None, rebalance)
    real_stat = float(bc.perf_stats(real["r_strat"], real["r_cash"])[stat])
    if not np.isfinite(real_stat):
        raise ValueError(f"real {stat} is not finite on the matched sample")

    rng = rng if rng is not None else np.random.default_rng(42)
    exposure = real["pos"].to_numpy()
    share = float(exposure.mean())
    transitions = max(1, int((np.diff(exposure) != 0).sum()))
    mean_len = len(exposure) / (transitions + 1)
    p_stay = max(0.0, 1 - 1 / mean_len)
    eligible = aligned.loc[aligned.first_valid_index() :]
    values, realized_exposure = [], []
    for _ in range(n_placebo):
        states = np.empty(len(eligible))
        state = float(rng.random() < share)
        for i in range(len(states)):
            if i and rng.random() > p_stay:
                state = float(rng.random() < share)
            states[i] = state
        fake_signal = pd.Series(states, index=eligible.index).where(eligible.notna())
        fake = bc.backtest_signal(
            px, fake_signal, cash, cost_bps, execution, None, rebalance
        )
        if not fake.index.equals(real.index):
            raise ValueError("real and placebo executed dates must match")
        values.append(bc.perf_stats(fake["r_strat"], fake["r_cash"])[stat])
        realized_exposure.append(float(fake["pos"].mean()))
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    return {
        "real": real_stat,
        "placebo_mean": float(vals.mean()) if len(vals) else np.nan,
        "placebo_q95": float(np.percentile(vals, 95)) if len(vals) else np.nan,
        "quantile": float((vals < real_stat).mean()) if len(vals) else np.nan,
        "p_one_sided": float((vals >= real_stat).mean()) if len(vals) else np.nan,
        "n_placebo": len(vals),
        "time_in_market": share,
        "evidence_version": "matched-v1",
        "sample_start": real.index[0].isoformat(),
        "sample_end": real.index[-1].isoformat(),
        "n_observations": len(real),
        "n_degenerate": n_placebo - len(vals),
        "placebo_time_in_market_mean": float(np.mean(realized_exposure)),
    }
