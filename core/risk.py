"""Expiry-risk scoring (FEFO + negative-binomial demand). See README for the derivation."""
import numpy as np, pandas as pd
from scipy.stats import nbinom
from .config import HORIZON


def cdf(k, mu, alpha):
    k = np.asarray(k); r = 1.0/alpha; p = r/(r + max(float(mu), 1e-9))
    return np.where(k < 0, 0.0, nbinom.cdf(np.maximum(k, 0), r, p))


def score_batches(bt, fc, o, alpha, cost, theta_src=0.30, horizon=HORIZON):
    bt = bt.sort_values(["s", "k", "exp", "bid"]).reset_index(drop=True).copy()
    bt["days_left"] = bt.exp - o
    bt["C"] = bt.groupby(["s", "k"]).qty.cumsum(); bt["C_prev"] = bt.C - bt.qty
    n = len(bt); mu = np.full(n, np.nan); p_un = np.full(n, np.nan); e_un = np.full(n, np.nan); risky = np.zeros(n, int)
    for i, r in enumerate(bt.itertuples(index=False)):
        d = int(r.days_left)
        if d > horizon or d < 1: continue
        m = float(fc[r.s, r.k, :d].sum()); mu[i] = m
        p_un[i] = float(cdf(r.C - 1, m, alpha)); e_un[i] = float(cdf(r.C - np.arange(1, r.qty+1), m, alpha).sum())
        pos = np.arange(r.C_prev + 1, r.C + 1); risky[i] = int((cdf(pos - 1, m, alpha) >= 1 - theta_src).sum())
    bt["mu"], bt["p_unsold"], bt["exp_unsold_units"], bt["at_risk_units"] = mu, p_un, e_un, risky
    bt["scored"] = ~np.isnan(mu); bt["unit_cost"] = cost[bt.k.values]; bt["value_at_risk"] = bt.exp_unsold_units * bt.unit_cost
    return bt


def demand_distribution(mu, alpha, upto=None):
    """x grid and pmf of demand until expiry (for the batch deep-dive chart)."""
    r = 1.0/alpha; p = r/(r + max(mu, 1e-9)); hi = int(upto or nbinom.ppf(0.995, r, p) + 5)
    x = np.arange(0, max(hi, 10)); return x, nbinom.pmf(x, r, p)


def expected_unsold(C, q, mu, alpha):
    return float(cdf(C - np.arange(1, q+1), mu, alpha).sum())


def markdown_curve(C_prev, q, mu, alpha, price, elasticity, discounts):
    """Expected cash from selling this batch at a discount. Demand uplift = 1 + elasticity*discount (user assumption)."""
    rows = []
    for d in discounts:
        mu2 = mu*(1 + elasticity*d); sold = q - expected_unsold(C_prev + q, q, mu2, alpha)
        rows.append(dict(discount=d, expected_units_sold=sold, expected_revenue=sold*price*(1-d), sell_through=sold/max(q, 1)))
    return pd.DataFrame(rows)
