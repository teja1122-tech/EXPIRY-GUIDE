"""Step 1a - build the synthetic chain: stores, SKUs, demand, and a FEFO inventory simulator."""
import copy
from collections import defaultdict
import numpy as np, pandas as pd
from config import *

K = N_SKUS; N = N_STORES


def make_world(seed):
    rng = np.random.default_rng(seed)
    stores = pd.DataFrame({
        "store_id": range(N), "store": [f"Store-{i+1:02d}" for i in range(N)],
        "lat": 17.385 + rng.uniform(-0.18, 0.18, N), "lon": 78.487 + rng.uniform(-0.18, 0.18, N),
        "scale": rng.lognormal(0, 0.35, N)})
    cat = np.repeat(np.arange(len(CATS)), K // len(CATS))
    cost = np.clip(rng.lognormal(np.log(40), 0.8, K), 3, 600).round(2)
    skus = pd.DataFrame({
        "sku_id": range(K), "sku": [f"SKU-{i+1:03d}" for i in range(K)],
        "category": [CATS[c] for c in cat], "cat_id": cat,
        "base_rate": np.clip(rng.lognormal(np.log(0.6), 1.2, K), 0.02, 10),
        "unit_cost": cost, "unit_price": (cost * rng.uniform(1.2, 1.4, K)).round(2),
        "shelf_life": rng.choice([180, 270, 365, 545], K), "pack": rng.choice([10, 15, 20, 30], K)})
    lat, lon = np.radians(stores.lat.values), np.radians(stores.lon.values)
    a = np.sin((lat[:, None]-lat[None])/2)**2 + np.cos(lat[:, None])*np.cos(lat[None])*np.sin((lon[:, None]-lon[None])/2)**2
    dist = 6371 * 2 * np.arcsin(np.sqrt(a))
    aff = rng.lognormal(0, 0.4, (N, len(CATS)))             # store x category affinity (nearby clinics etc.)
    return dict(seed=seed, stores=stores, skus=skus, dist=dist, aff=aff)


def simulate_demand(w, seed):
    """True (unobserved) daily demand: base x store x affinity x seasonality x weekday x slow drift, NB noise."""
    rng = np.random.default_rng(seed + 1)
    sk = w["skus"]; st = w["stores"]
    dates = pd.Timestamp(START_DATE) + pd.to_timedelta(np.arange(T_END), "D")
    doy, dow = dates.dayofyear.values, dates.dayofweek.values
    amp = np.array([SEAS[c][0] for c in sk.category]); pk = np.array([SEAS[c][1] for c in sk.category])
    seas = 1 + amp[None] * np.cos(2*np.pi*(doy[:, None]-pk[None])/365)           # (T,K)
    nm = T_END // 30 + 2
    logm = np.zeros((nm, N, K)); shock = np.zeros((nm, N, K))
    for m in range(1, nm):                                     # mean-reverting monthly drift
        logm[m] = 0.9*logm[m-1] + rng.normal(0, 0.15, (N, K))
        shock[m] = np.where(rng.random((N, K)) < 0.01, np.log(0.3), 0.0)   # rare regime shock (e.g. nearby doctor leaves)
    eff = logm.copy()
    for m in range(nm):                                        # a shock lasts 3 months, applied on top (no compounding)
        for j in range(3):
            if m-j >= 0: eff[m] += shock[m-j]
    logm = eff
    pair = (sk.base_rate.values[None]*st.scale.values[:, None]*w["aff"][:, sk.cat_id.values])   # (N,K)
    mult = np.exp(logm[np.arange(T_END)//30])                                       # (T,N,K)
    lam = pair[None]*seas[:, None, :]*DOW_FACTOR[dow][:, None, None]*mult
    D = rng.negative_binomial(NB_R, NB_R/(NB_R+lam)).astype(np.int32)
    life_u = rng.uniform(0.25, 0.65, (T_END, N, K)).astype(np.float32)   # remaining-life draw per (day,store,sku)
    return D, lam.astype(np.float32), life_u


class Sim:
    """FEFO inventory simulator. Batches: [expiry_day, qty, batch_id]. Sales are observed, demand is not."""
    def __init__(self, w, D, life_u, snap_origins=()):
        self.w, self.D, self.life_u = w, D, life_u
        sk = w["skus"]
        self.cost, self.price = sk.unit_cost.values, sk.unit_price.values
        self.pack, self.shelf = sk.pack.values, sk.shelf_life.values
        T = D.shape[0]
        self.S = np.zeros((T, N, K), np.int32); self.LOST = np.zeros((T, N, K), np.int32)
        self.inv = [[[] for _ in range(K)] for _ in range(N)]
        self.arrivals = defaultdict(list)        # day -> [(s,k,qty,exp,bid)]
        self.next_bid = 0
        self.purchases, self.writeoffs, self.transfers, self.returns = [], [], [], []
        self.snap_origins, self.snapshots = set(snap_origins), {}
        rng = np.random.default_rng(w["seed"] + 7)
        for s in range(N):                       # opening stock: ~25 days of cover, mixed expiry
            for k in range(K):
                rate = float(D[:60, s, k].mean())
                q = max(MIN_DISPLAY, int(np.ceil(rate*25/self.pack[k]))*self.pack[k])
                self._add(s, k, q, int(rng.integers(120, 400)))

    def _add(self, s, k, q, exp, bid=None):
        if bid is None:
            bid = self.next_bid; self.next_bid += 1
        lst = self.inv[s][k]; lst.append([exp, q, bid]); lst.sort(key=lambda b: b[0])
        return bid

    def onhand(self):
        return np.array([[sum(b[1] for b in self.inv[s][k]) for k in range(K)] for s in range(N)])

    def onorder(self):
        oo = np.zeros((N, K))
        for lst in self.arrivals.values():
            for (s, k, q, e, b) in lst: oo[s, k] += q
        return oo

    def batch_table(self):
        rows = [(s, k, b[2], b[0], b[1]) for s in range(N) for k in range(K) for b in self.inv[s][k]]
        return pd.DataFrame(rows, columns=["s", "k", "bid", "exp", "qty"]).sort_values(["s", "k", "exp"]).reset_index(drop=True)

    def place_order(self, t_order, s, k, q):
        arr = t_order + LEAD                               # placed at start of origin day, arrives LEAD days later
        life = int(self.shelf[k]*self.life_u[min(t_order, self.D.shape[0]-1), s, k])
        exp = arr + life
        bid = self.next_bid; self.next_bid += 1
        self.arrivals[arr].append((s, k, q, exp, bid))
        self.purchases.append((t_order, s, k, bid, q, exp, q*self.cost[k]))

    def day_ops(self, t):
        for (s, k, q, e, bid) in self.arrivals.pop(t, []):
            self._add(s, k, q, e, bid)
        for s in range(N):
            for k in range(K):
                lst = self.inv[s][k]
                while lst and lst[0][0] <= t:                          # expired -> write-off
                    e, q, bid = lst.pop(0)
                    self.writeoffs.append((t, s, k, bid, q, q*self.cost[k]))
                d = int(self.D[t, s, k])
                if d == 0: continue
                rem = d
                while rem > 0 and lst:
                    b = lst[0]; take = min(rem, b[1]); b[1] -= take; rem -= take
                    if b[1] == 0: lst.pop(0)
                self.S[t, s, k] = d - rem; self.LOST[t, s, k] = rem

    def run(self, policy, t0, t1, decide_at_start=False, stop_before_decide=None):
        """Loop days; the policy decides at each origin o=t+1 (end of day t)."""
        if decide_at_start: self._decide(policy, t0)
        for t in range(t0, t1):
            self.day_ops(t)
            o = t + 1
            if o < t1 and o != stop_before_decide: self._decide(policy, o)

    def _decide(self, policy, o):
        if o in self.snap_origins: self.snapshots[o] = self.batch_table()
        policy.decide(self, o)


def kpis(sim, t0, t1):
    sold = sim.S[t0:t1].sum((0, 1)); lost = sim.LOST[t0:t1].sum((0, 1))
    revenue = float((sold*sim.price).sum()); cogs = float((sold*sim.cost).sum())
    wo = [r for r in sim.writeoffs if t0 <= r[0] < t1]
    wo_cost = sum(r[5] for r in wo); wo_units = sum(r[4] for r in wo)
    ret = [r for r in sim.returns if t0 <= r[0] < t1]
    ret_cost = sum(r[4]*sim.cost[r[2]] for r in ret); ret_credit = sum(r[5] for r in ret)
    tr_cost = sum(r[8] for r in sim.transfers if t0 <= r[0] < t1)
    purchases = sum(r[6] for r in sim.purchases if t0 <= r[0] < t1)
    closing = sum(b[1]*sim.cost[k] for s in range(N) for k in range(K) for b in sim.inv[s][k])
    demand_units = sold.sum() + lost.sum()
    return dict(revenue=revenue, cogs=cogs, writeoff_cost=wo_cost, writeoff_units=int(wo_units),
                transfer_cost=tr_cost, return_loss=ret_cost-ret_credit, return_credit=ret_credit,
                purchases=purchases, closing_stock_cost=closing,
                lost_units=int(lost.sum()), fill_rate=float(sold.sum()/demand_units),
                net_contribution=revenue - cogs - wo_cost - tr_cost - (ret_cost - ret_credit))
