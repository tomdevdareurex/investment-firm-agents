"""Walk-forward machine-learning helpers with purge and embargo.

Rules shared by every ML strategy notebook in this programme:

* Train only on data strictly before the test window; drop the last ``purge``
  observations of the training set (their labels overlap the test period) and
  skip ``embargo`` observations after each test window before training resumes.
* Features must be point-in-time (see ``bt_pit``); labels are forward returns
  over ``horizon`` bars, so ``purge >= horizon``.
* Models are refit per fold from a fresh ``model_factory()`` so no state leaks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_HORIZON = 21
DEFAULT_TEST_LEN = 252
DEFAULT_TRAIN_MIN = 252 * 10
DEFAULT_EMBARGO = 21


@dataclass(frozen=True)
class Fold:
    train: pd.Index
    test: pd.Index

    @property
    def n_train(self) -> int:
        return len(self.train)

    @property
    def n_test(self) -> int:
        return len(self.test)


def forward_return(close: pd.Series, horizon: int = DEFAULT_HORIZON) -> pd.Series:
    """Label: log return from t to t+horizon (NaN for the last ``horizon`` rows)."""
    return np.log(close.shift(-horizon) / close)


def walk_forward_splits(
    index: pd.Index,
    train_min: int = DEFAULT_TRAIN_MIN,
    test_len: int = DEFAULT_TEST_LEN,
    purge: int = DEFAULT_HORIZON,
    embargo: int = DEFAULT_EMBARGO,
    expanding: bool = True,
    train_max: int | None = None,
) -> list[Fold]:
    """Expanding (or rolling) walk-forward folds over ``index``.

    Fold k tests ``index[s:s+test_len]`` where ``s = train_min + k*(test_len+embargo)``
    ... and trains on ``index[lo : s-purge]`` with ``lo = 0`` (expanding) or
    ``s - purge - train_max`` (rolling).  Folds with fewer than ``test_len // 2``
    test rows are dropped.
    """
    if purge < 0 or embargo < 0:
        raise ValueError("purge and embargo must be >= 0")
    n = len(index)
    folds: list[Fold] = []
    s = train_min
    while s < n:
        e = min(s + test_len, n)
        if e - s < max(1, test_len // 2):
            break
        hi = s - purge
        lo = 0 if expanding or train_max is None else max(0, hi - train_max)
        if hi - lo >= max(30, train_min // 2):
            folds.append(Fold(index[lo:hi], index[s:e]))
        s = e + embargo
    return folds


def assert_folds_disjoint(folds: list[Fold], purge: int, index: pd.Index) -> None:
    """Raise if any fold's training set reaches into its test window minus purge."""
    pos = {ts: i for i, ts in enumerate(index)}
    for k, f in enumerate(folds):
        if f.n_train == 0 or f.n_test == 0:
            raise AssertionError(f"fold {k}: empty train or test")
        last_train = pos[f.train[-1]]
        first_test = pos[f.test[0]]
        if last_train >= first_test - purge:
            raise AssertionError(
                f"fold {k}: train ends {last_train}, test starts {first_test}, purge {purge}"
            )
        if k and pos[f.test[0]] <= pos[folds[k - 1].test[-1]]:
            raise AssertionError(f"fold {k}: test windows overlap")


def walk_forward_predict(
    X: pd.DataFrame,
    y: pd.Series,
    model_factory,
    folds: list[Fold],
    *,
    fit_kwargs: dict | None = None,
) -> pd.Series:
    """Out-of-sample predictions, one fresh model per fold.

    Rows with NaN in ``X`` or ``y`` are dropped from training; test rows with NaN
    features get NaN predictions.  Returns a float Series aligned to the union of
    all test indices (NaN elsewhere is not included).
    """
    fit_kwargs = fit_kwargs or {}
    preds: list[pd.Series] = []
    for f in folds:
        xt = X.loc[f.train]
        yt = y.loc[f.train]
        ok = xt.notna().all(axis=1) & yt.notna()
        if ok.sum() < 30:
            preds.append(pd.Series(np.nan, index=f.test, dtype=float))
            continue
        model = model_factory()
        model.fit(xt[ok].to_numpy(), yt[ok].to_numpy(), **fit_kwargs)
        xs = X.loc[f.test]
        good = xs.notna().all(axis=1)
        out = pd.Series(np.nan, index=f.test, dtype=float)
        if good.any():
            out[good] = np.asarray(model.predict(xs[good].to_numpy()), dtype=float)
        preds.append(out)
    if not preds:
        return pd.Series(dtype=float)
    return pd.concat(preds).sort_index()


def prediction_to_signal(
    pred: pd.Series,
    index: pd.Index,
    threshold: float = 0.0,
    fill: float = 1.0,
) -> pd.Series:
    """Long (1) when ``pred > threshold`` else flat (0); ``fill`` before the first
    prediction / where pred is NaN (default 1.0 = stay in B&H, the honest prior).
    """
    sig = (pred > threshold).astype(float)
    sig[pred.isna()] = np.nan
    return sig.reindex(index).fillna(fill)


def oos_summary(pred: pd.Series, y: pd.Series) -> dict:
    """Information coefficient and hit rate of OOS predictions vs realised labels."""
    df = pd.concat({"pred": pred, "y": y}, axis=1, sort=True).dropna()
    if len(df) < 10:
        return {"n": int(len(df)), "ic": np.nan, "hit": np.nan, "rank_ic": np.nan}
    return {
        "n": int(len(df)),
        "ic": float(df["pred"].corr(df["y"])),
        "rank_ic": float(df["pred"].corr(df["y"], method="spearman")),
        "hit": float((np.sign(df["pred"]) == np.sign(df["y"])).mean()),
    }


class NaiveMean:
    """Baseline model: predicts the training-set mean label (zero information)."""

    def __init__(self) -> None:
        self.mu = 0.0

    def fit(self, X, y):
        self.mu = float(np.mean(y))
        return self

    def predict(self, X):
        return np.full(len(X), self.mu)


__all__ = [
    "DEFAULT_HORIZON",
    "DEFAULT_TEST_LEN",
    "DEFAULT_TRAIN_MIN",
    "DEFAULT_EMBARGO",
    "Fold",
    "forward_return",
    "walk_forward_splits",
    "assert_folds_disjoint",
    "walk_forward_predict",
    "prediction_to_signal",
    "oos_summary",
    "NaiveMean",
]
