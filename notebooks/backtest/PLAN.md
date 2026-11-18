# PLAN.md — Backtest research programme, Stage 1 (Phase B)

_Last updated: 2026-10-20_  |  **Frozen: 2026-10-20 (Stage 1 complete; edit only via Stage 2 PLAN)**  ·  Scope: `notebooks/backtest/`  ·  Decision-support only, no trading.

## 0 Context
Phase A (done): free long-history data research, primary-metric decision, 10-idea shortlist.
Phase B (this file): shared infrastructure as small modules, benchmarks notebook, trial
registry, S01 reference notebook, regression re-runs of the three existing notebooks.

## 1 Hard constraints
- Write discipline: <=150 lines per tool call; one concern per module; one test file per module.
- `bt_common.py` stays additive (existing functions unchanged; only a re-export block appended).
- Offline tests only (`pytest -p no:cacheprovider`); no live LLM calls; no git commits unless asked.
- Black (`--target-version py312`) on every edited .py. Never hardcode secrets.
- Point-in-time discipline: a monthly datum for month M is usable from the first trading day
  of M+1 (plus publication lag where known). Signals are shifted before execution.

## 2 Primary metric (frozen 2026-10-18)
PRIMARY = excess-return Sharpe (daily return minus T-bill, x sqrt(252)) **net of costs**.
Pass criteria for a shortlist idea:
1. dev AND val Sharpe > SMA200(monthly, 5 bp) AND > buy-and-hold;
2. block-bootstrap one-sided p <= 0.10 vs SMA200 in dev and in val;
3. deflated Sharpe ratio >= 0.95 using the registry trial count;
4. holdout: confirmatory only, Sharpe diff vs SMA200 > 0 (reported, never tuned on).
Sortino, Calmar, MaxDD reported alongside. Periods: dev 1934-02..1989-12, val 1990-01..2009-12,
holdout 2010-01..present (`bt_periods.PERIODS`).

## 3 Shortlist
S01 CAPE excess yield (REFERENCE) · S02 credit/term spread · S03 Sahm rule · S04 vol-managed ·
S05 TSMOM 12-1 · S06 Halloween+TOM · S07 EDGAR aggregate earnings (2009+) ·
S08 ML walk-forward Goyal features · S09 VIX/VIX3M (2009+) · S10 SMA200+CAPE ensemble.

## 4 Module checklist (build + test one at a time)
- [x] `bt_long.py` long-history loaders (Shiller, FRED, spliced S&P TR, T-bill) — 8 tests pass;
      reproduces sma200 reference (Sharpe 0.64 / B&H 0.51, 139 switches).
- [x] `bt_periods.py` dev/val/holdout runner + benchmark set — 6 tests pass; identical SMA200 rule gives zero diff vs benchmark; fixed const-mix rebalance bug
- [x] `bt_pit.py` point-in-time alignment + look-ahead test
- [x] `bt_stats.py` bootstrap, placebo, deflated Sharpe, primary metric, cost sensitivity
- [x] `bt_ml.py` walk-forward with purge/embargo
- [x] `bt_registry.py` registry.csv append + REGISTRY.md render
- [x] re-export block at end of `bt_common.py`; full `checks/` run green

## 5 Deliverables
- [x] B2 `benchmarks/benchmarks.ipynb` (B&H, SMA200, 60/40 const-mix, T-bills per period)
- [x] B3 `REGISTRY.md` + `registry.csv` (metric decision, backfilled SMA/TimesFM trials, S01–S10)
- [x] B4 `valuation/cape_excess_yield.ipynb` (S01) executed + registered incl. holdout
- [x] B5 regression re-run of sma200 / sma_trend / timesfm notebooks, key figures diffed
- [x] Final summary + Stage 2 executor prompt (see section 7)

## 6 Execution status
- 2026-10-20 bt_long.py + checks/test_bt_long.py written, black, 8 passed.

- bt_periods.py written + tested (6 passed). Fixes: check_days takes freq key not code; constant-mix sleeves reset to w/1-w on rebalance.
- bt_pit.py written + tested (7 passed). Note: next_close execution already lags the signal one bar, so leak tests use shift(-2); peek horizon default 21 bars.


- bt_stats.py written + tested (9 passed): block bootstrap of Sharpe diffs, Markov placebo, deflated Sharpe, cost sensitivity + breakeven bps, `PrimaryResult`/`primary_metric` (frozen CRITERIA; holdout confirmatory only, excluded from `passes`).

- bt_ml.py written + tested (9 passed): `Fold`, `walk_forward_splits` (expanding/rolling, purge+embargo), `assert_folds_disjoint`, `walk_forward_predict` (fresh model per fold), `forward_return`, `prediction_to_signal`, `oos_summary`, `NaiveMean` baseline.

- bt_registry.py written + tested (7 passed): `registry.csv` columns `COLUMNS`, `append_trial` (replace by trial_id), `append_trials`, `trial_count` (distinct strategy/params, excludes planned+benchmark), `rows_from_primary(PrimaryResult)`, `render_registry` -> REGISTRY.md.
- bt_common.py: guarded re-export loop over the six sibling modules appended (existing functions unchanged). Full `notebooks/backtest/checks` run green.


- B2 done: `benchmarks/build_benchmarks.py` builds + executes `benchmarks/benchmarks.ipynb` (nbformat/nbclient, `--execute`), writes `benchmarks/benchmarks.csv`. Full-sample Sharpe: bh 0.513, sma200 0.630, mix60 0.515 (B&H MaxDD -55.25%, SMA200 -32.96%, 136 switches, 69.4% in equities). Per period: dev sma200 0.64 vs bh 0.51; val 0.57 vs 0.32; holdout 0.66 vs 0.78 (SMA lags in the 2010+ bull market).

- B3 done: `seed_registry.py` (idempotent, replace-by-trial_id) seeds `registry.csv` with 12 benchmark rows (bh/sma200/mix60 x 4 periods), 4 backfilled pre-freeze trials (status run) and S01-S10 planned rows; renders `REGISTRY.md` with the frozen-metric header. trial_count = 4.

- B4 done: `valuation/build_cape.py` builds + executes `valuation/cape_excess_yield.ipynb` (S01, ey=1/CAPE-GS10 > expanding median, M+2 pit lag, monthly, 5bp). Excess Sharpe dev 0.573 / val 0.139 / holdout 0.649 / full 0.503 vs SMA200 0.644 / 0.572 / 0.658 / 0.630; bootstrap p vs SMA200 0.78 (dev), 0.97 (val); DSR 1.00 at n_trials=5; **passes=False**, holdout does not confirm. Placebo: real 0.46 vs placebo q95 0.43 (p 0.02) - better than random timing at 26% time-in-market, but not better than SMA200. Cost-insensitive (0.26x turnover/yr). Look-ahead test flagged suspicious but is powerless for a 23-switch signal. Registered as S01/dev..full status=fail (bare S01 planned row dropped); trial_count = 5.
- B5 done: `notebooks/backtest/rerun_regression.py` re-executed all three pre-freeze notebooks in place (0 cell errors; timesfm/torch present, so nothing skipped) and wrote `regression_report.md`. Key figures vs reference: sma200_regime_analysis SPY B&H 0.52 / SMA200 0.65 unchanged, long-history 0.58->0.57 / 0.69 (end date 2026-10-16 -> 2026-10-19, CAGR drift <=0.05pp); sma_trend_backtest Sharpe 0.69 / 0.70 / 0.53 unchanged (CAGR -0.03pp); timesfm_forecast_backtest 0.50 / SMA200 0.63 / B&H 0.48 unchanged. Verdict: no regression from the bt_* infra; all diffs are new trading days only.

## 7 Stage 1 verdict and Stage 2 executor prompt

### Verdict
Infrastructure, benchmarks, registry and regression are green. The one shortlist idea evaluated
(S01 CAPE excess yield) **fails** the frozen primary metric: dev/val excess Sharpe 0.573 / 0.139
vs SMA200 0.644 / 0.572 and B&H 0.511 / 0.319; bootstrap p vs SMA200 0.78 / 0.97; DSR 1.00 at
5 trials; holdout 0.649 vs SMA200 0.658 (does not confirm). It beats a Markov placebo (p 0.02) but
not the simpler SMA200 rule, and it is 26% invested with 23 switches in 90 years, so the look-ahead
test has no power. S01 stays in the registry as the honest reference row, not as a candidate.

### Stage 2 executor prompt (copy verbatim into a fresh session)
You are continuing the backtest research programme in `notebooks/backtest/` of
`investment-firm-agents`. Read `PLAN.md` sections 1-2 (hard constraints, FROZEN primary metric)
and `REGISTRY.md` first; do not change the metric, periods or pass criteria. Infra to reuse, never
rewrite: `bt_long` (loaders), `bt_periods` (dev/val/holdout runner + benchmarks), `bt_pit`
(point-in-time alignment, `RELEASE_LAGS`, `lookahead_test`), `bt_stats` (`primary_metric`,
`block_bootstrap`, `markov_placebo`, `deflated_sharpe`, `cost_sensitivity`), `bt_ml`
(walk-forward purge/embargo), `bt_registry` (`rows_from_primary`, `render_registry`,
`trial_count`). Template: `valuation/build_cape.py` (builder -> `.ipynb`, `--execute` via
nbclient; plotly date vlines must use `add_shape(yref="paper")`, never `add_vline`).
Tasks, one idea per builder + notebook, each registered with `n_trials = trial_count() + 1`
BEFORE looking at holdout: S02 credit/term spread, S03 Sahm rule, S05 TSMOM 12-1, S04 vol-managed,
S10 SMA200+CAPE ensemble (only if S01 adds information conditional on SMA200; report the bootstrap
of the ensemble vs SMA200 alone). Defer S07/S09 (short history) and S08 (ML) unless S02-S05 give
at least one pass. For every idea report: pit lag used, dev/val/holdout excess Sharpe vs SMA200 and
B&H, bootstrap p, DSR, cost breakeven bps, placebo p, look-ahead flag, pass/fail. After each
notebook: run `.venv\Scripts\python.exe -m pytest notebooks/backtest/checks -q -p no:cacheprovider`
and `rerun_regression.py --dry-run`, append the registry rows, re-render `REGISTRY.md`, tick
the checklist in a new `PLAN-stage2.md` (same template). Write discipline: <=150 lines per tool
call, black py312 on every .py, offline only, no live LLM calls, no git commits unless asked.
Stop and summarise after the first idea that PASSES, or after S10, whichever comes first.
