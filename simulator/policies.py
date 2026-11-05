"""Replenishment behaviour. Baseline = how a typical chain orders today (weekly review, order-up-to, pack-rounded)."""
import numpy as np
from config import *
from world import N, K


def review_orders(sim, o, fc=None, fc_origin=None):
    """Weekly (R,S)-style ordering, staggered by store. If a forecast is given, apply the expiry-aware order cap."""
    onhand, onord = sim.onhand(), sim.onorder()
    for s in range(N):
        if (o + s) % REVIEW != 0: continue
        r28 = sim.S[max(0, o-28):o, s, :].mean(0); r90 = sim.S[max(0, o-90):o, s, :].mean(0)
        rate = np.maximum(r28, 0.7*r90)
        pos = onhand[s] + onord[s]
        S_up = np.maximum(np.ceil(rate*(LEAD+REVIEW+SAFETY_DAYS)), MIN_DISPLAY)
        rop = np.maximum(np.ceil(rate*(LEAD+REVIEW+3)), MIN_DISPLAY)
        q = np.ceil(np.maximum(S_up-pos, 0)/sim.pack)*sim.pack
        q = np.where(pos <= rop, q, 0)
        if fc is not None:                                    # ---- expiry-aware cap ("stop over-ordering")
            off = o - fc_origin
            f90 = fc[s, :, off:off+90].sum(1)                 # forecast demand over next 90 days
            cap_pos = np.maximum(MIN_DISPLAY, np.ceil(f90))
            q_cap = np.floor(np.maximum(cap_pos-pos, 0)/sim.pack)*sim.pack
            q_cap = np.where(pos < rate*(LEAD+REVIEW), np.maximum(q_cap, sim.pack), q_cap)   # never allow imminent stock-out
            new_q = np.minimum(q, q_cap)
            q = new_q
        for k in np.nonzero(q > 0)[0]:
            sim.place_order(o, s, int(k), int(q[k]))


class Baseline:
    name = "baseline"
    def decide(self, sim, o):
        review_orders(sim, o)


class System:
    """Baseline ordering + weekly forecast -> risk score -> optimise actions -> execute, + expiry-aware order cap."""
    name = "system"
    def __init__(self, model, cat_of_sku, alpha, world, use_actions=True, use_cap=True):
        self.model, self.cat, self.alpha, self.w = model, cat_of_sku, alpha, world
        self.use_actions, self.use_cap = use_actions, use_cap
        self.fc = None; self.fc_origin = None; self.actions, self.risk_log, self.info_log = [], [], []
        self.store_names = world["stores"].store.tolist(); self.sku_names = world["skus"].sku.tolist()

    def decide(self, sim, o):
        from forecast import predict
        from risk import score_batches
        from optimize import plan_actions
        if self.fc is None or (o - self.fc_origin) >= 7:
            self.fc, self.fc_origin = predict(self.model, sim.S, self.cat, o), o
            sc = score_batches(sim.batch_table(), self.fc, o, self.alpha, sim.cost)
            self.risk_log.append(dict(origin=o, value_at_risk=float(sc.value_at_risk.sum()), units_at_risk=float(sc.exp_unsold_units.sum())))
            act, info = plan_actions(sc, self.fc, o, self.alpha, self.w["dist"], sim.cost, self.store_names, self.sku_names)
            self.info_log.append(dict(origin=o, **info))
            if len(act):
                self.actions.append(act)
                if self.use_actions: self._execute(sim, o, act)
        review_orders(sim, o, self.fc if self.use_cap else None, self.fc_origin)

    def _execute(self, sim, o, act):
        for r in act.itertuples(index=False):
            if r.action == "MARKDOWN_REVIEW": continue
            lst = sim.inv[r.from_store][r.k]; b = next(x for x in lst if x[2] == r.bid)
            assert b[1] >= r.units, "plan asked for more units than the batch holds"
            b[1] -= r.units
            if b[1] == 0: lst.remove(b)
            if r.action == "TRANSFER":
                nb = sim.next_bid; sim.next_bid += 1
                sim.arrivals[o+1].append((r.to_store, r.k, r.units, r.exp, nb))
                sim.transfers.append((o, r.from_store, r.to_store, r.k, r.bid, r.units, r.exp, r.est_gain, r.move_cost))
            else:
                sim.returns.append((o, r.from_store, r.k, r.bid, r.units, r.credit))
