import numpy as np, pandas as pd, plotly.graph_objects as go
import streamlit as st
import ui
from core import tasks

COLS = ["id", "approve", "action", "store_from", "store_to", "sku", "batch_id", "units", "days_left", "expiry_date", "unit_cost", "move_cost", "est_gain", "credit"]


def _network(ds, act):
    st_ = ds.stores.copy()
    if st_.lat.isna().any():
        ang = np.linspace(0, 2*np.pi, len(st_), endpoint=False); st_["lon"], st_["lat"] = np.cos(ang), np.sin(ang)
    pos = {r.store: (r.lon, r.lat) for r in st_.itertuples()}
    fig = go.Figure()
    t = act[act.action == "TRANSFER"].groupby(["store_from", "store_to"]).units.sum().reset_index()
    mx = max(t.units.max(), 1) if len(t) else 1
    for r in t.itertuples():
        (x0, y0), (x1, y1) = pos[r.store_from], pos[r.store_to]
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(width=1.5+7*r.units/mx, color="rgba(29,111,95,.55)"), hoverinfo="text", text=f"{r.store_from} → {r.store_to}: {r.units} units", showlegend=False))
        fig.add_annotation(x=x1, y=y1, ax=x0+(x1-x0)*.25, ay=y0+(y1-y0)*.25, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowcolor=ui.GREEN)
    out = act[act.action.isin(["TRANSFER", "RETURN"])].groupby("store_from").units.sum()
    fig.add_trace(go.Scatter(x=[pos[s][0] for s in st_.store], y=[pos[s][1] for s in st_.store], mode="markers+text", text=st_.store.str.replace("Store-", "S"), textposition="top center",
                             marker=dict(size=[14+min(30, out.get(s, 0)/4) for s in st_.store], color=[ui.RED if out.get(s, 0) else ui.GREY for s in st_.store], line=dict(width=1, color="white")),
                             hovertext=[f"{s}: {int(out.get(s, 0))} units leaving" for s in st_.store], hoverinfo="text", showlegend=False))
    fig.update_layout(title="Transfer network (line width = units moved; red node = store sending/returning stock)", height=460, xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
    return fig


def render():
    ds, fi, res = ui.need_analysis(); act = res["actions"]; k = res["kpis"]
    ui.hero("Action Center", "Review the recommended moves, approve or reject each one, and export pick-lists for your stores.")
    if act.empty: st.info("No at-risk units need action under the current settings."); return
    c = st.columns(4)
    ui.kpi(c[0], "Transfers", f"{k['transfer_units']} units", f"worth {ui.money(k['transfer_value'])} at cost"); ui.kpi(c[1], "Returns to distributor", f"{k['return_units']} units", f"credit {ui.money(k['credit'])}")
    ui.kpi(c[2], "Manual markdown review", f"{k['markdown_units']} units", f"worth {ui.money(k['markdown_value'])} at cost", "bad"); ui.kpi(c[3], "Est. net gain (all)", ui.money(k["est_net_gain"]), "conservative lower bound", "good")
    st.caption("Status: " + res["info"].get("status", "") + f" · {res['info'].get('n_lanes', 0)} shipping lane(s) used")
    which = st.radio("Show", ["All", "TRANSFER", "RETURN", "MARKDOWN_REVIEW"], horizontal=True, key="ac_filter")
    v = act if which == "All" else act[act.action == which]
    ed = st.data_editor(v[COLS], hide_index=True, width="stretch", height=360, key=f"ac_editor_{abs(hash(st.session_state.plan_key))}_{which}",
                        disabled=[c for c in COLS if c != "approve"], column_config={"approve": st.column_config.CheckboxColumn("Approve ✓"), "est_gain": st.column_config.NumberColumn("Est. gain", format="%.0f"),
                        "move_cost": st.column_config.NumberColumn("Cost", format="%.0f"), "credit": st.column_config.NumberColumn("Credit", format="%.0f"), "unit_cost": st.column_config.NumberColumn("Unit cost", format="%.2f")})
    ap = ed[ed.approve]
    m = st.columns(4); ui.kpi(m[0], "Approved actions", len(ap)); ui.kpi(m[1], "Approved units", int(ap.units.sum())); ui.kpi(m[2], "Credit + costs", f"{ui.money(ap.credit.sum())} / {ui.money(ap.move_cost.sum())}"); ui.kpi(m[3], "Approved est. gain", ui.money(ap.est_gain.sum()), tone="good")
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Download approved actions (CSV)", ap.to_csv(index=False), "approved_actions.csv", key="dl_ap"); d2.download_button("⬇️ Download full plan (CSV)", act[COLS].to_csv(index=False), "full_plan.csv", key="dl_full")
    st.markdown("##### Hand over to stores")
    h1, h2, h3 = st.columns([2, 1.5, 2]); user = st.session_state.user
    auto = h2.checkbox("Approve immediately", key="ac_auto", disabled=user["role"] not in ("admin", "manager"), help="Managers/admins only")
    if h1.button(f"📨 Send {len(ap)} approved action(s) to the Task Board", type="primary", disabled=ap.empty, key="ac_send"):
        rows = [dict(kind=r.action, store_from=r.store_from, store_to=r.store_to, sku=r.sku, batch_id=r.batch_id, units=int(r.units), expiry_date=str(r.expiry_date), est_gain=float(r.est_gain), credit=float(r.credit), move_cost=float(r.move_cost)) for r in ap.itertuples()]
        made, skipped = tasks.create_tasks(rows, user, status="APPROVED" if auto else "PROPOSED", as_of=str(ds.as_of.date()))
        st.toast(f"{made} task(s) sent to the Task Board", icon="📨"); st.success(f"Created {made} task(s)" + (f"; {skipped} duplicate(s) skipped" if skipped else "") + ". Track them in ✅ Task Board.")
    tr = ap[ap.action == "TRANSFER"]
    if len(tr):
        pick = h3.selectbox("Want a different destination? Re-route in the planner:", tr.id.tolist(), format_func=lambda i: f"#{i} {tr.set_index('id').loc[i, 'sku']} {tr.set_index('id').loc[i, 'store_from']}→{tr.set_index('id').loc[i, 'store_to']}", key="ac_reroute")
        def _go(i=None):
            S = st.session_state; row = act[act.id == S.ac_reroute].iloc[0]; b = res["sc"][res["sc"].bid == row.bid].iloc[0]
            S.tp_store, S.tp_batch, S.page = b.store, int(row.bid), "🔀 Transfer Planner"
        h3.button("🔀 Open in Transfer Planner", on_click=_go, key="ac_reroute_btn")
    t1, t2 = st.tabs(["🗺️ Transfer network", "📦 Store pick-lists"])
    with t1:
        if (act.action == "TRANSFER").any(): ui.pc(_network(ds, act), "ac_net")
        else: st.info("No transfers in this plan.")
    with t2:
        s = st.selectbox("Store", ds.stores.store.tolist(), key="ac_store"); a = ap[ap.action.isin(["TRANSFER", "RETURN"])]
        out, inc = a[a.store_from == s], a[a.store_to == s]
        c1, c2 = st.columns(2)
        c1.markdown(f"**Send out from {s}**"); c1.dataframe(out[["action", "store_to", "sku", "batch_id", "units", "expiry_date"]], hide_index=True, width="stretch")
        c2.markdown(f"**Receiving at {s}**"); c2.dataframe(inc[["store_from", "sku", "batch_id", "units", "expiry_date"]], hide_index=True, width="stretch")
        st.download_button(f"⬇️ Pick-list for {s}", pd.concat([out.assign(direction="OUT"), inc.assign(direction="IN")]).to_csv(index=False), f"picklist_{s}.csv", key="dl_pick")
