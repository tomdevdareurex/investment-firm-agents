# AUDIT.md — Stage 3 independent audit of Stages 1 and 2

_Audit date: 2026-10-21. Auditor: Fable (Stage 1 author; Stage 2 was built by a different model)._
_Scope: notebooks/backtest/ only. Decision support only. No strategy was tuned, the frozen metric (PLAN.md §2) was not changed._

## 1. Audit plan

Question: is the conclusion "none of S01–S10 beats SMA200 monthly or buy-and-hold under the frozen metric" trustworthy, and is any individual result wrong because of a bug, look-ahead, data leakage or a statistical error?

Method: small targeted experiments (scripts in `audit/`), not reading alone. Every finding is a row in `audit.csv` (id, area, strategy, severity, finding, evidence, effect, fixed, file) and is discussed below.

| # | Area | Script(s) | What is tested |
|---|------|-----------|----------------|
| A1 | Engine timing | `audit/a1_engine_timing.py` | `backtest_signal` next_close lag 2 on synthetic prices; `check_days` month-end incl. last bar |
| A2 | Long-history proxy | `audit/a2_long_history.py` | synthetic TR dividends spread, TB3MS known from M+1, cash uses previous-bar yield |
| A3 | PIT alignment | `audit/a3_pit_lags.py` | `monthly_to_daily_pit` months=1 ⇒ M+2; `daily_pit` union-index shift (S09 VIX); UNRATE / Moody's 7-day margin |
| A4 | Shiller lag sensitivity | `audit/a4_shiller_lag.py` | S01 / S10 / S08 re-run with Shiller E (and pre-1953 GS10) lagged +3 months |
| A5 | Truncation test blind spots | `audit/a5_truncation_blindspot.py` | show a lag-0 (release-date-indexed) series passes `stage2.truncation_test` |
| A6 | S06 calendar | `audit/a6_s06_calendar.py` | days actually held vs intended TOM / Nov–Apr days with exchange holidays |
| A7 | S08 folds, S07 EDGAR | `audit/a7_s08_s07.py` | disjoint folds with purge, label overlap, scaler inside pipeline, feature timing; S07 as-filed YoY, filed+1, staleness, membership |
| A8 | Statistics | `audit/a8_build_returns.py`, `audit/a8_stats.py` | bootstrap pairing/direction; DSR meaning and recomputation vs SMA200 / cross-trial variance; fuller trial count |
| A9 | Placebo | `audit/a9_placebo_fractional.py` | effect of binarising fractional weights (S04, S10 avg) |
| A10 | Process | `audit/a10_process.py` | every variant in registry; dev-only selection; cards vs builders |
| R | Replication | `audit/rep_independent.py` | pandas-only engine: benchmarks, S06 tom, S10 avg, S09 |
| Q | Quoted numbers | `audit/a12_spot_check.py` | interpretation cells and PLAN-stage2 §6 vs executed outputs |

Baseline before any change: `pytest notebooks/backtest/checks -q -p no:cacheprovider` → 52 passed (34 s); `rerun_regression.py --dry-run` → 0 changed key lines in the three earlier notebooks.

## 2. Summary verdict

**The conclusion holds.** Under the frozen metric none of S01–S10 beats SMA200 monthly and buy-and-hold in both development and validation; no verdict changes under any experiment run in this audit. Confidence is **high** for S01–S06, S08 and S10 (long-history, engine replicated independently to ≤0.0012 Sharpe, lag sensitivity run) and **medium** for S07 and S09 (recent-data protocol with 4-year validation windows, survivorship in S07's membership map, bootstrap on short series).

Three findings are **major** but none changes a verdict:

- **A5-01** `stage2.truncation_test` is blind to missing release lags — it passes a lag-0 series just as happily as the lagged one. Release-lag correctness therefore rests on `bt_pit.RELEASE_LAGS` and the builders' `LAG` constants alone, which were checked individually (A3, A4) and found conservative or immaterial.
- **A8-02** `bt_stats.deflated_sharpe` uses the trial's own sampling variance, so it tests Sharpe > 0 rather than deflating for 34 trials; it is non-binding (≈1.0 for every long-history strategy). Recomputed against SMA200 or with cross-trial variance it would be binding, but every strategy already fails the bootstrap gate.
- **A8-04** The SMA200 monthly benchmark was itself selected on 1993+ data from a 13×5 grid and ranks 3/26 in both dev and val; the hurdle is a survivor. This biases *against* the candidates (makes PASS harder), so it does not weaken "none passes" — it does weaken any claim that SMA200 is a fair out-of-sample hurdle.

No bugs that change a result were confirmed. **No fixes were applied**; the deviation log of PLAN-stage2.md is unchanged.

## 3. Findings by severity

Full rows (evidence, effect, file) are in `audit.csv`. Severity: critical = verdict change / invalid result; major = material bias, no verdict change; minor = documentation, clarity, small bias.

### Critical — none

### Major

| id | area | finding | effect |
|----|------|---------|--------|
| A5-01 | look-ahead test | `truncation_test` and `truncate_inputs` apply the same "month has ended" rule, so a signal that uses month M on the first trading day of M+1 with zero lag passes (60 cuts, 0 mismatches for months=0 and months=1). Also blind to data revisions (single vintage) and samples only completed months. | The test proves "no future-month data", not "realistic availability". |
| A8-02 | statistics | `deflated_sharpe` uses var_sr ≈ 1/T of the trial itself, so SR0 ≈ 0.02–0.05 annualised and DSR ≈ P(SR>0). | Non-binding gate; §6 recomputation. No verdict change. |
| A8-04 | benchmark | SMA200 monthly chosen after inspecting the 13×5 window × rebalance grid on 1993+ data; ranks 3/26 in dev and val of that grid. | Conservative direction (harder to PASS). |

### Minor

| id | strategy | finding |
|----|----------|---------|
| A1-02 | engine | `check_days` last-bar rule uses the Mon–Fri BDay calendar; a final bar before a weekday exchange holiday (e.g. Thu 30 Dec 2021) is not flagged as month-end. Affects only the last bar of a live sample. |
| A3-03 | S02, S03 | UNRATE lag `months=0, days=7` leaves ≥1 day margin for scheduled first-Friday releases but not shutdown-delayed ones (e.g. Sep-2013 report on 2013-10-22) or pre-1960s practice. S03 fails by 0.37 Sharpe, so immaterial. |
| A3-04 | S03 | `comp` variants use current-vintage UNRATE (revised seasonals) rather than first release; only `rt` variants use SAHMREALTIME. Favours S03, which still fails. |
| A4-01/02/03 | S01, S10, S08 | Shiller E depends on quarterly earnings published up to ~5 months later; `months=1` is optimistic. Re-run with +3 months: S01 and S10 *improve*, S08 slightly worsens; all still FAIL (§5). |
| A6-01 | S06 | Signal built as desired(t+2 BDays) on a Mon–Fri calendar; around exchange holidays the realised position misses the intended day. Position matches the intended day on 98.94 % of days; exact-intended Sharpe dev 1.00 / val 0.27 / holdout 0.31 vs registry 0.96 / 0.34 / 0.25 — still FAIL. |
| A7-02 | S07 | Ticker→CIK map is current-vintage: delisted members unmapped (survivorship), reused tickers may map to the wrong company. Bias direction unknown. |
| A8-03 | all | Registry counts 34 trials; the SMA grid (65), SMA cost sweep (39) and TimesFM R1–R4 + thresholds (20) are unregistered. Fuller count 119 signal-distinct / 158 incl. cost variants (§6). |
| A9-01 | S04, S10 | `placebo_test` binarises at >0.5: S10 avg's 0.5 weights become 0 (placebo time-in-market 0.17 vs real mean weight 0.47); S04 weights <0.5 become 0 (0.95 vs 0.91). Placebo p stays ≤0.025 under all three binarisations tried; robustness-only. |
| A10-03/04/05 | S02, S08, S06 | Card-vs-builder differences not in the deviation log (documentation only; registry scores the executed signal). |
| A11-02 | benchmarks | `benchmark_returns` drops warmup after the SMA NaN window, so benchmarks.csv dev starts 1935-11-26 vs strategy dev 1935-02-08 (0.6437 vs 0.6832 on the longer window). `stage2.evaluate` reindexes the benchmark onto each strategy window, so d_sma200 and p are unaffected. |

### None (verified correct)

A1-01 next_close timing (signal at t earns from close t+1 to t+2); A2-01 synthetic TR dividends evenly spread, spliced to ^SP500TR; A2-02 TB3MS known from M+1 and cash uses previous-bar yield; A3-01 `months=1` ⇒ usable from the 1st of M+2 as documented; A3-02 S09 VIX lag is exactly one trading day (every FRED VIX date is a trading day); A4-04 pre-1953 GS10 +12m changes Sharpe by <0.002; A7-01 S08 folds disjoint, purge covers labels, scaler inside the fold pipeline, features unchanged when post-decision data is removed; A8-01 paired block bootstrap (block 126, same indices, p = share of differences ≤ 0); A10-01 every builder variant has a `-vK/dev` row and vice versa; A10-02 chosen variant = best-dev variant for every strategy, no variant has val/holdout rows; A11-01 independent replication; A12-01/02 quoted numbers agree with the registry.
## 4. Per-strategy audited verdicts

Original verdicts from `registry.csv` finals (status `fail`); audited verdict after the experiments in §5–§7. Sharpe = excess-return Sharpe net of 5 bp costs; p = one-sided block-bootstrap p vs SMA200. Benchmarks: SMA200 dev 0.64 / val 0.57 / holdout 0.66; B&H 0.51 / 0.32 / 0.78.

| ID | Strategy | Original | Audited | Confidence | Dev S / p | Val S / p | Key issues |
|----|----------|----------|---------|------------|-----------|-----------|------------|
| S01 | CAPE excess yield | FAIL | FAIL | high | 0.57 / 0.78 | 0.14 / 0.97 | Shiller E lag optimistic (A4-01); longer lag improves val to 0.44 but still fails |
| S02 | Credit & term spread | FAIL | FAIL | high | 0.57 / 0.83 | 0.32 / 0.93 | UNRATE lag margin thin in delayed-release months (A3-03); card differs from builder (A10-03) |
| S03 | Sahm rule | FAIL | FAIL | high | 0.34 / 0.99 | 0.46 / 0.76 | comp variants current-vintage (A3-04); fails by widest margin |
| S04 | Vol-managed | FAIL | FAIL | high | 0.57 / 0.85 | 0.38 / 0.92 | placebo binarisation (A9-01), robustness only |
| S05 | TSMOM | FAIL | FAIL | high | 0.65 / 0.55 | 0.49 / 0.94 | none beyond the general findings |
| S06 | Halloween / TOM | FAIL | FAIL | high | 0.96 / 0.04 | 0.34 / 0.84 | beats SMA200 in dev (p 0.04) but not val; holiday mis-timing 1.06 % of days (A6-01) |
| S07 | EDGAR earnings breadth | FAIL | FAIL | medium | 0.83 / 0.39 | 0.97 / 0.09 | only strategy to beat SMA200 at p≤0.10 in val, but fails dev; survivorship in CIK map (A7-02); 4-year val window; EDGAR cache not re-downloaded |
| S08 | ML walk-forward | FAIL | FAIL | high | 0.55 / 0.80 | 0.27 / 0.94 | folds, purge, scaling verified (A7-01); +3m Shiller lag worsens (A4-03) |
| S09 | VIX term structure | FAIL | FAIL | medium | 0.72 / 0.59 | 0.34 / 0.98 | VIX lag exact (A3-02); recent-data protocol, short windows |
| S10 | SMA200 + CAPE ensemble | FAIL | FAIL | high | 0.69 / 0.25 | 0.55 / 0.65 | +3m Shiller lag raises val to 0.65 (above SMA200) but p 0.21 (A4-02); placebo binarisation (A9-01) |

Deflated Sharpe (own-variance, as implemented) ≥ 0.95 for S01–S06, S08, S10; 0.75 (S07) and 0.64 (S09) — irrelevant to the verdicts because the bootstrap gate fails first in every case.

## 5. Look-ahead and lag sensitivity

Scripts: `audit/a3_pit_lags.py`, `audit/a4_shiller_lag.py` (`--s08`), `audit/a5_truncation_blindspot.py`, `audit/a6_s06_calendar.py`, `audit/a7_s08_s07.py`. Registry baselines were reproduced exactly before each perturbation.

### 5.1 Release lags vs real practice

| Series | Lag used | Real practice | Judgement |
|--------|----------|---------------|-----------|
| TB3MS (cash) | known from the 1st of M+1, used with 1-bar shift | daily bill rate observable intraday | conservative (A2-02) |
| BAA/AAA (S02) | months=0, days=7 → ≥ 8th of M+1 | monthly average known at month-end | conservative |
| UNRATE (S02, S03) | months=0, days=7 | first Friday of M+1 (1st–7th) | ≥1 day margin; shutdown delays and pre-1960s practice not covered (A3-03) |
| SAHMREALTIME (S03 rt) | months=0, days=7 | FRED real-time series | ok; `comp` variants use revised UNRATE (A3-04) |
| Shiller CAPE / E (S01, S08, S10) | months=1 → 1st of M+2 | monthly E interpolated from quarterly earnings published up to ~5 months later | optimistic; sensitivity below (A4) |
| Shiller GS10 pre-1953 (S01, S10) | months=1 | annual data interpolated | sensitivity below (A4-04) |
| VIXCLS / VXVCLS (S09) | daily_pit(days=1) on union index | close known same evening | exactly one trading day (A3-02) |
| EDGAR 10-K/10-Q (S07) | filed + 1 day; staleness 135 d | filing date is the release date | ok (A7-02) |

### 5.2 Shiller lag sensitivity (`a4_s01_s10_lag.csv`, `a4_s08_lag.csv`)

| Variant | Dev S | Val S | Hold S | Full S | Dev p | Val p | DSR | PASS |
|---------|-------|-------|--------|--------|-------|-------|-----|------|
| S01 months=1 (registry) | 0.5731 | 0.1393 | 0.6487 | 0.5032 | 0.782 | 0.966 | 0.996 | no |
| S01 months=4 (+3m E) | 0.5947 | 0.4384 | 0.6297 | 0.5505 | 0.744 | 0.810 | 0.999 | no |
| S01 months=1, GS10 pre-1953 +12m | 0.5734 | 0.1393 | 0.6487 | 0.5034 | 0.782 | 0.966 | 0.996 | no |
| S01 months=4, GS10 +12m | 0.5957 | 0.4384 | 0.6297 | 0.5512 | 0.742 | 0.810 | 0.999 | no |
| S10 avg months=1 (registry) | 0.6907 | 0.5549 | 0.7596 | 0.6749 | 0.247 | 0.647 | 1.000 | no |
| S10 avg months=4 (+3m E) | 0.6958 | 0.6524 | 0.7419 | 0.6913 | 0.211 | 0.209 | 1.000 | no |
| S10 avg months=1, GS10 +12m | 0.6917 | 0.5549 | 0.7596 | 0.6756 | 0.242 | 0.647 | 1.000 | no |
| S08 logit_c0.1 (registry lags) | 0.5503 | 0.2712 | 0.7803 | 0.5129 | 0.800 | 0.945 | 0.992 | no |
| S08 both Shiller lags +3m | 0.5295 | 0.2576 | 0.7803 | 0.4987 | 0.850 | 0.960 | 0.989 | no |

Interpretation: a longer, more realistic Shiller lag *helps* S01 and S10 (the CAPE signal is slow-moving, so a staler CAPE avoided some whipsaw in 1990–2009) and slightly hurts S08. The pre-1953 long-rate interpolation is immaterial (<0.002). The verdicts are insensitive to the Shiller lag in both directions, so the optimistic `months=1` did not produce a false negative or a false positive.

### 5.3 What `truncation_test` can and cannot detect (A5-01)

`a5_truncation_blindspot.py` builds a signal from Shiller CAPE with `months=0` (month M usable on the first trading day of M+1, i.e. zero publication lag) and runs `stage2.truncation_test` with 60 random cut dates: **0 mismatches**, identical to the `months=1` case. Reason: `truncate_inputs` cuts the monthly input at the last *completed* month, the same rule the signal uses, so a missing publication lag is invisible. The test also cannot see data revisions (one vintage) and samples only completed months. It is a valid test of "no future-month data leaks into the signal" and nothing more; release-lag correctness rests on `RELEASE_LAGS` / builder `LAG` constants, which §5.1 checks individually.

### 5.4 S06 calendar (A6-01)

The builder sets `desired(t+2 BDays)` on a Mon–Fri calendar and the engine holds with a 2-bar lag. On the realised trading calendar the position equals the intended TOM / Nov–Apr indicator on **98.94 %** of days; the 1.06 % mismatches are the days adjacent to weekday exchange holidays. Replacing the signal with the exact intended indicator gives dev 0.9998 / val 0.2676 / holdout 0.3086 / full 0.6861 vs registry 0.9603 / 0.3352 / 0.2506 / 0.6685 — no verdict change (val still far below SMA200).

### 5.5 S08, S07, S09

- S08 (`a7_s08_s07.py`): walk-forward folds are disjoint; every training label ends before the test start (purge); `StandardScaler` is inside the per-fold pipeline; features at a decision date are bit-identical when all data after that date is deleted. A7-01 none.
- S07: as-filed YoY compares each filing with the same company's filing ~1 year earlier (no restated values); availability = filing date + 1 day; 135-day staleness drops old filings; membership is point-in-time but the ticker→CIK map is current-vintage (A7-02 minor, survivorship, direction unknown).
- S09: every FRED VIXCLS/VXVCLS date is an S&P trading day, so `daily_pit(days=1)` on the union index is exactly a one-trading-day lag (A3-02). Latent risk documented for 7-day series.
## 6. Statistics: deflated Sharpe, trial count, bootstrap, placebo

Scripts: `audit/a8_build_returns.py` (rebuilds every strategy's daily return series; all full-period Sharpes match the registry within 0.0006), `audit/a8_stats.py` (→ `a8_dsr.csv`, `a8_sma_grid.csv`), `audit/a9_placebo_fractional.py` (→ `a9_placebo.csv`).

### 6.1 Paired block bootstrap (A8-01, verified correct)

`bt_stats.sharpe_diff_bootstrap`: both the strategy and the SMA200 excess-return series are resampled with the **same** block indices (block length 126 trading days ≈ 6 months), the statistic is Sharpe(strategy) − Sharpe(SMA200), and `p = mean(diffs <= 0)` — a one-sided p for H1 "strategy > SMA200", the direction PLAN.md §2 specifies. Seeded; the registry p-values were reproduced exactly in §5.2.

### 6.2 What the deflated Sharpe actually tests (A8-02)

`bt_stats.deflated_sharpe(sr, n_trials, T, skew, kurt)` computes the expected maximum Sharpe of `n_trials` null strategies as SR0 = sqrt(var_sr)·E[max of n standard normals], then DSR = Φ((SR − SR0)·sqrt(T−1)/sqrt(1 − γ3·SR + (γ4−1)/4·SR²)). The implementation feeds **var_sr = the sampling variance of the trial's own Sharpe (≈ 1/T)**. With T ≈ 14,000 days that gives SR0 ≈ 0.02–0.05 annualised, so the hurdle is essentially zero and DSR ≈ P(SR > 0) — a test that the strategy has *any* positive excess Sharpe, not that it survives 34 trials. That is why DSR ≈ 1.0 for every long-history strategy and only the short-sample S07/S09 fall below 0.95. Bailey & López de Prado intend var_sr to be the **cross-trial variance of the Sharpe estimates** (how dispersed the tried strategies' Sharpes are), which is what makes SR0 a genuine multiple-testing hurdle.

Recomputation (dev period, `a8_dsr.csv`); `n_reg` = cumulative registry trial count at that strategy; cross-trial daily-Sharpe variance over the 34 registered trials = 1.24e-4:

| ID | n_reg | Dev S | DSR as implemented | DSR vs SMA200 (SR − SR_sma) | DSR cross-trial, n_reg | DSR cross-trial, n = 119 |
|----|-------|-------|--------------------|-----------------------------|------------------------|--------------------------|
| S01 | 5 | 0.573 | 0.999 | 0.008 | 0.996 | 0.802 |
| S02 | 9 | 0.571 | 0.996 | 0.187 | 0.986 | 0.794 |
| S03 | 13 | 0.337 | 0.634 | 0.000 | 0.587 | 0.232 |
| S04 | 17 | 0.571 | 0.989 | 0.023 | 0.963 | 0.793 |
| S05 | 20 | 0.651 | 0.996 | 0.030 | 0.986 | 0.912 |
| S06 | 23 | 0.960 | 1.000 | 0.005 | 1.000 | 1.000 |
| S07 | 29 | 0.827 | 0.354 | 0.026 | 0.827 | 0.774 |
| S08 | 27 | 0.550 | 0.927 | 0.032 | 0.888 | 0.722 |
| S09 | 31 | 0.722 | 0.375 | 0.005 | 0.807 | 0.742 |
| S10 | 34 | 0.691 | 0.997 | 0.000 | 0.987 | 0.951 |

- *DSR vs SMA200* (hurdle = SMA200 Sharpe, i.e. test "strategy beats the benchmark after deflation"): every strategy except S02 (0.19) is < 0.05 — consistent with the bootstrap gate.
- *Cross-trial variance, registry n*: DSR ≥ 0.95 passes fall from 8 to 6 (S03, S07, S08, S09 fail).
- *Cross-trial variance, fuller n = 119*: only S06 (dev) and S10 (0.951) remain ≥ 0.95.

Verdict effect: **none**. The DSR gate is applied *in addition to* the bootstrap gate, and every strategy already fails the bootstrap in dev or val. The finding is that the gate as implemented adds no information; it is reported, not changed (frozen metric).

### 6.3 Fuller trial count (A8-03) and benchmark selection (A8-04)

| Source | Trials | Registered? |
|--------|--------|-------------|
| Stage 1 + 2 registry (`registry.csv`) | 34 | yes |
| `sma/sma_trend_backtest.ipynb` window × rebalance grid (13 windows × 5 rebalance rules) | 65 | no |
| same notebook, cost sweep (3 cost levels × 13 windows) | 39 | no (cost variants, same signals) |
| `timesfm/timesfm_forecast_backtest.ipynb` rules R1–R4 + threshold sweeps (7 + 9) | 20 | no |
| **Signal-distinct total** | **119** | |
| **Including cost variants** | **158** | |

Effect on DSR: with cross-trial variance and n = 119 the dev hurdle SR0 rises to 0.457 annualised and only S06 and S10 keep DSR ≥ 0.95 (table above); no verdict changes because the bootstrap gate already fails.

Benchmark selection bias (A8-04): `a8_sma_grid.csv` re-runs a 13-window × {daily, monthly} subset of that grid (26 cells) on the long history. SMA200/monthly ranks **3rd of 26** in both dev and val. The benchmark was chosen in Stage 0 after inspecting 1993+ results, so it is a survivor of ~65 trials and is in-sample on val/holdout years. Direction: the hurdle is too high, which makes PASS harder and leaves "none passes" intact; it does mean a PASS would have been strong evidence and a FAIL is weaker evidence of "no edge" than the headline suggests.

### 6.4 Placebo binarisation (A9-01)

`bt_stats.placebo_test` binarises the signal at > 0.5 before building random in/out chains with the same time-in-market and mean run length.

| Strategy | Binarisation | Real S | Placebo mean S | Placebo q95 | p one-sided | Placebo share in market | Real mean weight |
|----------|--------------|--------|----------------|-------------|-------------|-------------------------|------------------|
| S04 | frozen (>0.5) | 0.550 | 0.498 | 0.542 | 0.020 | 0.951 | 0.910 |
| S04 | threshold >0 | 0.550 | 0.513 | 0.513 | 0.000 | 0.999 | 0.910 |
| S04 | share = mean weight | 0.550 | 0.487 | 0.539 | 0.025 | 0.910 | 0.910 |
| S10 avg | frozen (>0.5) | 0.694 | 0.210 | 0.379 | 0.000 | 0.172 | 0.474 |
| S10 avg | threshold >0 | 0.694 | 0.454 | 0.531 | 0.000 | 0.775 | 0.474 |
| S10 avg | share = mean weight | 0.694 | 0.352 | 0.498 | 0.000 | 0.474 | 0.474 |

For S10 avg the frozen binarisation maps the 0.5 weights to 0, so placebo chains hold equity only 17 % of the time against a real mean weight of 47 % — the placebo carries far less equity beta, which flatters the comparison. For S04 the effect is small. The placebo is robustness-only (not in the PASS rule) and the placebo p stays ≤ 0.025 under every binarisation, so nothing changes; the two notebooks already caveat it.
## 7. Independent replication and quoted-number spot checks

### 7.1 Pandas-only engine (`audit/rep_dump_inputs.py` → `rep_inputs.pkl`; `audit/rep_independent.py` → `rep_independent.csv`)

The replication imports neither `bt_common`/`bt_*` nor `stage2`. It takes only the raw inputs (TR close, cash yield, VIX series, Shiller CAPE as dumped by `rep_dump_inputs.py`) and re-implements from scratch: month-end check days, `target = signal.where(check).ffill()`, `pos = target.shift(2)`, turnover cost 5 bp, cash leg on the previous bar's yield, excess Sharpe ×√252, the 252-bar warmup and the two period protocols. Signals re-implemented: SMA200 monthly, buy-and-hold, S06 `tom`, S10 `avg`, S09 `ratio<0.95`.

| Item | Period | Original | Independent | Diff |
|------|--------|----------|-------------|------|
| SMA200 monthly | dev | 0.6437 | 0.6437 | 0.0000 |
| SMA200 monthly | val | 0.5722 | 0.5722 | 0.0000 |
| SMA200 monthly | holdout | 0.6575 | 0.6569 | −0.0006 |
| SMA200 monthly | full | 0.6297 | 0.6296 | −0.0001 |
| Buy-and-hold | dev | 0.5110 | 0.5110 | 0.0000 |
| Buy-and-hold | val | 0.3190 | 0.3190 | 0.0000 |
| Buy-and-hold | holdout | 0.7808 | 0.7803 | −0.0004 |
| Buy-and-hold | full | 0.5133 | 0.5132 | −0.0001 |
| S06 tom | dev | 0.9603 | 0.9603 | 0.0000 |
| S06 tom | val | 0.3352 | 0.3352 | 0.0000 |
| S06 tom | holdout | 0.2506 | 0.2506 | 0.0000 |
| S06 tom | full | 0.6685 | 0.6685 | 0.0000 |
| S10 avg | dev | 0.6907 | 0.6907 | 0.0000 |
| S10 avg | val | 0.5549 | 0.5549 | 0.0000 |
| S10 avg | holdout | 0.7601 | 0.7596 | −0.0005 |
| S10 avg | full | 0.6750 | 0.6749 | −0.0001 |
| S09 ratio<0.95 | dev | 0.7225 | 0.7225 | 0.0000 |
| S09 ratio<0.95 | val | 0.3352 | 0.3352 | 0.0000 |
| S09 ratio<0.95 | holdout | 0.5595 | 0.5583 | −0.0012 |
| S09 ratio<0.95 | full | 0.5713 | 0.5707 | −0.0006 |

All 20 comparisons are within the 0.01 tolerance (max |diff| 0.0012). Dev and val agree to four decimals; the small holdout/full drift is because the price cache now extends to 2026-10-19, a few bars beyond the registry runs — it is not an engine difference. A11-01 none.

### 7.2 Quoted numbers (`audit/a12_spot_check.py`)

- PLAN-stage2.md §6 results table vs `registry.csv` finals: **100 cells checked, 0 mismatches** (A12-01).
- `benchmarks/benchmarks.csv` SMA200 dev 0.64 / val 0.57 / holdout 0.66 and B&H 0.51 / 0.32 / 0.78 match PLAN-stage2 §6.
- Every number quoted in the ten notebooks' Interpretation cells is consistent with the registry; apparent discrepancies are reproduced as differences (e.g. S07 "dev B&H 1.02" = 0.83 + 0.20; S09 "val SMA200 0.77" = 0.34 + 0.44; S08 quotes SMA200 dev 0.63 because the benchmark is re-sliced to S08's later dev start). A12-02 none.

### 7.3 Full-strategy return rebuild (`audit/a8_build_returns.py`)

Independently of the replication above, every strategy's daily return series was rebuilt from its builder's signal through the Stage-1 engine; all ten full-period Sharpes agree with the registry within 0.0006 (cached in `a8_returns.pkl` and used by §6).

## 8. Fixes applied, process checks, and what remains unverified

### 8.1 Fixes applied — none

No confirmed bug changes a result, so nothing was modified outside `notebooks/backtest/audit/`, `AUDIT.md` and `audit.csv`. The PLAN-stage2.md deviation log is unchanged. Candidates considered and rejected as fixes: A1-02 (last-bar BDay rule — affects only a live sample's final bar; a change would alter the engine for all strategies and is deferred to a future stage), A6-01 (S06 holiday timing — the exact-intended signal would be a new trial and does not change the verdict), A8-02 (DSR — frozen metric; reported instead).

### 8.2 Process integrity (`audit/a10_process.py`)

- Every builder `VARIANTS` key has a `<ID>-vK/dev` row in `registry.csv` and vice versa (A10-01).
- `stage2.dev_sweep` scores only `slice_period(..., "dev")`; the chosen variant is the best-dev variant in all nine Stage-2 strategies; no variant has a val/holdout/full row, so the holdout never influenced a choice (A10-02).
- Strategy cards vs build scripts: three undocumented differences (A10-03 S02, A10-04 S08, A10-05 S06) are documentation gaps; the registry scores the executed signal.

### 8.3 Final checks

- `pytest notebooks/backtest/checks -q -p no:cacheprovider`: 52 passed (see chat summary for the final run).
- `rerun_regression.py --dry-run`: 0 changed key lines.
- Every audit `.py` black-formatted (`-t py312`).

### 8.4 Unverified / out of scope

- **S07 EDGAR data** was not re-downloaded; the audit used the cached `.cache/notebooks/edgar/` files and verified the logic, not the download.
- **FRED data revisions**: UNRATE, BAA/AAA, TB3MS are current-vintage; only S03 `rt` uses a real-time series. Effect quantified only indirectly (S03 fails widely).
- **UNRATE release calendar before the 1960s and shutdown-delayed releases** (A3-03): the 7-day margin is asserted from current BLS practice, not checked month by month.
- **Pre-1988 synthetic total return**: Shiller D is a smoothed annual series; spreading it evenly is an assumption. It affects returns equally for strategies and benchmarks.
- **Ticker→CIK map vintage (S07)**: survivorship direction unknown; a point-in-time map was not available offline.
- **S06 holiday mismatches** (1.06 % of days) were quantified but the exact per-holiday attribution was not listed.
- **Benchmark dev-window offset** (A11-02) is informational; `stage2.evaluate` neutralises it.
- Nothing here used an LLM agent run, live trading data feeds, or any connectivity beyond the local cache.