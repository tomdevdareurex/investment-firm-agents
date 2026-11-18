"""Tests for bt_ml walk-forward helpers (synthetic data, no network)."""

import numpy as np
import pandas as pd
import pytest

import bt_ml as bm


@pytest.fixture(scope="module")
def frame():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("1990-01-01", periods=252 * 20)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))), idx)
    return close


def test_forward_return_shape_and_nan_tail(frame):
    y = bm.forward_return(frame, 21)
    assert y.index.equals(frame.index)
    assert y.iloc[-21:].isna().all()
    assert np.isclose(y.iloc[0], np.log(frame.iloc[21] / frame.iloc[0]))


def test_splits_respect_purge_and_embargo(frame):
    idx = frame.index
    folds = bm.walk_forward_splits(
        idx, train_min=2520, test_len=252, purge=21, embargo=21
    )
    assert len(folds) >= 8
    bm.assert_folds_disjoint(folds, 21, idx)
    pos = {t: i for i, t in enumerate(idx)}
    for k in range(1, len(folds)):
        gap = pos[folds[k].test[0]] - pos[folds[k - 1].test[-1]] - 1
        assert gap == 21
    for f in folds:
        assert pos[f.test[0]] - pos[f.train[-1]] - 1 == 21


def test_rolling_window_caps_train_length(frame):
    idx = frame.index
    folds = bm.walk_forward_splits(
        idx,
        train_min=1260,
        test_len=252,
        purge=21,
        embargo=0,
        expanding=False,
        train_max=1000,
    )
    assert all(f.n_train <= 1000 for f in folds)
    assert folds[-1].n_train == 1000


def test_assert_folds_disjoint_catches_leak(frame):
    idx = frame.index
    leaky = [bm.Fold(idx[:300], idx[290:400])]
    with pytest.raises(AssertionError):
        bm.assert_folds_disjoint(leaky, 0, idx)


def test_bad_args_raise(frame):
    with pytest.raises(ValueError):
        bm.walk_forward_splits(frame.index, purge=-1)


class _OLS:
    def fit(self, X, y):
        X1 = np.c_[np.ones(len(X)), X]
        self.b = np.linalg.lstsq(X1, y, rcond=None)[0]
        return self

    def predict(self, X):
        return np.c_[np.ones(len(X)), X] @ self.b


def test_walk_forward_predict_recovers_planted_signal(frame):
    rng = np.random.default_rng(7)
    idx = frame.index
    x = pd.Series(rng.normal(size=len(idx)), idx)
    y = 0.5 * x + pd.Series(rng.normal(scale=0.1, size=len(idx)), idx)
    X = pd.DataFrame({"x": x})
    folds = bm.walk_forward_splits(
        idx, train_min=1260, test_len=252, purge=5, embargo=5
    )
    pred = bm.walk_forward_predict(X, y, _OLS, folds)
    assert pred.notna().sum() > 0.6 * len(idx)
    s = bm.oos_summary(pred, y)
    assert s["ic"] > 0.9 and s["hit"] > 0.9


def test_walk_forward_predict_no_information_with_naive_mean(frame):
    rng = np.random.default_rng(8)
    idx = frame.index
    X = pd.DataFrame({"x": rng.normal(size=len(idx))}, index=idx)
    y = pd.Series(rng.normal(size=len(idx)), idx)
    folds = bm.walk_forward_splits(
        idx, train_min=1260, test_len=252, purge=5, embargo=5
    )
    pred = bm.walk_forward_predict(X, y, bm.NaiveMean, folds)
    # constant within each fold -> correlation undefined within fold; overall IC ~ 0
    s = bm.oos_summary(pred, y)
    assert abs(s["ic"]) < 0.1


def test_predict_only_uses_test_rows_and_handles_nan(frame):
    idx = frame.index
    X = pd.DataFrame({"x": np.arange(len(idx), dtype=float)}, index=idx)
    X.iloc[1300, 0] = np.nan
    y = X["x"] * 2
    folds = bm.walk_forward_splits(
        idx, train_min=1260, test_len=252, purge=5, embargo=5
    )
    pred = bm.walk_forward_predict(X, y, _OLS, folds)
    test_union = pd.Index(np.concatenate([f.test for f in folds]))
    assert pred.index.equals(test_union.sort_values())
    assert np.isnan(pred.loc[idx[1300]])


def test_prediction_to_signal_fill_and_threshold(frame):
    idx = frame.index
    pred = pd.Series([0.1, -0.2, np.nan], index=idx[1000:1003])
    sig = bm.prediction_to_signal(pred, idx, threshold=0.0, fill=1.0)
    assert sig.index.equals(idx)
    assert sig.iloc[0] == 1.0
    assert sig.loc[idx[1000]] == 1.0
    assert sig.loc[idx[1001]] == 0.0
    assert sig.loc[idx[1002]] == 1.0
    assert set(sig.unique()) <= {0.0, 1.0}
