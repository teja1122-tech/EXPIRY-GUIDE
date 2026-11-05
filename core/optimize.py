"""Action recommender: TRANSFER / RETURN / MARKDOWN_REVIEW as a small mixed-integer programme (HiGHS). Parameter-driven."""
import numpy as np, pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import coo_matrix
from .config import HORIZON, Params
from .risk import cdf


def receiver_capacity(bt_all, fc, o, alpha, j, k, e_min, cap_max, p):
    d = int(e_min - o)
    if d < 2 or d > HORIZON or cap_max <= 0: return 0
    mine = bt_all[(bt_all.s == j) & (bt_all.k == k)]; mu = float(fc[j, k, :d].sum())
    c_le = int(mine.loc[mine.exp <= e_min, "qty"].sum()); m = np.arange(1, cap_max+1)
    m_star = int(np.cumprod((1 - cdf(c_le + m - 1, mu, alpha)) >= p.theta_dst).sum())
    if m_star == 0: return 0
    later = mine[(mine.exp > e_min) & (mine.exp - o <= HORIZON)]
    if len(later):
        mm = np.arange(1, m_star+1); good = np.ones(m_star, bool)
        for r in later.itertuples(index=False):
            mu_b = float(fc[j, k, :int(r.exp - o)].sum()); C = int(r.C)
            good &= (1 - cdf(C + mm - 1, mu_b, alpha)) >= min(p.keep_later, float(1 - cdf(C - 1, mu_b, alpha))) - 1e-9
        m_star = int(np.cumprod(good).sum())
    return m_star


def plan_actions(sc, fc, o, alpha, dist, cost, store_names, sku_names, p: Params = Params()):
    EMPTY = pd.DataFrame(); n_st = fc.shape[0]
    if dist is None:
        dist = np.full((n_st, n_st), p.default_distance_km); np.fill_diagonal(dist, 0.0)
    src = sc[(sc.at_risk_units > 0) & (sc.days_left >= 2)].copy()
    blocked_r = {i for i, n in enumerate(store_names) if n in set(p.blocked_receivers)}; blocked_s = set(p.blocked_senders)
    if src.empty: return EMPTY, dict(status="no at-risk units", n_sources=0)
    src["transfer_ok"] = (src.days_left >= p.transfer_min_days) & p.allow_transfers & ~src.s.map(lambda i: store_names[i] in blocked_s)
    src["return_ok"] = (src.days_left >= p.return_min_days) & p.allow_returns
    src = src.reset_index(drop=True); xs, caps = [], {}
    for k, g in src[src.transfer_ok].groupby("k"):
        e_min = int(g.exp.min()); tot = int(g.at_risk_units.sum())
        for j in range(n_st):
            if (g.s == j).all() or j in blocked_r: continue
            caps[(j, k)] = receiver_capacity(sc, fc, o, alpha, j, k, e_min, tot, p)
    gx_of = lambda k: cost[k]*(p.theta_dst - p.theta_src) - p.unit_handling
    gz_of = lambda k: cost[k]*(p.return_credit - p.theta_src) - p.return_handling
    for b in src[src.transfer_ok].itertuples():
        if gx_of(b.k) <= 0: continue
        for j in range(n_st):
            cap = caps.get((j, b.k), 0)
            if p.max_transfer_km > 0 and dist[b.s, j] > p.max_transfer_km: continue
            if j != b.s and cap > 0: xs.append((b.Index, j, min(b.at_risk_units, cap), gx_of(b.k)))
    zs = [(b.Index, b.at_risk_units, gz_of(b.k)) for b in src[src.return_ok].itertuples() if gz_of(b.k) > 0]
    lanes = sorted({(int(src.s[bi]), j) for bi, j, _, _ in xs}); lane_ix = {l: i for i, l in enumerate(lanes)}
    nx, nz, ny = len(xs), len(zs), len(lanes); nv = nx + nz + ny; x = np.zeros(nv, int); status = "no cost-effective moves"
    if nx + nz > 0:
        cvec = np.zeros(nv); ub = np.zeros(nv)
        for i, (bi, j, cap, gx) in enumerate(xs): cvec[i] = -gx; ub[i] = cap
        for i, (bi, u, gz) in enumerate(zs): cvec[nx+i] = -gz; ub[nx+i] = u
        for i, (a, j) in enumerate(lanes): cvec[nx+nz+i] = p.lane_fixed + p.lane_per_km*dist[a, j]; ub[nx+nz+i] = 1
        rows, cols, vals, rhs = [], [], [], []; r = 0
        by_b = {}
        for i, x_ in enumerate(xs): by_b.setdefault(x_[0], []).append(i)
        for i, z_ in enumerate(zs): by_b.setdefault(z_[0], []).append(nx+i)
        for bi, idx in by_b.items():
            for c_ in idx: rows.append(r); cols.append(c_); vals.append(1)
            rhs.append(int(src.at_risk_units[bi])); r += 1
        by_jk = {}
        for i, (bi, j, cap, gx) in enumerate(xs): by_jk.setdefault((j, int(src.k[bi])), []).append(i)
        for (j, k), idx in by_jk.items():
            for c_ in idx: rows.append(r); cols.append(c_); vals.append(1)
            rhs.append(caps[(j, k)]); r += 1
        for i, (bi, j, cap, gx) in enumerate(xs):
            rows += [r, r]; cols += [i, nx+nz+lane_ix[(int(src.s[bi]), j)]]; vals += [1, -float(src.at_risk_units[bi])]; rhs.append(0); r += 1
        A = coo_matrix((vals, (rows, cols)), shape=(r, nv)).tocsr()
        res = milp(cvec, constraints=LinearConstraint(A, -np.inf, np.array(rhs)), integrality=np.ones(nv),
                   bounds=Bounds(np.zeros(nv), ub), options=dict(time_limit=30, mip_rel_gap=1e-3))
        if res.x is not None: x = np.round(res.x).astype(int); status = "optimal" if res.status == 0 else str(res.message)
    lane_units = {}
    for i, (bi, j, cap, gx) in enumerate(xs):
        if x[i] > 0: lane_units[(int(src.s[bi]), j)] = lane_units.get((int(src.s[bi]), j), 0) + int(x[i])
    out, moved, returned = [], {}, {}
    for i, (bi, j, cap, gx) in enumerate(xs):
        if x[i] <= 0: continue
        b = src.loc[bi]; a = int(b.s); moved[bi] = moved.get(bi, 0) + int(x[i]); c = float(cost[int(b.k)])
        lane = p.lane_fixed + p.lane_per_km*dist[a, j]; mc = x[i]*p.unit_handling + lane*x[i]/lane_units[(a, j)]
        out.append(dict(action="TRANSFER", s=a, to_s=j, k=int(b.k), bid=int(b.bid), batch_id=b.batch_id, units=int(x[i]), exp=int(b.exp),
                        days_left=int(b.days_left), unit_cost=c, move_cost=float(mc), est_gain=float(x[i]*c*(p.theta_dst-p.theta_src) - mc),
                        credit=0.0, p_unsold=float(b.p_unsold), distance_km=float(dist[a, j])))
    for i, (bi, u, gz) in enumerate(zs):
        n = int(x[nx+i])
        if n <= 0: continue
        b = src.loc[bi]; returned[bi] = n; c = float(cost[int(b.k)])
        out.append(dict(action="RETURN", s=int(b.s), to_s=-1, k=int(b.k), bid=int(b.bid), batch_id=b.batch_id, units=n, exp=int(b.exp),
                        days_left=int(b.days_left), unit_cost=c, move_cost=n*p.return_handling, est_gain=float(n*gz), credit=float(n*p.return_credit*c),
                        p_unsold=float(b.p_unsold), distance_km=0.0))
    for bi in src.index:
        left = int(src.at_risk_units[bi]) - moved.get(bi, 0) - returned.get(bi, 0)
        if left > 0:
            b = src.loc[bi]
            out.append(dict(action="MARKDOWN_REVIEW", s=int(b.s), to_s=-1, k=int(b.k), bid=int(b.bid), batch_id=b.batch_id, units=left, exp=int(b.exp),
                            days_left=int(b.days_left), unit_cost=float(cost[int(b.k)]), move_cost=0.0, est_gain=0.0, credit=0.0,
                            p_unsold=float(b.p_unsold), distance_km=0.0))
    act = pd.DataFrame(out)
    if len(act):
        act["store_from"] = [store_names[i] for i in act.s]; act["store_to"] = [store_names[i] if i >= 0 else "" for i in act.to_s]
        act["sku"] = [sku_names[i] for i in act.k]
    return act, dict(status=status, n_sources=len(src), n_lanes=int(sum(x[nx+nz:] > 0)) if nx+nz > 0 else 0)
