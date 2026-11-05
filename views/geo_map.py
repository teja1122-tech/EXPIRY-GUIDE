import numpy as np, pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui
from core import auth, geo
from views import anim

METRICS = {"Expected expiry loss": "expected_loss", "Loss as % of stock": "loss_pct_of_stock", "High-risk batches": "high_risk_batches", "Days of cover": "days_of_cover", "Stock value": "stock_value"}


def _zoom(lat, lon):
    span = max(np.ptp(lat), np.ptp(lon), 0.02); return float(np.clip(np.log2(360/span) - 1, 2, 14))


def render():
    ds, fi, res = ui.need_analysis(); S = st.session_state; user, P = S.user, S.params
    ui.hero("Geo Map", "See every store on a real map: where the expiry risk is, which shipping lanes the plan uses, and who is close enough to help.")
    sc_card = geo.scorecard(ds, fi, res, P); has = not (ds.stores.lat.isna().any() or ds.stores.lon.isna().any()); act = res["actions"]
    mine = set(auth.allowed_stores(user, ds.stores.store.tolist())); restricted = user["role"] != "admin" and bool(user["stores"])
    names = ds.stores.store.tolist(); kv = ui.get_focus()["version"]
    def _store_from_points(pts):
        for p in pts:
            cd = p.get("customdata"); cd = cd[0] if isinstance(cd, (list, tuple)) and cd else cd
            if cd in names: return cd
        return None
    if ui.sync_selection(f"gm_map_{kv}", _store_from_points, lambda v_: ui.set_focus(store=v_) if v_ else False): st.rerun()
    if ui.sync_selection(f"gm_sc1_{kv}", lambda pts: next((p.get("y") for p in pts if p.get("y") in names), None), lambda v_: ui.set_focus(store=v_) if v_ else False): st.rerun()
    fstore = ui.get_focus()["store"]
    ui.apply_focus("geo", {"gm_sel": lambda f_: f_["store"] if f_["store"] in names else "— none —", "gm_near_store": lambda f_: f_["store"] if f_["store"] in names else ui.SKIP})
    t1, t2, t3, t4 = st.tabs(["🗺️ Map", "📍 Nearby & distances", "🏆 Store scorecards", "✏️ Edit locations"])
    with t1:
        if not has: st.warning("Some stores have no coordinates. Add them in the **Edit locations** tab to unlock the map and distance-based shipping costs.")
        else:
            c = st.columns([1.2, 1.2, 1, 1]); metric = c[0].selectbox("Bubble size = ", list(METRICS), key="gm_metric"); style = c[1].selectbox("Map style", ["carto-positron", "open-street-map", "carto-darkmatter", "white-bg"], key="gm_style", help="'white-bg' needs no internet map tiles.")
            lanes = c[2].checkbox("Show planned transfer lanes", True, key="gm_lanes"); sel = c[3].selectbox("Radius around", ["— none —"] + ds.stores.store.tolist(), key="gm_sel")
            rad = st.slider("Radius (km)", 1, 60, 10, key="gm_rad") if sel != "— none —" else 0
            g = ds.stores.merge(sc_card, on="store"); col = METRICS[metric]; v = g[col].fillna(0).astype(float).values; size = 14 + 36*(v - v.min())/max(v.max() - v.min(), 1e-9)
            f = go.Figure()
            if lanes and len(act):
                t = act[act.action == "TRANSFER"].groupby(["store_from", "store_to"]).units.sum().reset_index(); mx = max(t.units.max(), 1) if len(t) else 1
                pos = {r.store: (r.lat, r.lon) for r in ds.stores.itertuples()}
                for r in t.itertuples():
                    (a1, o1), (a2, o2) = pos[r.store_from], pos[r.store_to]
                    f.add_trace(go.Scattermap(lat=[a1, a2], lon=[o1, o2], mode="lines", line=dict(width=1.5 + 6*r.units/mx, color="rgba(29,111,95,.7)"), hoverinfo="text", text=f"{r.store_from} → {r.store_to}: {r.units} units", showlegend=False))
                    f.add_trace(go.Scattermap(lat=[a1 + .8*(a2-a1)], lon=[o1 + .8*(o2-o1)], mode="markers", marker=dict(size=9, color=ui.GREEN), hoverinfo="skip", showlegend=False))
            if sel != "— none —":
                s0 = ds.stores[ds.stores.store == sel].iloc[0]; cl, co = geo.circle(s0.lat, s0.lon, rad); f.add_trace(go.Scattermap(lat=cl, lon=co, mode="lines", line=dict(width=2, color=ui.AMBER), name=f"{rad} km", hoverinfo="skip"))
            hover = [f"<b>{r.store}</b><br>Expected loss: {r.expected_loss:,.0f}<br>High-risk batches: {int(r.high_risk_batches)}<br>Days of cover: {r.days_of_cover:.0f}<br>Out/In (units): {int(r.units_out)}/{int(r.units_in)}" if (not restricted or r.store in mine) else f"<b>{r.store}</b>" for r in g.itertuples()]
            if fstore in names:
                fr = ds.stores[ds.stores.store == fstore].iloc[0]; f.add_trace(go.Scattermap(lat=[fr.lat], lon=[fr.lon], mode="markers", marker=dict(size=64, color="rgba(217,162,59,.30)"), hoverinfo="skip", name="Focus", showlegend=False))
            f.add_trace(go.Scattermap(lat=g.lat, lon=g.lon, customdata=g.store, mode="markers+text", text=g.store.str.replace("Store-", "S"), textposition="top right", hovertext=hover, hoverinfo="text", name="Stores",
                                      marker=dict(size=size, color=v, colorscale="Reds", showscale=True, colorbar=dict(title=metric, thickness=12), opacity=.9)))
            f.update_layout(map=dict(style=style, center=dict(lat=float(g.lat.mean()), lon=float(g.lon.mean())), zoom=_zoom(g.lat.values, g.lon.values)), height=560, margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h", y=1.02))
            ui.pc(f, f"gm_map_{kv}", select=True); st.caption("Click a store to make it the global focus. Bubble size and colour follow the chosen metric. Green lines = planned transfers (dot near the destination). Map tiles load from the internet in your browser.")
            with st.expander("▶ Replay the plan, lane by lane"):
                rp = anim.plan_replay(ds, act)
                if rp is not None: ui.pc(rp, "gm_replay")
                else: st.info("No transfer lanes in the current plan.")
    with t2:
        c = st.columns(2); s_ = c[0].selectbox("Store", ds.stores.store.tolist(), key="gm_near_store"); r_ = c[1].slider("Within (km)", 1, 80, 15, key="gm_near_r")
        nb = geo.nearby(ds, P, s_, r_, res["sc"])
        st.dataframe(nb, hide_index=True, width="stretch", column_config={"distance_km": st.column_config.NumberColumn("km", format="%.1f"), "expected_loss": st.column_config.NumberColumn(format="%.0f"), "stock_value": st.column_config.NumberColumn(format="%.0f")}) if len(nb) else st.info("No other store within this radius.")
        if not has: st.caption(f"No coordinates uploaded: all store-to-store distances use the default {P.default_distance_km:g} km.")
        st.button(f"🔗 Make {s_} the global focus", key="gm_focus", on_click=lambda x_=s_: ui.set_focus(store=x_))
        dm = pd.DataFrame(geo.dist_matrix(ds, P), index=ds.stores.store, columns=ds.stores.store)
        f = px.imshow(dm, color_continuous_scale="Greens_r", title="Distance between stores (km)", aspect="auto"); f.update_layout(height=420); ui.pc(f, "gm_dm")
    with t3:
        sc2 = sc_card.copy()
        if restricted: sc2 = sc2[sc2.store.isin(mine)]
        st.dataframe(sc2.sort_values("expected_loss", ascending=False), hide_index=True, width="stretch", column_config={
            "stock_value": st.column_config.NumberColumn(format="%.0f"), "expected_loss": st.column_config.NumberColumn("Expected loss", format="%.0f"), "loss_pct_of_stock": st.column_config.ProgressColumn("Loss % of stock", min_value=0, max_value=max(float(sc2.loss_pct_of_stock.max()), 1), format="%.1f%%"),
            "days_of_cover": st.column_config.NumberColumn(format="%.0f"), "units": st.column_config.NumberColumn(format="%.0f")})
        a, b = st.columns(2)
        f = px.bar(sc2.sort_values("expected_loss"), x="expected_loss", y="store", orientation="h", title="Expected expiry loss by store · click a bar to focus", color_discrete_sequence=[ui.RED]); f.update_layout(height=360, xaxis_title=None, yaxis_title=None, clickmode="event+select")
        with a: ui.pc(f, f"gm_sc1_{kv}", select=True)
        f = px.scatter(sc2, x="days_of_cover", y="loss_pct_of_stock", size=np.maximum(sc2.stock_value, 1), text="store", title="Over-stocked stores sit top-right (high cover, high loss %)", color_discrete_sequence=[ui.GREEN]); f.update_traces(textposition="top center"); f.update_layout(height=360, xaxis_title="Days of cover", yaxis_title="Loss % of stock")
        with b: ui.pc(f, "gm_sc2")
    with t4:
        can = user["role"] in ("admin", "manager", "analyst")
        st.write("Edit coordinates (decimal degrees). Saved locations are remembered and re-applied to every future upload; shipping costs and the transfer planner switch to real distances immediately.")
        ed = st.data_editor(ds.stores[["store", "lat", "lon"]], hide_index=True, disabled=["store"] if can else True, width="stretch", key="gm_editor", column_config={"lat": st.column_config.NumberColumn("Latitude", format="%.5f"), "lon": st.column_config.NumberColumn("Longitude", format="%.5f")})
        if st.button("💾 Save locations", type="primary", disabled=not can, key="gm_save"):
            try:
                geo.save_locations(ed, user); geo.apply_overrides(ds); st.success("Locations saved. Distances and plans updated."); st.rerun()
            except ValueError as e: st.error(str(e))
        if not can: st.caption("Only managers, analysts and administrators can edit locations.")
