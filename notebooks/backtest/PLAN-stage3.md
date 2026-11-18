# PLAN-stage3.md — Stage 3 follow-ups (post-audit)
_Created 2026-10-20. Implements the "Recommended next steps" of AUDIT.md §8._

## 0. Scope and rules
- Everything here is **additive**. The frozen Stage 1 metric (PLAN.md §2, `bt_stats.py`)
  and every Stage 2 verdict are unchanged. New scoring is a **version 2**, reported
  side by side, never substituted.
- No strategy is tuned. Any variant that changes a strategy's parameters is a new
  trial and goes into `registry.csv` with its own id.
- Offline only; no LLM agent runs; nothing under `src/`, `tests/`, `config/`,
  `pyproject.toml` is touched.

## 1. Metric v2 — deflated Sharpe that answers the right question (NS1)
Module: `bt_stats_v2.py`; tests: `checks/test_bt_stats_v2.py`;
re-score script: `audit/metric_v2_rescore.py` → `audit/metric_v2_scores.csv`.

Why: audit finding A8-02. The frozen `bt_stats.deflated_sharpe` tests the
strategy's **own** Sharpe against the expected maximum of `n_trials` **zero-skill**
strategies whose Sharpe variance is the trial's own sampling variance (≈1/T). With
T≈14 000 daily bars that variance is tiny, SR0 is 0.02–0.05 annualised, and every
strategy with a positive Sharpe scores ≈1.0. It therefore tests "SR > 0 after a
negligible haircut", not "beats the benchmark after multiple testing".

v2 defines three estimators (all on daily returns, `ANN=252`):

| name | series tested | SR0 variance | question answered |
|---|---|---|---|
| `dsr_v1` | strategy excess return | own sampling var (≈1/T) | frozen v1, for reference |
| `dsr_vs_bench` | **active** return (strategy − SMA200) | own sampling var | does it beat SMA200 at all? |
| `dsr_cross_reg` | strategy excess return | cross-trial var of the 34 registry dev Sharpes | haircut for the trials we registered |
| `dsr_cross_full` | strategy excess return | same var, n = 119 trials | haircut for everything actually run (AUDIT.md §6.3) |

`pass_v2` = `dsr_vs_bench ≥ 0.95` **and** `dsr_cross_full ≥ 0.95`, required in both
dev and val, exactly mirroring the v1 two-period rule. Cross-trial variance of the
daily Sharpe = `var(annual dev Sharpes)/ANN` = **1.237e-4** (30 distinct values).
### 1.1 Results (`audit/metric_v2_scores.csv`, dev = 1935–1989, val = 1990–2009; S07/S09 use their recent-data periods)

| ID | period | SR | active SR vs SMA200 | dsr_v1 | dsr_vs_bench | dsr_cross_reg (n=34) | dsr_cross_full (n=119) | pass_v1 | pass_v2 |
|---|---|---|---|---|---|---|---|---|---|
| S01 | dev | 0.573 | −0.169 | 0.981 | 0.000 | 0.927 | 0.802 | yes | no |
| S02 | dev | 0.571 | 0.086 | 0.978 | 0.025 | 0.922 | 0.794 | yes | no |
| S03 | dev | 0.337 | −0.413 | 0.468 | 0.000 | 0.408 | 0.232 | no | no |
| S04 | dev | 0.571 | −0.022 | 0.977 | 0.003 | 0.921 | 0.793 | yes | no |
| S05 | dev | 0.651 | 0.003 | 0.992 | 0.005 | 0.973 | 0.912 | yes | no |
| S06 | dev | 0.960 | −0.086 | 1.000 | 0.001 | 1.000 | 1.000 | yes | no |
| S07 | dev | 0.827 | 0.057 | 0.330 | 0.007 | 0.821 | 0.774 | no | no |
| S08 | dev | 0.550 | 0.028 | 0.913 | 0.008 | 0.866 | 0.722 | no | no |
| S09 | dev | 0.722 | −0.201 | 0.361 | 0.001 | 0.802 | 0.742 | no | no |
| S10 | dev | 0.691 | −0.169 | 0.997 | 0.000 | 0.987 | 0.951 | yes | no |
| S01 | val | 0.139 | −0.464 | 0.067 | 0.000 | 0.145 | 0.077 | no | no |
| S02 | val | 0.319 | −0.053 | 0.243 | 0.002 | 0.401 | 0.268 | no | no |
| S03 | val | 0.457 | −0.116 | 0.465 | 0.001 | 0.643 | 0.500 | no | no |
| S04 | val | 0.383 | −0.166 | 0.338 | 0.000 | 0.514 | 0.370 | no | no |
| S05 | val | 0.487 | −0.334 | 0.515 | 0.000 | 0.690 | 0.552 | no | no |
| S06 | val | 0.335 | −0.338 | 0.257 | 0.000 | 0.430 | 0.295 | no | no |
| S07 | val | 0.971 | 0.617 | 0.417 | 0.088 | 0.880 | 0.845 | no | no |
| S08 | val | 0.271 | −0.131 | 0.181 | 0.001 | 0.321 | 0.203 | no | no |
| S09 | val | 0.335 | −0.752 | 0.072 | 0.000 | 0.469 | 0.404 | no | no |
| S10 | val | 0.555 | −0.464 | 0.635 | 0.000 | 0.788 | 0.668 | no | no |

Reading:
- `dsr_v1` passes 6/10 in dev (S01, S02, S04, S05, S06, S10) purely because SR > 0; it passes 0/10 in val, which is
  the only reason v1 did not inflate the programme's conclusion.
- `dsr_vs_bench` is ≈0 for every strategy in every period: no strategy's active
  return against SMA200 is distinguishable from zero. S07 val (0.088) is the only
  value above 0.05, driven by a short 4-year window.
- `dsr_cross_full` keeps only S06 (1.000) and S10 (0.951) in dev; both fail val.
- **Verdict under v2: none of S01–S10 passes.** The Stage 2 conclusion is robust to
  the choice of DSR estimator; v2 simply makes the gate informative instead of
  vacuous. v1 remains the metric of record for Stages 1–2.

Known limit: the cross-trial variance is estimated from registry dev Sharpes that
are themselves not independent (shared data, nested variants) and the 30 distinct
values include benchmarks' neighbours; treat 1.24e-4 as an order of magnitude.
## 2. Register the uncounted historical trials (NS2)

**Done 2026-10-20.** Audit finding A8-02: the SMA and TimesFM studies ran ~85 further
strategy variants that `registry.csv` (34 trials) never recorded.

- `audit/build_registry_historical.py` -> `registry_historical.csv` (124 rows, 85
  signal-distinct) and `REGISTRY-historical.md`.
- Composition: 65 SMA window x rebalance cells, 39 SMA cost-sweep cells (not
  signal-distinct), 18 TimesFM rule variants (R1, R4, R2 x 7 P_STAR, R3 x 9
  TAIL_Q10), 2 TimesFM comparison rules (ARIMA(1,1,1) under R1, 1-month momentum).
- Fuller trial count **119** signal-distinct (158 incl. cost sweeps) = the numbers
  AUDIT.md section 3.3 and section 1 above already use; the two comparison rules
  were included in a8's TimesFM count of 20, so no change to the totals.
- `registry.csv` / `bt_registry.trial_count()` untouched (still 34): the frozen
  v1 denominator must not move. A pointer line was appended to `REGISTRY.md`; it
  disappears whenever `render_registry` regenerates that file (seed_registry.py,
  stage2.py, valuation/build_cape.py), which is accepted - the canonical place for
  the pointer is this section and `REGISTRY-historical.md`.
- Sharpes are filled only for the 26 SMA grid cells the audit re-ran on the long
  proxy (`audit/a8_sma_grid.csv`); the remaining rows count for multiplicity only.

Assumptions: windows/rebalance set from `audit/a8_stats.py` constants (read from the
SMA notebook's parameter cell during the audit, not re-executed here); cost-sweep
rows share the monthly signal, hence not signal-distinct.
## 3. Release-aware truncation test (NS3)

**Done 2026-10-20.** Audit finding A5-01: `stage2.truncation_test` truncates each
monthly input at the month end (`truncate_inputs`), so a signal that uses month M's
value from the first trading day of M+1 - with no publication lag at all - still
rebuilds identically on every cut and passes with 0 mismatches. The test proves
"no future rows" but not "no unreleased rows".

- New module `stage2_trunc.py` (additive; `stage2.py` untouched):
  - `resolve_lag(spec)` - `None`, a `bt_pit.RELEASE_LAGS` key, or `{"months","days"}`.
  - `monthly_release_dates(index, lag)` - first day of M + MonthBegin(1+months) +
    days, identical to the `bt_pit.monthly_to_daily_pit` availability rule.
  - `truncate_inputs_release(inputs, cut, lags)` - starts from
    `stage2.truncate_inputs`, then drops monthly rows whose release date is after
    the cut and daily rows later than `cut - BDay(days)`.
  - `release_window_cuts(...)` - cut dates sampled inside the (month end, release)
    windows, where the two truncations differ and the original test is blind.
  - `truncation_test_release(build_signal, inputs, lags, ...)` - same comparison
    loop and `TruncResult` as stage2, on the release-aware truncation.
- `checks/test_truncation_blindspot.py` (9 tests, synthetic data, offline): the
  original test passes BOTH a lag-0 and a lag-1 monthly signal; the release-aware
  test fails lag-0 on every in-window cut and passes lag-1; daily `days=1` inputs
  are cut one business day early; `RELEASE_LAGS` keys resolve.
- Not applied to the Stage 2 notebooks: doing so would re-execute them without any
  expected change (AUDIT.md section 2 already confirmed the declared lags are
  implemented), and the frozen Stage 2 protocol names `stage2.truncation_test`.
  Stage 4 builders should call `truncation_test_release` with the strategy's
  declared lags in addition to the original test.

Still blind: data revisions (ALFRED vintages, section 5), lags that are declared
too short (the test only checks that the declared lag is honoured), and the
business-day approximation of exchange holidays in the daily cut (section 4).
## 4. NS4 - exchange-calendar helpers (`bt_calendar.py`)

Status: DONE 2026-10-20. Additive module; `bt_common.check_days` and the frozen
engine are unchanged.

What it adds (`notebooks/backtest/bt_calendar.py`):
- `exchange_holidays_from_index(index)` - weekdays missing from a price index
  (heuristic; `pandas_market_calendars` is not installed, so closures after the
  last bar cannot be known unless passed explicitly).
- `trading_day_offset(index, holidays=None)` - a `CustomBusinessDay` offset that
  skips those closures.
- `check_days_exchange(index, rebalance, holidays=None)` - identical to
  `bt_common.check_days` on interior bars; only the final bar is re-decided
  using the next *trading* day instead of `BDay(1)` (closes audit item A1-02:
  a sample ending on the day before a month-end holiday is now a check day).
- `nth_trading_day`, `is_last_trading_day`, `desired_calendar(index, rule)`
  (`halloween` / `tom` / `halloween_or_tom`) and `signal_for_lag(desired, lag)`
  = `desired.shift(-lag).ffill()` - the exact trading-calendar construction of
  the S06 target such that `signal.shift(lag)` under `next_close` holds exactly
  the intended days.

Tests: `checks/test_bt_calendar.py`, 9 passed. Includes a round-trip test
(`signal_for_lag(...).shift(2) == desired` on every bar after the first two) and
a divergence test showing that the Mon-Fri `BDay` construction used by
`seasonality/build_s06.py` misses the true last trading day when the exchange is
closed on the calendar month-end (e.g. 2023-11-29 when 2023-11-30 is dropped).

Effect on S06 (from audit A6-01, `audit/a6_s06_calendar.py`): the registered
S06 "tom" holds the intended day on 98.94 % of 23,298 bars (247 mismatches).
Re-timed exactly, excess Sharpe is dev 0.9998 / val 0.2676 / holdout 0.3086 /
full 0.6861 versus registry 0.9603 / 0.3352 / 0.2506 / 0.6685. Verdict FAIL is
unchanged (val p vs SMA200 ~0.84).

Decision: the S06 build script is NOT modified and no new trial is registered
(`trial_count()` stays 34). Re-timing S06 changes the strategy definition and
therefore counts as a new trial under PLAN.md section 2; it is deferred to
Stage 4, where `bt_calendar.desired_calendar` + `signal_for_lag` should be used
from the start. `check_days_exchange` is likewise available for Stage 4 engines
but is not swapped into `backtest_signal` (frozen).
## 5. NS5 - deferred items (documented, not implemented)

Status: DONE 2026-10-20 (documentation only; entry added to the PLAN-stage2.md
section 7 deviation log).

| Item | Audit ref | Why deferred | Stage 4 action |
|---|---|---|---|
| S06 exchange-calendar re-timing | A6-01 | Changes the strategy definition -> new trial; verdict unchanged when measured (val p ~0.84) | Build with `bt_calendar.desired_calendar` + `signal_for_lag`; register as new trial |
| S07 point-in-time membership / CIK map | A7-02 | Needs historical S&P 500 constituent lists (not available offline); current map = today's members, survivorship risk | Source PIT constituents; rebuild `fundamentals/edgar_data.py` mapping; new trial |
| S02/S03 full-history first-release vintages | A3-03, A3-04 | ALFRED vintages require network; S03 already uses `SAHMREALTIME` | Fetch ALFRED vintages, rerun with `stage2_trunc.truncation_test_release` |
| Shiller E lag +3 months as a default | A4-01..A4-04 | Verdicts unchanged under +3m lag; changing lags = new trials | Adopt +3m (or quarterly as-published E) for all Shiller-E strategies in Stage 4 |
| Deflated Sharpe vs SMA200 in the frozen metric | A8-02 | Metric is frozen for Stages 1-2 | Use `bt_stats_v2` as the Stage 4 primary metric |

Nothing in this section alters a registered result.
## 6. NS6 - final verification (2026-10-20)

- black `--target-version py312` on all new .py: 8 files unchanged (already formatted).
- `pytest notebooks/backtest/checks -q -p no:cacheprovider`: **79 passed** (10 files; new this
  stage: test_bt_stats_v2 9, test_truncation_blindspot 9, test_bt_calendar 9).
- `rerun_regression.py --dry-run`: every notebook `changed 0` (no registered result moved).
- `bt_registry.trial_count(registry.csv)` = 34 (unchanged; no new trial registered in Stage 3).
- Files touched: only `notebooks/backtest/**` (new modules, tests, audit scripts, registry_historical,
  PLAN-stage3.md, pointer line in REGISTRY.md, one dated entry in the PLAN-stage2.md section 7 log).
  `src/`, `tests/`, `config/`, `pyproject.toml`, frozen metric (`bt_stats.py`, PLAN.md section 2),
  `stage2.py` and every Stage 2 build script are untouched.
- Verdict impact: none. All ten strategies still fail the frozen v1 metric; none passes metric v2 either.