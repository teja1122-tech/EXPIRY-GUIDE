from dataclasses import replace
import pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui
from core.config import Params, PRESETS
from core.pipeline import plan_stage


def _row(name, res):
    k = res["kpis"]; return dict(scenario=name, transfer_units=k["transfer_units"], return_units=k["return_units"], markdown_units=k["markdown_units"],
                                 credit=k["credit"], cost=k["move_cost"], est_net_gain=k["est_net_gain"])


def render():
    ds, fi, res = ui.need_analysis(); S = st.session_state; cur = S.params
    ui.hero("Scenario Lab", "Change business assumptions and see the plan change - test distributor terms, shipping costs and risk appetite before committing.")
    st.markdown("**1 · Pick a starting profile, then tweak**")
    c0 = st.columns([2, 1]); base = c0[0].selectbox("Start from", list(PRESETS), key="sl_base"); p0 = PRESETS[base]
    a, b, c = st.columns(3)
    with a:
        st.markdown("##### Risk appetite")
        ts = st.slider("At-risk if sell chance ≤", 0.05, 0.6, p0.theta_src, 0.05, key="sl_ts", help="Higher = act on more units, earlier.")
        td = st.slider("Receiver must sell with chance ≥", 0.5, 0.95, p0.theta_dst, 0.05, key="sl_td"); kl = st.slider("Protect receiver's later batches ≥", 0.2, 0.8, p0.keep_later, 0.05, key="sl_kl")
    with b:
        st.markdown("##### Distributor terms")
        rc = st.slider("Return credit (% of cost)", 0.0, 1.0, p0.return_credit, 0.05, key="sl_rc"); rd = st.slider("Min days left to return", 0, 180, p0.return_min_days, 5, key="sl_rd"); td2 = st.slider("Min days left to transfer", 0, 90, p0.transfer_min_days, 1, key="sl_td2")
    with c:
        st.markdown("##### Logistics")
        lf = st.number_input("Fixed cost per shipping lane", 0.0, 2000.0, p0.lane_fixed, 10.0, key="sl_lf"); lk = st.number_input("Cost per km", 0.0, 100.0, p0.lane_per_km, 1.0, key="sl_lk")
        dk = st.number_input("Default distance if no coordinates (km)", 1.0, 200.0, p0.default_distance_km, 1.0, key="sl_dk"); at = st.checkbox("Allow transfers", p0.allow_transfers, key="sl_at"); ar = st.checkbox("Allow returns", p0.allow_returns, key="sl_ar")
        mk = st.number_input("Max transfer distance (km, 0 = no limit)", 0.0, 500.0, p0.max_transfer_km, 5.0, key="sl_mk")
        br = st.multiselect("Stores that must NOT receive transfers", ds.stores.store.tolist(), default=[x for x in p0.blocked_receivers if x in set(ds.stores.store)], key="sl_br", help="e.g. closed stores or no cold chain")
        bs = st.multiselect("Stores that must NOT send transfers", ds.stores.store.tolist(), default=[x for x in p0.blocked_senders if x in set(ds.stores.store)], key="sl_bs")
    scen = replace(p0, theta_src=ts, theta_dst=td, keep_later=kl, return_credit=rc, return_min_days=int(rd), transfer_min_days=int(td2), lane_fixed=lf, lane_per_km=lk, default_distance_km=dk, allow_transfers=at, allow_returns=ar, max_transfer_km=mk, blocked_receivers=tuple(br), blocked_senders=tuple(bs))
    name = st.text_input("Scenario name", f"Scenario {len(S.scenarios)+1}", key="sl_name"); b1, b2 = st.columns(2)
    if b1.button("▶️ Run scenario & add to comparison", type="primary", key="sl_run"):
        with st.spinner("Planning..."): r = plan_stage(ds, fi, scen)
        S.scenarios.append(dict(name=name, params=scen, row=_row(name, r)))
    if b2.button("✅ Make this the active profile for all pages", key="sl_apply"):
        S.params = scen; st.success("Active profile updated - all pages now use these settings."); st.rerun()
    st.markdown("**2 · Compare scenarios**")
    rows = [_row("▶ Active profile", res)] + [s["row"] for s in S.scenarios]; df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch", column_config={"est_net_gain": st.column_config.NumberColumn("Est. net gain", format="%.0f"), "credit": st.column_config.NumberColumn("Credit", format="%.0f"), "cost": st.column_config.NumberColumn("Move cost", format="%.0f")})
    st.caption("⚠️ *Est. net gain* is a conservative per-unit lower bound that depends on the risk thresholds, so it is **not comparable across different risk-appetite settings** (an aggressive profile can look worse on this number while recovering more). Compare distributor terms and logistics costs freely; judge risk appetite with the Business Case simulation evidence.")
    if len(df) > 1:
        f = px.bar(df, x="scenario", y="est_net_gain", title="Estimated net gain by scenario", color_discrete_sequence=[ui.GREEN]); f.update_layout(height=300, xaxis_title=None, yaxis_title=None); ui.pc(f, "sl_cmp")
        if st.button("Clear scenarios", key="sl_clear"): S.scenarios = []; st.rerun()
    st.markdown("**3 · Sensitivity sweeps** - how much do the results depend on the assumptions that are hardest to know?")
    if st.button("🔬 Run sensitivity sweeps", key="sl_sweep"):
        bar = st.progress(0.0); out = []; grid = [("Return credit", "return_credit", [0.3, 0.45, 0.6, 0.75, 0.9]), ("Lane fixed cost", "lane_fixed", [0, 60, 150, 300])]; n = sum(len(g[2]) for g in grid); i = 0
        for lab, fld, vals in grid:
            for v in vals:
                r = plan_stage(ds, fi, replace(cur, **{fld: v})); out.append(dict(parameter=lab, value=v, est_net_gain=r["kpis"]["est_net_gain"], units_moved=r["kpis"]["transfer_units"], units_returned=r["kpis"]["return_units"])); i += 1; bar.progress(i/n)
        S.sweep = pd.DataFrame(out)
    if S.get("sweep") is not None:
        cs = st.columns(2)
        for col, lab in zip(cs, ["Return credit", "Lane fixed cost"]):
            d = S.sweep[S.sweep.parameter == lab]; f = go.Figure()
            f.add_scatter(x=d.value, y=d.est_net_gain, name="Est. net gain", mode="lines+markers", line=dict(color=ui.GREEN, width=3)); f.add_bar(x=d.value, y=d.units_returned if lab == "Return credit" else d.units_moved, name="Units returned" if lab == "Return credit" else "Units transferred", marker_color="rgba(217,162,59,.5)", yaxis="y2")
            f.update_layout(title=f"Sensitivity: {lab}", height=320, yaxis2=dict(overlaying="y", side="right", showgrid=False), legend=dict(orientation="h", y=1.15), xaxis_title=lab)
            with col: ui.pc(f, f"sw_{lab}")
