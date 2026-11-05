"""Step 3 - expiry-risk scoring.

For one (store, SKU), batches are sold First-Expiry-First-Out. Batch b can only start selling after all
earlier-expiring units are gone, so with C_b = cumulative units up to and including b, and D_b = demand
between now and b's expiry:
    P(any unit of b expires unsold)  = P(D_b <= C_b - 1)
    E[units of b expiring unsold]    = sum_{j=1..q_b} P(D_b <= C_b - j)
    P(unit at queue position n sells) = P(D_b >= n)
D_b ~ NegativeBinomial(mean = sum of daily forecasts, var = mu + alpha*mu^2).
"""
import numpy as np, pandas as pd
from scipy.stats import nbinom
from config import *


def cdf(k, mu, alpha):
    k = np.asarray(k); r = 1.0/alpha; p = r/(r + max(float(mu), 1e-9))
    return np.where(k < 0, 0.0, nbinom.cdf(np.maximum(k, 0), r, p))


def score_batches(bt, fc, o, alpha, cost):
    """bt: batch table (s,k,bid,exp,qty) at origin o. fc: forecast (N,K,HORIZON) from origin o."""
    bt = bt.sort_values(["s", "k", "exp", "bid"]).reset_index(drop=True).copy()
    bt["days_left"] = bt.exp - o
    bt["C"] = bt.groupby(["s", "k"]).qty.cumsum(); bt["C_prev"] = bt.C - bt.qty
    mu = np.full(len(bt), np.nan); p_un = np.full(len(bt), np.nan); e_un = np.full(len(bt), np.nan); risky = np.zeros(len(bt), int)
    for i, r in enumerate(bt.itertuples(index=False)):
        d = int(r.days_left)
        if d > HORIZON: continue                              # too far out to score reliably; re-scored in later weeks
        m = float(fc[r.s, r.k, :max(d, 0)].sum()); mu[i] = m
        p_un[i] = float(cdf(r.C - 1, m, alpha))
        j = np.arange(1, r.qty + 1)
        e_un[i] = float(cdf(r.C - j, m, alpha).sum())
        n = np.arange(r.C_prev + 1, r.C + 1)                  # queue positions of this batch's units
        risky[i] = int((cdf(n - 1, m, alpha) >= 1 - THETA_SRC).sum())   # units with P(sell) <= THETA_SRC
    bt["mu"], bt["p_unsold"], bt["exp_unsold_units"], bt["at_risk_units"] = mu, p_un, e_un, risky
    bt["scored"] = ~np.isnan(mu)
    bt["unit_cost"] = cost[bt.k.values]
    bt["value_at_risk"] = bt.exp_unsold_units * bt.unit_cost
    return bt


def calibration(snapshots, sim_writeoffs, predict_fn, alpha, cost, bins=(0, .1, .3, .5, .7, .9, 1.0001)):
    """Did the scores come true? Compare predicted risk at past snapshots with what actually expired."""
    wo = pd.DataFrame(sim_writeoffs, columns=["t", "s", "k", "bid", "units", "cost"]).groupby("bid").units.sum()
    parts = []
    for o, bt in snapshots.items():
        sc = score_batches(bt, predict_fn(o), o, alpha, cost); sc = sc[sc.scored].copy()
        sc["snapshot"] = o; parts.append(sc)
    d = pd.concat(parts, ignore_index=True)
    d["actual_unsold"] = d.bid.map(wo).fillna(0).clip(upper=d.qty)       # units of this batch actually written off
    d["actual_any"] = (d.actual_unsold > 0).astype(int)
    d["bin"] = pd.cut(d.p_unsold, list(bins), right=False)
    tab = d.groupby("bin", observed=True).agg(batches=("bid", "size"), predicted=("p_unsold", "mean"), actual=("actual_any", "mean"),
                                            exp_units=("exp_unsold_units", "sum"), actual_units=("actual_unsold", "sum")).reset_index()
    from sklearn.metrics import roc_auc_score
    auc = roc_auc_score(d.actual_any, d.p_unsold) if d.actual_any.nunique() > 1 else np.nan
    return d, tab, dict(auc=float(auc), exp_units=float(d.exp_unsold_units.sum()), actual_units=float(d.actual_unsold.sum()),
                        exp_value=float(d.value_at_risk.sum()), actual_value=float((d.actual_unsold*d.unit_cost).sum()), n_batches=len(d))
