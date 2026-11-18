# PLAN-stage2.md - Backtest research programme, Stage 2 (S02-S10)

_Started: 2026-10-20_ | Scope: `notebooks/backtest/` | Decision-support only, no trading. | Stage 1 plan: `PLAN.md` (frozen).

## 0 Context
Stage 1 (PLAN.md) built the infrastructure (`bt_long`, `bt_periods`, `bt_pit`, `bt_stats`, `bt_ml`,
`bt_registry`), benchmarks, the registry and the S01 reference (fails). Stage 2 evaluates S02-S10
with the same frozen metric, periods and benchmarks. User decisions for Stage 2 (2026-10-20):
run **all** of S02-S10 (no early stop, S07/S08/S09 not deferred); plans live in `notebooks/backtest/`.

## 1 Hard constraints (inherited, unchanged)
- PLAN.md sections 1-2: frozen primary metric (excess Sharpe net of costs; beat SMA200 and B&H in dev
  AND val; block-bootstrap one-sided p <= 0.10 vs SMA200 in dev and val; DSR >= 0.95; holdout
  confirmatory only). Periods dev 1934-02..1989-12, val 1990..2009, holdout 2010.. (`bt_periods.PERIODS`).
- Infra is reused, never rewritten. New code is additive (`stage2.py`, `stage2_nb.py`, per-strategy builders).
- Point-in-time: every input lagged to its publication date; decide at the close, next-close execution.
- Every parameter variant evaluated is a registered trial (feeds `trial_count()` -> deflated Sharpe).
- Write discipline: <=150 lines per tool call; black py312; offline tests; no LLM calls; no git commits.

## 2 Stage 2 protocol per strategy
1. Inputs loaded with explicit publication lags (table in each notebook).
2. **Truncation look-ahead test** (new, `stage2.truncation_test`) for every variant: recompute the signal
   with all inputs cut at ~30 past dates (monthly inputs: completed months only) and require it to equal
   the full-data signal on those dates. Must pass before any backtest. Fable's peek test is reported too.
3. **Dev-only sweep** over a small fixed grid; each variant registered (`<ID>-v<k>/dev`, status `run`).
   The variant with the best dev Sharpe is chosen; val and holdout are never used for choosing.
4. Frozen evaluation of the chosen variant with `bt_stats.primary_metric` (n_trials = registry count),
   rows `<ID>/<period>` registered with pass/fail; holdout reported, confirmatory only.
5. Robustness: cost sensitivity + break-even bp, Markov placebo, decade table, peek test.

**Late-data protocol** (S07, S09; data start after 1990): dev = data start..2013-12-31,
val = 2014-01-01..2017-12-31, holdout = 2018-01-01..latest, same frozen criteria, separate
leaderboard, marked weaker evidence. (Deviation from PLAN.md wording "dev to 2017 by walk-forward":
the frozen `primary_metric` needs dev and val, so the late window is split in two.)

## 3 Strategy cards (grids fixed before any run)
| ID | Rule (risk-on = equities) | Inputs and lags | Variants | Rebal. |
|---|---|---|---|---|
| S02 | credit: BAA-AAA spread <= its k-month MA; term: long rate - TB3MS > 0 | FRED BAA/AAA, TB3MS monthly avg: month M usable M+1 +7d; long rate = Shiller GS10 to 1953-03, FRED GS10 after | credit k=6; credit k=12; term>0; credit12 AND term>0 | monthly |
| S03 | Sahm: 3m avg UNRATE minus min of 3m avg over prior 12m < thr | FRED UNRATE, M+1 +7d (first Friday) | thr 0.3; thr 0.5; thr 0.5 with re-entry only below 0.25 | monthly |
| S04 | weight = min(1, target vol / realised vol) | daily TR, realised vol to close t | lookback 21d/63d x target 10%/15% | monthly |
| S05 | TSMOM: trailing TR over lookback (skip) > T-bill accrual over same window | daily TR + T-bill yield to close t | 12-1m; 12m; 6m | monthly |
| S06 | calendar | business-day calendar only | Halloween (Nov-Apr); TOM (last + first 3 bdays); Halloween + TOM in May-Oct | daily |
| S07 | breadth of YoY trailing-4Q net-income growth among S&P 500 members > 50% (late-data) | SEC EDGAR companyconcept (filed date +1d), fja05680 membership (MIT) | breadth>50%; aggregate NI YoY>0 | monthly |
| S08 | ML: P(next-month excess > 0) > 0.5, walk-forward yearly refits, purge 1m | Shiller D/P, E/P (M+2), term & credit spread (M+1 +7d), TB3MS, 12-1 mom, 1m ret, 21d vol | logit C=0.1; logit C=1; GBM depth 2; GBM depth 3 (+ NaiveMean baseline, not a trial) | monthly |
| S09 | VIX / VIX3M < thr (contango) (late-data) | FRED VIXCLS, VXVCLS daily, +1 trading day | thr 1.00; thr 0.95 | daily |
| S10 | SMA200 + S01 CAPE excess yield | as S01 (M+2) and price | AND; OR; 50/50 weight | monthly |

## 4 Files
`stage2.py` (truncation test, custom periods, dev sweep, evaluation, plots), `stage2_nb.py` (notebook
generator), `checks/test_stage2.py`, builders `<family>/build_sXX.py` -> `<family>/<name>.ipynb`.

## 5 Execution status
- [x] stage2.py + tests
- [x] stage2_nb.py generator
- [x] S02 credit/term spread
- [x] S03 Sahm rule
- [x] S04 vol-managed
- [x] S05 TSMOM
- [x] S06 Halloween + TOM
- [x] S07 EDGAR breadth (late-data)
- [x] S08 ML walk-forward
- [x] S09 VIX term structure (late-data)
- [x] S10 SMA200 + CAPE
- [x] regression (checks + rerun_regression --dry-run), REGISTRY.md, final summary

## 6 Results (generated from registry.csv)

Benchmark SMA200 monthly Sharpe: dev 0.64, val 0.57, holdout 0.66 (main protocol).

**Main protocol (dev 1934-89, val 1990-2009, holdout 2010+)**

| ID | strategy | chosen variant | Sharpe dev / val / holdout | vs SMA200 dev / val / holdout | p vs SMA200 dev / val | DSR (n) | result |
|---|---|---|---|---|---|---|---|
| S01 | cape_excess_yield | ey=1/CAPE-GS10 | 0.57 / 0.14 / 0.65 | -0.07 / -0.43 / -0.01 | 0.78 / 0.97 | 1.00 (5) | **fail** |
| S02 | credit_term_spread | term_pos | 0.57 / 0.32 / 0.70 | -0.07 / -0.25 / +0.04 | 0.83 / 0.93 | 1.00 (9) | **fail** |
| S03 | sahm_rule | comp_thr03 | 0.34 / 0.46 / 0.69 | -0.37 / -0.11 / +0.03 | 0.99 / 0.76 | 0.99 (13) | **fail** |
| S04 | vol_managed | lb21_t15 | 0.57 / 0.38 / 0.79 | -0.07 / -0.19 / +0.14 | 0.85 / 0.92 | 1.00 (17) | **fail** |
| S05 | tsmom | m6 | 0.65 / 0.49 / 0.46 | +0.01 / -0.09 / -0.20 | 0.55 / 0.94 | 1.00 (20) | **fail** |
| S06 | halloween_tom | tom | 0.96 / 0.34 / 0.25 | +0.32 / -0.24 / -0.41 | 0.04 / 0.84 | 1.00 (23) | **fail** |
| S08 | ml_walkforward | logit_c0.1 | 0.55 / 0.27 / 0.78 | -0.08 / -0.30 / +0.12 | 0.80 / 0.94 | 0.99 (27) | **fail** |
| S10 | sma200_cape | avg | 0.69 / 0.55 / 0.76 | +0.05 / -0.02 / +0.10 | 0.25 / 0.65 | 1.00 (34) | **fail** |

**Late-data protocol (dev to 2013, val 2014-17, holdout 2018+; weaker evidence)**

| ID | strategy | chosen variant | Sharpe dev / val / holdout | vs SMA200 dev / val / holdout | p vs SMA200 dev / val | DSR (n) | result |
|---|---|---|---|---|---|---|---|
| S07 | edgar_earnings_breadth | breadth50 | 0.83 / 0.97 / 0.52 | -0.08 / +0.20 / -0.02 | 0.39 / 0.09 | 0.75 (29) | **fail** |
| S07b | edgar_earnings_breadth_q | accel50 | 1.00 / 0.68 / 0.69 | +0.19 / -0.09 / +0.16 | 0.36 / 0.49 | 0.78 (37) | **fail** |
| S09 | vix_term_structure | ratio_lt_0.95 | 0.72 / 0.34 / 0.56 | -0.16 / -0.44 / +0.01 | 0.59 / 0.98 | 0.64 (31) | **fail** |

**Verdict: none of S02-S10 passes the frozen primary metric.** Closest: S10 `avg` (beats SMA200 in dev and
holdout, level in val, not significant; higher Sharpe from lower volatility, lower CAGR). Total distinct
trials in the registry: 34.

## 7 Deviation log
- 2026-10-20 Late-data window split into dev/val (see section 2) to reuse the frozen `primary_metric`.
- 2026-10-20 S02: long rate = Moody's AAA (FRED) instead of Shiller GS10 before 1953 (Shiller's pre-1953
  long rate is interpolated from annual data, a potential look-ahead). Result: fails (best dev = term_pos).
- 2026-10-20 S03: grid fixed before the run as comp_thr05, comp_thr03, rt_thr05 (FRED SAHMREALTIME,
  first-release data), rt_hyst; replaces the card's "thr 0.5 with re-entry" on revised data. Result: fails.
- 2026-10-20 S04 fails (beats B&H in all periods, not SMA200). S05 fails (m6 ties SMA200 in dev only).
- 2026-10-20 S06: calendar computed on a Mon-Fri business-day calendar (signal for t+2 bdays), daily checks.
- 2026-10-20 S07: SEC companyconcept (`NetIncomeLoss`) for the 638 CIKs mappable from 899 members since 2008
  (71%); YoY taken within each filing; stale > 135 days dropped; coverage >= 30%; 15 truncation cuts (slow build).
- 2026-10-20 S08: calendar-anchored yearly folds built in the notebook (partial last fold kept) instead of
  `bt_ml.walk_forward_splits`, which drops a short last fold and would make the truncation test fail for a
  non-leaky model; `bt_ml.assert_folds_disjoint` and `bt_ml.walk_forward_predict` are still used. 6 truncation cuts.
- 2026-10-20 S09: VIX3M from FRED `VXVCLS` (2007-12) rather than Cboe (2009-09): longer late-data history.
- 2026-10-20 Interpretations written after execution and inserted without re-running (`stage2_nb.set_interpretation`);
  specific claims were checked against the signals (S03 and S07 texts corrected).
- 2026-10-20 Stage 3 audit (AUDIT.md, audit.csv): no confirmed bugs, no strategy or metric changed. Follow-ups
  are additive modules only (`bt_stats_v2.py`, `stage2_trunc.py`, `bt_calendar.py`, `registry_historical.csv`);
  see PLAN-stage3.md. Deferred to Stage 4 (not fixed here, each would be a new trial or needs network):
  S06 re-timed on the exchange calendar (A6-01, verdict unchanged); S07 point-in-time CIK/membership map
  (current map uses today's membership and CIKs - survivorship risk, A7-02); S02/S03 on ALFRED first-release
  vintages for the full history (needs network; S03 already uses SAHMREALTIME).
- 2026-10-25 S07 defect found (registered result left unchanged): the 135-day staleness rule was never applied --
  `breadth_panel` subtracted microsecond timestamps (EDGAR dates, datetime64[us]) from second timestamps (`px.index`,
  datetime64[s]), so every filing counted as fresh. Effect on S07 breadth50: signal differs in 2 of 208 months.
- 2026-10-25 S07b (new trial, `fundamentals/build_s07b.py`): 10-K events compare Q4 with prior-year Q4 instead of fiscal
  years (Q4 tagged in the 10-K if present, else FY - 9-month YTD from the latest Q3 10-Q filed before the 10-K, else no
  event; `edgar_data.quarterly_yoy_events`, events in `ni_events_q.pkl`); staleness applied with unit-safe day numbers;
  variant grid fixed before the run as breadth50, agg_delta, accel50 (share of members whose YoY change beats the
  previous quarter's). Q4 check: derived = tagged within 1% for 97.3% of 3,328 10-Ks (tagged is used). Result: fails
  (dev chose accel50; val 0.65 < SMA200 0.77). Registry trials 34 -> 37.
- 2026-11-12 S07b re-run (notebook executed again): SEC `company_tickers.json` had refreshed (7-day cache), two
  long-filing CIKs left the current list and two tickers were reassigned, so the whole history changed slightly;
  registry now val 0.68 / holdout 0.69 (was 0.65 / 0.70), verdict unchanged. Results table and interpretation updated.
- 2026-11-13 S07 builder (`build_s07.py`) and notebook (`edgar_earnings_breadth.ipynb`) removed as superseded by S07b;
  audit scripts a7/a8/a10/a12 now run on S07b. S07's registry rows and the results row above are kept as history
  (they count towards the trial total).