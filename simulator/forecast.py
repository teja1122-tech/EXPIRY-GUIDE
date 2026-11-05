"""Step 2 - demand forecasting per store x SKU, daily, up to HORIZON days ahead.

Model: gradient-boosted trees with a Poisson loss (right loss for small non-negative counts).
Direct multi-horizon: features are known at forecast time (recent sales levels, store, SKU, category,
calendar of the *target* day, horizon). No recursive forecasting, so errors do not compound.
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from config import *
from world import N, K

START = pd.Timestamp(START_DATE)
FEATS = ["store", "sku", "cat", "l7", "l28", "l90", "l180", "h", "sin_doy", "cos_doy", "dow"]


def feature_matrix(S, cat_of_sku, o, hs):
    """Rows = (store,sku) pair x horizon. Uses only sales BEFORE origin o (no leakage)."""
    P, H = N*K, len(hs)
    store = np.repeat(np.arange(N), K); sku = np.tile(np.arange(K), N); cat = cat_of_sku[sku]
    lv = [S[max(0, o-w):o].mean(0).reshape(-1) for w in (7, 28, 90, 180)]
    dt = START + pd.to_timedelta(o + np.asarray(hs), "D")
    doy, dow = dt.dayofyear.values, dt.dayofweek.values
    cols = [np.repeat(x, H) for x in (store, sku, cat, *lv)]
    cols += [np.tile(hs, P), np.tile(np.sin(2*np.pi*doy/365.25), P), np.tile(np.cos(2*np.pi*doy/365.25), P), np.tile(dow, P)]
    return np.column_stack(cols).astype(np.float32)


def build_training(S, cat_of_sku, origins, last_target_day, per_origin=12, seed=0):
    rng = np.random.default_rng(seed); X, y = [], []
    for o in origins:
        hmax = min(HORIZON, last_target_day - o + 1)
        if hmax <= 0: continue
        hs = np.sort(rng.choice(hmax, size=min(per_origin, hmax), replace=False))
        X.append(feature_matrix(S, cat_of_sku, o, hs))
        y.append(S[o + hs].reshape(len(hs), N*K).T.reshape(-1))
    return np.vstack(X), np.concatenate(y)


def fit_gbm(X, y):
    m = HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                      min_samples_leaf=100, l2_regularization=1.0, random_state=0,
                                      categorical_features=[True, True, True] + [False]*(len(FEATS)-3))
    return m.fit(X, y)


def predict(model, S, cat_of_sku, o, horizon=HORIZON):
    """Expected demand per day for the next `horizon` days -> array (N, K, horizon)."""
    hs = np.arange(horizon)
    mu = model.predict(feature_matrix(S, cat_of_sku, o, hs))
    return np.clip(mu, 1e-4, None).reshape(N, K, horizon)


def naive_flat(S, o, window, horizon=HORIZON):
    return np.repeat(np.clip(S[max(0, o-window):o].mean(0), 1e-4, None)[:, :, None], horizon, axis=2)


def poisson_deviance(y, mu):
    mu = np.clip(mu, 1e-6, None)
    t = np.where(y > 0, y*np.log(np.clip(y, 1e-9, None)/mu), 0.0)
    return float(np.mean(2*(t - (y - mu))))


def backtest(S, cat_of_sku, train_origins, train_last_day, val_origins, val_last_day, block=28):
    """Train only on information up to train_last_day, evaluate on origins/targets strictly after it."""
    X, y = build_training(S, cat_of_sku, train_origins, train_last_day)
    model = fit_gbm(X, y)
    rows = {"GBM (Poisson)": [], "Naive 28d mean": [], "Naive 90d mean": []}; act = []
    mus = {k: [] for k in rows}
    for o in val_origins:
        hmax = min(HORIZON, val_last_day - o + 1)
        a = S[o:o+hmax].transpose(1, 2, 0)                          # (N,K,hmax)
        act.append(a)
        mus["GBM (Poisson)"].append(predict(model, S, cat_of_sku, o)[:, :, :hmax])
        mus["Naive 28d mean"].append(naive_flat(S, o, 28)[:, :, :hmax])
        mus["Naive 90d mean"].append(naive_flat(S, o, 90)[:, :, :hmax])
    out = []
    for name in rows:
        wape_num = wape_den = bias_num = 0.0; dev = []; slow_n = slow_d = 0.0
        for a, m in zip(act, mus[name]):
            nb = a.shape[2] // block
            if nb == 0: continue
            A = a[:, :, :nb*block].reshape(N, K, nb, block).sum(3); M = m[:, :, :nb*block].reshape(N, K, nb, block).sum(3)
            wape_num += np.abs(A-M).sum(); wape_den += A.sum(); bias_num += (M-A).sum()
            slow = (S[:val_origins[0]].mean(0) < 0.3)[:, :, None]
            slow_n += (np.abs(A-M)*slow).sum(); slow_d += (A*slow).sum()
            dev.append(poisson_deviance(a, m))
        out.append(dict(model=name, WAPE_28d=wape_num/wape_den, bias=bias_num/wape_den,
                        WAPE_28d_slow_movers=slow_n/slow_d, daily_poisson_deviance=float(np.mean(dev))))
    return model, pd.DataFrame(out), act, mus["GBM (Poisson)"]


def estimate_alpha(act, mu_list, block=56):
    """Over-dispersion of window demand: Var = mu + alpha*mu^2 (negative binomial). Moment estimator."""
    xs, ys = [], []
    for a, m in zip(act, mu_list):
        nb = a.shape[2] // block
        if nb == 0: continue
        A = a[:, :, :nb*block].reshape(N, K, nb, block).sum(3).ravel(); M = m[:, :, :nb*block].reshape(N, K, nb, block).sum(3).ravel()
        xs.append(M**2); ys.append((A-M)**2 - M)
    x, y = np.concatenate(xs), np.concatenate(ys)
    return float(max(0.02, (x*y).sum()/(x*x).sum()))
