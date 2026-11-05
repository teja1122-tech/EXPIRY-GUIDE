"""Forecasting for arbitrary store/SKU counts. Poisson gradient boosting when >= 1 year of history, level model otherwise."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from .config import HORIZON

FEATS = ["store", "sku", "cat", "l7", "l28", "l90", "l180", "h", "sin_doy", "cos_doy", "dow"]


def feature_matrix(S, cat_of_sku, start, o, hs):
    _, N, K = S.shape; P, H = N*K, len(hs)
    store = np.repeat(np.arange(N), K); sku = np.tile(np.arange(K), N); cat = cat_of_sku[sku]
    lv = [S[max(0, o-w):o].mean(0).reshape(-1) for w in (7, 28, 90, 180)]
    dt = start + pd.to_timedelta(o + np.asarray(hs), "D"); doy, dow = dt.dayofyear.values, dt.dayofweek.values
    cols = [np.repeat(x, H) for x in (store, sku, cat, *lv)]
    cols += [np.tile(hs, P), np.tile(np.sin(2*np.pi*doy/365.25), P), np.tile(np.cos(2*np.pi*doy/365.25), P), np.tile(dow, P)]
    return np.column_stack(cols).astype(np.float32)


def build_training(S, cat, start, origins, last_target_day, per_origin=12, seed=0):
    rng = np.random.default_rng(seed); X, y = [], []; _, N, K = S.shape
    if N*K > 2000: per_origin = 6
    for o in origins:
        hmax = min(HORIZON, last_target_day - o + 1)
        if hmax <= 0: continue
        hs = np.sort(rng.choice(hmax, size=min(per_origin, hmax), replace=False))
        X.append(feature_matrix(S, cat, start, o, hs)); y.append(S[o + hs].reshape(len(hs), N*K).T.reshape(-1))
    return np.vstack(X), np.concatenate(y)


def fit_gbm(X, y):
    return HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=100,
                                         l2_regularization=1.0, random_state=0,
                                         categorical_features=[True, True, True] + [False]*(len(FEATS)-3)).fit(X, y)


def predict_gbm(model, S, cat, start, o, horizon=HORIZON):
    _, N, K = S.shape
    return np.clip(model.predict(feature_matrix(S, cat, start, o, np.arange(horizon))), 1e-4, None).reshape(N, K, horizon)


def level_forecast(S, start, o, horizon=HORIZON):
    """Blend of 28- and 90-day averages x day-of-week profile. Used when history is too short for the ML model."""
    base = 0.6*S[max(0, o-28):o].mean(0) + 0.4*S[max(0, o-90):o].mean(0)
    dts = start + pd.to_timedelta(np.arange(max(0, o-90), o), "D"); tot = S[max(0, o-90):o].sum((1, 2)).astype(float)
    dow = pd.Series(tot).groupby(dts.dayofweek.values).mean().reindex(range(7)).fillna(tot.mean()); prof = (dow/dow.mean()).values
    fdow = (start + pd.to_timedelta(o + np.arange(horizon), "D")).dayofweek.values
    return np.clip(base[:, :, None]*prof[fdow][None, None, :], 1e-4, None)


def _naive(S, o, window, horizon=HORIZON):
    return np.repeat(np.clip(S[max(0, o-window):o].mean(0), 1e-4, None)[:, :, None], horizon, axis=2)


def _dev(y, mu):
    mu = np.clip(mu, 1e-6, None); t = np.where(y > 0, y*np.log(np.clip(y, 1e-9, None)/mu), 0.0)
    return float(np.mean(2*(t-(y-mu))))


def backtest(S, cat, start, train_origins, train_last, val_origins, val_last, block=28):
    X, y = build_training(S, cat, start, train_origins, train_last); model = fit_gbm(X, y)
    names = ["GBM (Poisson)", "Naive 28d mean", "Naive 90d mean"]; mus = {n: [] for n in names}; act = []
    for o in val_origins:
        hmax = min(HORIZON, val_last - o + 1); act.append(S[o:o+hmax].transpose(1, 2, 0))
        mus[names[0]].append(predict_gbm(model, S, cat, start, o)[:, :, :hmax])
        mus[names[1]].append(_naive(S, o, 28)[:, :, :hmax]); mus[names[2]].append(_naive(S, o, 90)[:, :, :hmax])
    N, K = S.shape[1:]; rows = []
    for n in names:
        num = den = bn = 0.0; dv = []
        for a, m in zip(act, mus[n]):
            nb = a.shape[2]//block
            if nb == 0: continue
            A = a[:, :, :nb*block].reshape(N, K, nb, block).sum(3); M = m[:, :, :nb*block].reshape(N, K, nb, block).sum(3)
            num += np.abs(A-M).sum(); den += A.sum(); bn += (M-A).sum(); dv.append(_dev(a, m))
        rows.append(dict(model=n, WAPE_28d=num/max(den, 1), bias=bn/max(den, 1), daily_poisson_deviance=float(np.mean(dv))))
    return pd.DataFrame(rows), act, mus[names[0]]


def estimate_alpha(act, mu_list, block=56):
    N, K = act[0].shape[:2]; xs, ys = [], []
    for a, m in zip(act, mu_list):
        nb = a.shape[2]//block
        if nb == 0: continue
        A = a[:, :, :nb*block].reshape(N, K, nb, block).sum(3).ravel(); M = m[:, :, :nb*block].reshape(N, K, nb, block).sum(3).ravel()
        xs.append(M**2); ys.append((A-M)**2 - M)
    if not xs: return 0.25
    x, y = np.concatenate(xs), np.concatenate(ys)
    return float(np.clip((x*y).sum()/max((x*x).sum(), 1e-9), 0.05, 1.0))


def make_forecast(ds, progress=None):
    """Returns dict(fc, alpha, method, backtest, notes). fc has shape (stores, skus, HORIZON) starting at ds.as_of."""
    S, T, start = ds.S, ds.T, ds.start; cat = pd.factorize(ds.skus.category)[0]; notes = []; bt = None
    cb = progress or (lambda f, m: None)
    if T < 365:
        cb(0.5, "Level forecast"); fc = level_forecast(S, start, T)
        notes.append(f"Only {T} days of history: used a level + weekday model (no seasonality). Upload 12+ months for the ML model.")
        return dict(fc=fc, alpha=0.35, method="Level + weekday profile", backtest=None, notes=notes)
    alpha = 0.25
    if T >= 540:
        cb(0.15, "Backtesting on unseen weeks"); vs = T - 240
        bt, act, mu = backtest(S, cat, start, range(180, vs-HORIZON+1, 14), vs, range(vs, T-HORIZON+1, 14), T-1)
        alpha = estimate_alpha(act, mu)
    else:
        notes.append("History under 18 months: accuracy backtest skipped and over-dispersion assumed (0.25). Risk scores are less well-calibrated.")
    cb(0.5, "Training final model")
    model = fit_gbm(*build_training(S, cat, start, range(180, T, 14), T-1))
    cb(0.9, "Forecasting")
    return dict(fc=predict_gbm(model, S, cat, start, T), alpha=alpha, method="Poisson gradient boosting", backtest=bt, notes=notes)
