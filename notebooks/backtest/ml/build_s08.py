"""Build ml/ml_walkforward.ipynb (S08). Usage: python build_s08.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S08 - Machine-learning walk-forward on Welch-Goyal-style predictors (ML)

**Hypothesis.** No single predictor times the market reliably (Welch & Goyal 2008), but a
regularised model that combines valuation, rates, credit, trend and volatility might, if it is
trained strictly out of sample (Rapach, Strauss & Zhou 2010; Gu, Kelly & Xiu 2020).

**Model.** At each month-end *t*, predict P(next-month S&P 500 return > T-bill return) and hold
equities when it is > 0.5. Walk-forward: refit every 12 months on all earlier months (expanding,
first fit after 120 months), purge 1 month so no training label overlaps the test months, fresh
model per fold, fixed seed. Variants (fixed in advance): logistic regression C = 0.1 / 1
(standardised features), gradient boosting depth 2 / 3. Baseline: training-mean predictor
(`bt_ml.NaiveMean`), shown but not traded.

**Features and point-in-time lags**

| Feature | Source | Lag used |
|---|---|---|
| dividend yield D/P | Shiller monthly | month M usable from M+2 |
| earnings yield E/P | Shiller monthly (E interpolated from quarterly) | M+4 (extra quarter, interpolation) |
| term spread AAA - TB3MS, credit spread BAA - AAA, T-bill level | FRED monthly averages | M+1 + 7 days |
| 12-month and 1-month total return, 21-day realised vol, close / SMA200 - 1 | daily S&P 500 | up to the decision close |

Monthly check, next-close execution, 5 bp per switch. Shiller data end 2024-09, so the two
valuation features are frozen at their last value afterwards (holdout tail).

**Sources.** Welch & Goyal (2008), RFS doi:10.1093/rfs/hhm014; Goyal, Welch & Zafirov (2024),
SSRN 3929119; Rapach, Strauss & Zhou (2010), SSRN 1257858; Gu, Kelly & Xiu (2020), NBER w25398;
scikit-learn (BSD-3).

> Decision-support research only; never places orders."""

DATA = """import bt_ml

sh = sample["shiller"]
inputs = {"px": px, "cash": cash, "shiller": sh[["P", "D", "E"]].dropna()}
for s in ("BAA", "AAA", "TB3MS"):
    inputs[s] = bt_long.fred_series(s)
print("Shiller", sh.index[0], "->", sh.index[-1], "| FRED to", inputs["TB3MS"].index[-1].date())"""

SIGNAL = """from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

TRAIN_MIN, TEST_LEN, PURGE = 120, 12, 1  # months
FEATURES = ["dp", "ep", "term", "credit", "tbill", "mom12", "ret1", "vol21", "sma_dist"]


class Prob:
    # wraps a classifier so bt_ml.walk_forward_predict gets P(class 1) from .predict
    def __init__(self, est):
        self.est = est

    def fit(self, X, y):
        self.const = float(np.mean(y)) if len(np.unique(y)) < 2 else None
        if self.const is None:
            self.est.fit(X, y)
        return self

    def predict(self, X):
        return np.full(len(X), self.const) if self.const is not None else self.est.predict_proba(X)[:, 1]


def model_factory(kind, c=1.0, depth=2):
    if kind == "logit":
        return lambda: Prob(make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=2000)))
    if kind == "gbm":
        return lambda: Prob(HistGradientBoostingClassifier(max_depth=depth, max_iter=100, learning_rate=0.05, random_state=42))
    return bt_ml.NaiveMean


def features(inputs):
    px_, idx = inputs["px"], inputs["px"].index
    tr, close = px_["tr_close"], px_["close"]
    sh = inputs["shiller"].copy()
    sh.index = sh.index.to_timestamp(how="start")
    pit = bt_pit.monthly_to_daily_pit
    day = pd.DataFrame(index=idx)
    day["dp"] = pit(sh["D"] / sh["P"], idx, months=1)
    day["ep"] = pit(sh["E"] / sh["P"], idx, months=3)
    for name, ser in (("term", inputs["AAA"] - inputs["TB3MS"]), ("credit", inputs["BAA"] - inputs["AAA"]), ("tbill", inputs["TB3MS"])):
        day[name] = pit(ser.dropna(), idx, months=0, days=7)
    r = tr.pct_change(fill_method=None)
    day["mom12"] = tr / tr.shift(252) - 1
    day["ret1"] = tr / tr.shift(21) - 1
    day["vol21"] = r.rolling(21).std() * np.sqrt(252)
    day["sma_dist"] = close / close.rolling(200).mean() - 1
    dec = idx[bc.check_days(idx, "monthly").to_numpy()]
    X = day.loc[dec, FEATURES]
    ci = (1 + inputs["cash"].reindex(idx).fillna(0.0)).cumprod()
    nxt = pd.Series(dec, index=dec).shift(-1)
    ok = nxt.notna()
    y = pd.Series(np.nan, index=dec)
    y[ok] = (tr[nxt[ok]].to_numpy() / tr[dec[ok]].to_numpy() - 1) - (ci[nxt[ok]].to_numpy() / ci[dec[ok]].to_numpy() - 1)
    return X, (y > 0).astype(float).where(y.notna()), y


def predict(inputs, kind="logit", c=1.0, depth=2):
    X, ycls, _ = features(inputs)
    X = X.dropna()
    ycls = ycls.reindex(X.index)
    folds = []
    for s in range(TRAIN_MIN, len(X), TEST_LEN):  # calendar-anchored folds, partial last fold kept
        folds.append(bt_ml.Fold(X.index[: s - PURGE], X.index[s : s + TEST_LEN]))
    bt_ml.assert_folds_disjoint(folds, PURGE, X.index)
    return bt_ml.walk_forward_predict(X, ycls, model_factory(kind, c, depth), folds)


def build_signal(inputs, kind="logit", c=1.0, depth=2):
    pred = predict(inputs, kind, c, depth)
    sig = (pred > 0.5).astype(float).where(pred.notna())
    idx = inputs["px"].index
    return sig.reindex(sig.index.union(idx)).ffill().reindex(idx)


VARIANTS = {
    "logit_c0.1": dict(kind="logit", c=0.1),
    "logit_c1": dict(kind="logit", c=1.0),
    "gbm_d2": dict(kind="gbm", depth=2),
    "gbm_d3": dict(kind="gbm", depth=3),
}
PARAMS_TEXT = {n: f"{n}; 9 PIT features; yearly expanding refit, purge 1m; P>0.5; monthly; next_close; 5bp" for n in VARIANTS}"""

CHART = """X, ycls, yex = features(inputs)
rows = {}
for name, p in {**VARIANTS, "naive_mean (baseline)": dict(kind="naive")}.items():
    pred = predict(inputs, **p)
    rows[name] = {**bt_ml.oos_summary(pred - 0.5, yex), "share P>0.5": float((pred.dropna() > 0.5).mean())}
print("Out-of-sample quality of P(up) - 0.5 against realised next-month excess return (all OOS months)")
display(pd.DataFrame(rows).T.round(3))
Xd = X.dropna()
lr = model_factory("logit", 1.0)().fit(Xd.iloc[:-1].to_numpy(), ycls.reindex(Xd.index).iloc[:-1].to_numpy())
coef = pd.Series(lr.est[-1].coef_[0], index=FEATURES).sort_values()
print("Logistic C=1 coefficients on standardised features, fitted on all months (plausibility check only):")
display(coef.round(3).to_frame("coef"))"""

CAVEATS = """* Out-of-sample by construction (walk-forward, purge), but the *choice* of features and models is
  informed by the literature, which was written with hindsight over much of this sample.
* Monthly data: about 900 training months at most and ~11 positive / negative regimes per decade;
  machine learning has little data to learn from here.
* The OOS table above mixes dev, val and holdout months; it is descriptive only.
* Shiller valuation features are frozen after 2024-09."""

SPEC = dict(
    trial_id="S08",
    strategy="ml_walkforward",
    folder="ml",
    name="ml_walkforward",
    title="S08",
    protocol="main",
    rebalance="monthly",
    header_md=HEADER,
    data_code=DATA,
    signal_code=SIGNAL,
    chart_code=CHART,
    caveats_md=CAVEATS,
    n_cuts=6,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
