"""Geography + manual-transfer analytics: location overrides, nearby stores, store scorecards, per-destination transfer options."""
import time
import numpy as np, pandas as pd
from .db import conn
from .auth import audit
from .config import HORIZON, Params
from .io import recompute_geo
from .risk import cdf
from .optimize import receiver_capacity


def get_overrides():
    with conn() as c: return {r["store"]: (r["lat"], r["lon"]) for r in c.execute("SELECT store,lat,lon FROM geo_overrides")}


def save_locations(df, user):
    """df: store, lat, lon. Validates ranges; persists so locations survive new uploads."""
    bad = df[(df.lat.abs() > 90) | (df.lon.abs() > 180) | df.lat.isna() | df.lon.isna()]
    if len(bad): raise ValueError(f"Invalid coordinates for: {', '.join(bad.store.astype(str))}. Latitude must be -90..90 and longitude -180..180.")
    with conn() as c:
        for r in df.itertuples():
            c.execute("INSERT INTO geo_overrides(store,lat,lon,updated_by,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(store) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                      (r.store, float(r.lat), float(r.lon), user["username"], time.strftime("%Y-%m-%d %H:%M:%S")))
    audit(user["username"], "locations_saved", f"{len(df)} store(s)")


def apply_overrides(ds):
    ov = get_overrides()
    if ov:
        for i, s in enumerate(ds.stores.store):
            if s in ov: ds.stores.loc[i, ["lat", "lon"]] = ov[s]
    return recompute_geo(ds)


def dist_matrix(ds, p: Params):
    if ds.dist is not None: return ds.dist
    d = np.full((ds.N, ds.N), p.default_distance_km); np.fill_diagonal(d, 0.0); return d


def circle(lat, lon, km, n=60):
    ang = np.linspace(0, 2*np.pi, n); dlat = km/111.0; dlon = km/(111.0*max(np.cos(np.radians(lat)), 0.05))
    return lat + dlat*np.sin(ang), lon + dlon*np.cos(ang)


def nearby(ds, p, store, radius_km, sc=None):
    i = ds.stores.store.tolist().index(store); d = dist_matrix(ds, p)[i]
    df = pd.DataFrame({"store": ds.stores.store, "distance_km": d}); df = df[(df.store != store) & (df.distance_km <= radius_km)].sort_values("distance_km")
    if sc is not None and len(df):
        g = sc.groupby("store").agg(expected_loss=("value_at_risk", "sum"), stock_value=("stock_value", "sum")); df = df.merge(g, left_on="store", right_index=True, how="left")
    return df.reset_index(drop=True)


def scorecard(ds, fi, res, p: Params):
    sc, act, fc = res["sc"], res["actions"], fi["fc"]
    g = sc.groupby("store").agg(stock_value=("stock_value", "sum"), units=("qty", "sum"), expected_loss=("value_at_risk", "sum"), high_risk_batches=("p_unsold", lambda x: int((x >= 0.7).sum())), batches=("bid", "size"))
    g = g.reindex(ds.stores.store).fillna(0); g["loss_pct_of_stock"] = 100*g.expected_loss/g.stock_value.replace(0, np.nan)
    daily = fc[:, :, :30].sum((1, 2))/30; g["days_of_cover"] = g.units.values/np.maximum(daily, 1e-9)
    g["units_out"] = 0; g["units_in"] = 0
    if len(act):
        mv = act[act.action.isin(["TRANSFER", "RETURN"])]
        g["units_out"] = mv.groupby("store_from").units.sum().reindex(g.index).fillna(0).astype(int)
        g["units_in"] = act[act.action == "TRANSFER"].groupby("store_to").units.sum().reindex(g.index).fillna(0).astype(int)
    g["risk_rank"] = g.expected_loss.rank(ascending=False, method="min").astype(int)
    return g.reset_index().rename(columns={"index": "store"})


def transfer_options(ds, fi, res, r, units, p: Params, optimizer_picks=(), skip_last=0):
    """For one source batch row r (from res['sc']) and a number of units, evaluate EVERY other store as a destination."""
    sc, fc, alpha, T = res["sc"], fi["fc"], fi["alpha"], ds.T
    k, s, e = int(r.k), int(r.s), int(r.exp); d = e - T; c = float(ds.cost[k]); dist = dist_matrix(ds, p)
    pos = np.arange(int(r.C) - skip_last - units + 1, int(r.C) - skip_last + 1); e_src = float((1 - cdf(pos - 1, r.mu, alpha)).sum())      # the units we'd move are the last in the sell queue
    rows = []
    for j in range(ds.N):
        if j == s: continue
        name = ds.stores.store.iloc[j]; mine = sc[(sc.s == j) & (sc.k == k)]; mu_j = float(fc[j, k, :d].sum()) if 1 <= d <= HORIZON else 0.0
        c_le = int(mine.loc[mine.exp <= e, "qty"].sum()); m = np.arange(1, units + 1); ps = 1 - cdf(c_le + m - 1, mu_j, alpha)
        cap = receiver_capacity(sc, fc, T, alpha, j, k, e, units, p) if d >= 2 else 0
        ship = p.lane_fixed + p.lane_per_km*float(dist[s, j]) + units*p.unit_handling
        flags = []
        if name in p.blocked_receivers: flags.append("blocked receiver")
        if p.max_transfer_km > 0 and dist[s, j] > p.max_transfer_km: flags.append(f"> {p.max_transfer_km:g} km limit")
        if d < p.transfer_min_days: flags.append(f"only {d}d left")
        if units > cap: flags.append(f"exceeds safe capacity ({cap})")
        rows.append(dict(destination=name, distance_km=float(dist[s, j]), existing_stock=int(mine.qty.sum()), demand_to_expiry=mu_j, first_unit_sell_prob=float(ps[0]), avg_sell_prob=float(ps.mean()),
                         expected_units_sold=float(ps.sum()), safe_capacity=int(cap), shipping_cost=ship, expected_gain=c*(float(ps.sum()) - e_src) - ship,
                         optimizer_pick=name in optimizer_picks, warnings="; ".join(flags) if flags else "✅ ok"))
    return pd.DataFrame(rows).sort_values("expected_gain", ascending=False).reset_index(drop=True), e_src
