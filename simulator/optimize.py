"""Step 4 - action recommender: decide TRANSFER / RETURN / MARKDOWN_REVIEW for at-risk units.

Per at-risk unit we use conservative *lower-bound* values (avoided re-purchase cost c):
  transfer gain/unit = c*(THETA_DST - THETA_SRC) - handling      (sells at receiver >=70% vs <=30% at source)
  return   gain/unit = c*(RETURN_CREDIT - THETA_SRC) - handling  (60% credit vs <=30% chance of selling)
Shipping has a fixed cost per store-to-store lane, so it is a small mixed-integer program (HiGHS via scipy).
Receivers may only take what they are likely to sell (capacity from the same probabilistic model) and may not
have their own later batches pushed into high expiry risk.
"""
import numpy as np, pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import coo_matrix
from config import *
from risk import cdf


def receiver_capacity(bt_all, fc, o, alpha, j, k, e_min, cap_max):
    d = int(e_min - o)
    if d < 2 or d > HORIZON or cap_max <= 0: return 0
    mine = bt_all[(bt_all.s == j) & (bt_all.k == k)]
    mu = float(fc[j, k, :d].sum())
    c_le = int(mine.loc[mine.exp <= e_min, "qty"].sum())
    m = np.arange(1, cap_max + 1)
    ok = (1 - cdf(c_le + m - 1, mu, alpha)) >= THETA_DST           # P(m-th extra unit sells) >= 70%
    m_star = int(np.cumprod(ok).sum())
    if m_star == 0: return 0
    later = mine[(mine.exp > e_min) & (mine.exp - o <= HORIZON)]    # protect the receiver's own later batches
    if len(later):
        mm = np.arange(1, m_star + 1); good = np.ones(m_star, bool)
        for r in later.itertuples(index=False):
            mu_b = float(fc[j, k, :int(r.exp - o)].sum()); C = int(r.C)
            cur = 1 - cdf(C - 1, mu_b, alpha); aft = 1 - cdf(C + mm - 1, mu_b, alpha)
            good &= aft >= min(KEEP_LATER, float(cur)) - 1e-9
        m_star = int(np.cumprod(good).sum())
    return m_star


def plan_actions(sc, fc, o, alpha, dist, cost, store_names, sku_names):
    """sc: scored batch table from risk.score_batches. Returns (actions DataFrame, info dict)."""
    src = sc[(sc.at_risk_units > 0) & (sc.days_left >= 2)].copy()
    if src.empty: return pd.DataFrame(), dict(solver="none", n_sources=0)
    src["transfer_ok"] = src.days_left >= TRANSFER_MIN_DAYS
    src["return_ok"] = src.days_left >= RETURN_MIN_DAYS
    src = src.reset_index(drop=True)
    xs, caps = [], {}                                              # candidate transfer variables
    for k, g in src[src.transfer_ok].groupby("k"):
        e_min = int(g.exp.min()); tot = int(g.at_risk_units.sum())
        for j in range(fc.shape[0]):
            if (g.s == j).all(): continue                          # receiver cannot be the only source store
            caps[(j, k)] = receiver_capacity(sc, fc, o, alpha, j, k, e_min, tot)
    for b in src[src.transfer_ok].itertuples():
        c = cost[b.k]; gx = c*(THETA_DST-THETA_SRC) - UNIT_HANDLING
        if gx <= 0: continue
        for j in range(fc.shape[0]):
            cap = caps.get((j, b.k), 0)
            if j != b.s and cap > 0: xs.append((b.Index, j, min(b.at_risk_units, cap), gx))
    zs = [(b.Index, b.at_risk_units, cost[b.k]*(RETURN_CREDIT-THETA_SRC)-RETURN_HANDLING)
          for b in src[src.return_ok].itertuples() if cost[b.k]*(RETURN_CREDIT-THETA_SRC)-RETURN_HANDLING > 0]
    lanes = sorted({(int(src.s[bi]), j) for bi, j, _, _ in xs}); lane_ix = {l: i for i, l in enumerate(lanes)}
    nx, nz, ny = len(xs), len(zs), len(lanes); nv = nx + nz + ny
    if nx + nz == 0: return pd.DataFrame(), dict(solver="none", n_sources=len(src))
    cvec = np.zeros(nv); lb = np.zeros(nv); ub = np.zeros(nv)
    for i, (bi, j, cap, gx) in enumerate(xs): cvec[i] = -gx; ub[i] = cap
    for i, (bi, u, gz) in enumerate(zs): cvec[nx+i] = -gz; ub[nx+i] = u
    for i, (a, j) in enumerate(lanes): cvec[nx+nz+i] = LANE_FIXED + LANE_PER_KM*dist[a, j]; ub[nx+nz+i] = 1
    rows, cols, vals, rhs = [], [], [], []; r = 0
    for bi in src.index:                                           # (1) never move/return more than the at-risk units of a batch
        idx = [(i, 1) for i, x in enumerate(xs) if x[0] == bi] + [(nx+i, 1) for i, z in enumerate(zs) if z[0] == bi]
        if not idx: continue
        for c_, v_ in idx: rows.append(r); cols.append(c_); vals.append(v_)
        rhs.append(src.at_risk_units[bi]); r += 1
    by_jk = {}
    for i, (bi, j, cap, gx) in enumerate(xs): by_jk.setdefault((j, int(src.k[bi])), []).append(i)
    for (j, k), idx in by_jk.items():                              # (2) receiver capacity per SKU
        for c_ in idx: rows.append(r); cols.append(c_); vals.append(1)
        rhs.append(caps[(j, k)]); r += 1
    for i, (bi, j, cap, gx) in enumerate(xs):                      # (3) pay the lane fixed cost if anything moves on it
        rows += [r, r]; cols += [i, nx+nz+lane_ix[(int(src.s[bi]), j)]]; vals += [1, -float(src.at_risk_units[bi])]; rhs.append(0); r += 1
    A = coo_matrix((vals, (rows, cols)), shape=(r, nv)).tocsr()
    integ = np.ones(nv)
    res = milp(cvec, constraints=LinearConstraint(A, -np.inf, np.array(rhs)), integrality=integ, bounds=Bounds(lb, ub),
               options=dict(time_limit=30, mip_rel_gap=1e-3))
    x = np.round(res.x).astype(int) if res.x is not None else np.zeros(nv, int)
    lane_used = {l: x[nx+nz+i] > 0 for l, i in lane_ix.items()}
    lane_units = {}
    for i, (bi, j, cap, gx) in enumerate(xs):
        if x[i] > 0: lane_units[(int(src.s[bi]), j)] = lane_units.get((int(src.s[bi]), j), 0) + x[i]
    out = []
    for i, (bi, j, cap, gx) in enumerate(xs):
        if x[i] <= 0: continue
        b = src.loc[bi]; a = int(b.s); lane_cost = LANE_FIXED + LANE_PER_KM*dist[a, j]
        move_cost = x[i]*UNIT_HANDLING + lane_cost*x[i]/lane_units[(a, j)]
        out.append(dict(origin=o, action="TRANSFER", from_store=a, to_store=j, k=int(b.k), bid=int(b.bid), units=int(x[i]),
                        exp=int(b.exp), days_left=int(b.days_left), unit_cost=cost[int(b.k)], move_cost=move_cost,
                        est_gain=(x[i]*cost[int(b.k)]*(THETA_DST-THETA_SRC)) - move_cost, credit=0.0, p_unsold=b.p_unsold))
    used_return = {}
    for i, (bi, u, gz) in enumerate(zs):
        if x[nx+i] <= 0: continue
        b = src.loc[bi]; n = int(x[nx+i]); used_return[bi] = n
        out.append(dict(origin=o, action="RETURN", from_store=int(b.s), to_store=-1, k=int(b.k), bid=int(b.bid), units=n,
                        exp=int(b.exp), days_left=int(b.days_left), unit_cost=cost[int(b.k)], move_cost=n*RETURN_HANDLING,
                        est_gain=n*gz + 0.0, credit=n*RETURN_CREDIT*cost[int(b.k)], p_unsold=b.p_unsold))
    moved = {}
    for i, (bi, j, cap, gx) in enumerate(xs): moved[bi] = moved.get(bi, 0) + int(x[i])
    for bi in src.index:
        left = int(src.at_risk_units[bi]) - moved.get(bi, 0) - used_return.get(bi, 0)
        if left > 0:
            b = src.loc[bi]
            out.append(dict(origin=o, action="MARKDOWN_REVIEW", from_store=int(b.s), to_store=-1, k=int(b.k), bid=int(b.bid), units=left,
                            exp=int(b.exp), days_left=int(b.days_left), unit_cost=cost[int(b.k)], move_cost=0.0,
                            est_gain=0.0, credit=0.0, p_unsold=b.p_unsold))
    act = pd.DataFrame(out)
    if len(act):
        act["store_from"] = [store_names[i] for i in act.from_store]
        act["store_to"] = [store_names[i] if i >= 0 else "" for i in act.to_store]
        act["sku"] = [sku_names[i] for i in act.k]
    return act, dict(solver=res.message, n_sources=len(src), n_lanes=int(sum(lane_used.values())), objective=float(-res.fun) if res.fun is not None else 0.0)
