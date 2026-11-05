"""Two stages: forecast_stage (slow, depends only on data) and plan_stage (fast, depends on planning parameters)."""
import numpy as np, pandas as pd
from .config import Params, HORIZON
from .forecast import make_forecast
from .risk import score_batches
from .optimize import plan_actions


def forecast_stage(ds, progress=None):
    return make_forecast(ds, progress)


def plan_stage(ds, fi, params: Params):
    fc, alpha, T = fi["fc"], fi["alpha"], ds.T
    sc = score_batches(ds.batches, fc, T, alpha, ds.cost, params.theta_src)
    sc["store"] = ds.stores.store.values[sc.s]; sc["sku"] = ds.skus.sku.values[sc.k]; sc["category"] = ds.skus.category.values[sc.k]
    sc["unit_price"] = ds.price[sc.k]; sc["stock_value"] = sc.qty*sc.unit_cost
    sc["risk_band"] = np.select([~sc.scored, sc.p_unsold >= 0.7, sc.p_unsold >= 0.3], ["Not scored (>120d)", "High", "Medium"], "Low")
    act, info = plan_actions(sc, fc, T, alpha, ds.dist, ds.cost, ds.stores.store.tolist(), ds.skus.sku.tolist(), params)
    if len(act):
        act["expiry_date"] = (ds.start + pd.to_timedelta(act.exp, "D")).dt.date
        act["category"] = ds.skus.category.values[act.k]; act["approve"] = act.action.isin(["TRANSFER", "RETURN"])
        act["id"] = np.arange(1, len(act)+1)
    exp = ds.expired
    kp = dict(stock_value=float(sc.stock_value.sum()), n_batches=int(len(sc)), value_at_risk=float(sc.value_at_risk.sum()),
              units_at_risk=float(sc.exp_unsold_units.sum()), high_risk_batches=int((sc.p_unsold >= 0.7).sum()),
              exp30_value=float(sc.loc[sc.days_left <= 30, "stock_value"].sum()),
              expired_value=float((exp.qty*ds.cost[exp.k.values]).sum()) if len(exp) else 0.0, expired_batches=int(len(exp)))
    if len(act):
        for a, nm in (("TRANSFER", "transfer"), ("RETURN", "return"), ("MARKDOWN_REVIEW", "markdown")):
            g = act[act.action == a]; kp[f"{nm}_units"] = int(g.units.sum()); kp[f"{nm}_value"] = float((g.units*g.unit_cost).sum())
        kp["est_net_gain"] = float(act.est_gain.sum()); kp["credit"] = float(act.credit.sum()); kp["move_cost"] = float(act.move_cost.sum())
    else:
        for nm in ("transfer", "return", "markdown"): kp[f"{nm}_units"] = 0; kp[f"{nm}_value"] = 0.0
        kp["est_net_gain"] = kp["credit"] = kp["move_cost"] = 0.0
    return dict(sc=sc, actions=act, info=info, kpis=kp, params=params, fingerprint=ds.fingerprint)
