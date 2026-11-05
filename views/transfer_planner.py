import numpy as np, pandas as pd, plotly.graph_objects as go
import streamlit as st
import ui
from core import auth, geo, tasks


def _map(ds, src, opt, chosen):
    st_ = ds.stores
    if st_.lat.isna().any(): return None
    f = go.Figure()
    for nm in chosen:
        a, b = st_[st_.store == src].iloc[0], st_[st_.store == nm].iloc[0]
        f.add_trace(go.Scattermap(lat=[a.lat, b.lat], lon=[a.lon, b.lon], mode="lines", line=dict(width=4, color=ui.GREEN), hoverinfo="skip", showlegend=False))
    o = opt.merge(st_, left_on="destination", right_on="store")
    f.add_trace(go.Scattermap(lat=o.lat, lon=o.lon, mode="markers+text", text=o.destination.str.replace("Store-", "S"), textposition="top right", name="Candidates",
                              marker=dict(size=10+24*o.first_unit_sell_prob, color=[ui.GREEN if d in chosen else "#9AD1C4" for d in o.destination]),
                              hovertext=[f"{r.destination}: {r.distance_km:.1f} km · sell chance {r.first_unit_sell_prob:.0%} · gain {r.expected_gain:,.0f}" for r in o.itertuples()], hoverinfo="text"))
    s = st_[st_.store == src].iloc[0]
    f.add_trace(go.Scattermap(lat=[s.lat], lon=[s.lon], mode="markers+text", text=[src], textposition="top right", name="Source", marker=dict(size=22, color=ui.RED)))
    f.update_layout(map=dict(style="carto-positron", center=dict(lat=float(st_.lat.mean()), lon=float(st_.lon.mean())), zoom=9.2), height=380, margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h", y=1.02))
    return f


def render():
    ds, fi, res = ui.need_analysis(); S = st.session_state; user, P = S.user, S.params
    ui.hero("Transfer Planner", "You choose where stock goes. Pick a batch, compare every possible destination on sell-through, distance and cost, then raise the request.")
    allowed = auth.allowed_stores(user, ds.stores.store.tolist())
    if not allowed: st.warning("No stores are assigned to your account. Ask an administrator."); return
    sc = res["sc"]; cand = sc[sc.scored & (sc.days_left >= 2) & sc.store.isin(allowed)]
    if cand.empty: st.info("No batches within the 120-day risk window in your stores."); return
    srcs = sorted(cand.store.unique())
    ui.apply_focus("planner", {"tp_store": lambda f: f["store"] if f["store"] in srcs else ui.SKIP})
    if S.get("tp_store") not in srcs: S.pop("tp_store", None)
    c1, c2 = st.columns([1, 3]); store = c1.selectbox("Source store", srcs, key="tp_store")
    sub = cand[cand.store == store].sort_values("value_at_risk", ascending=False); lab = {r.bid: f"{r.sku} · batch {r.batch_id} · {int(r.qty)} units · {int(r.days_left)}d left · P(expire) {r.p_unsold:.0%} · {ui.money(r.value_at_risk)} at risk" for r in sub.itertuples()}
    if S.get("tp_batch") not in lab: S.pop("tp_batch", None)
    bid = c2.selectbox("Batch to move", list(lab), format_func=lambda b: lab[b], key="tp_batch"); r = sub[sub.bid == bid].iloc[0]
    act = res["actions"]; recs = act[(act.bid == bid) & (act.action != "MARKDOWN_REVIEW")] if len(act) else act
    m = st.columns(4); ui.kpi(m[0], "In this batch", f"{int(r.qty)} units", f"expires in {int(r.days_left)} days"); ui.kpi(m[1], "P(some expire)", f"{r.p_unsold:.0%}", tone="bad" if r.p_unsold >= .7 else "")
    ui.kpi(m[2], "Units flagged at-risk", int(r.at_risk_units)); ui.kpi(m[3], "Optimizer recommends", "; ".join(f"{a.action.title()} {a.units}" + (f" → {a.store_to}" if a.store_to else "") for a in recs.itertuples()) or "nothing cost-effective", "")
    units = st.slider("Units to evaluate", 1, int(r.qty), int(min(max(r.at_risk_units, 1), r.qty)), key=f"tp_units_{bid}")
    picks = set(recs[recs.action == "TRANSFER"].store_to) if len(recs) else set()
    opt, e_src = geo.transfer_options(ds, fi, res, r, units, P, picks)
    st.markdown(f"**Destination comparison for moving {units} unit(s)** · at the source these units have an expected **{e_src:.1f}** sales")
    st.dataframe(opt, hide_index=True, width="stretch", height=300, column_config={
        "distance_km": st.column_config.NumberColumn("km", format="%.1f"), "demand_to_expiry": st.column_config.NumberColumn("Demand to expiry", format="%.1f"),
        "first_unit_sell_prob": st.column_config.ProgressColumn("P(sells)", min_value=0, max_value=1, format="percent"), "avg_sell_prob": st.column_config.ProgressColumn("Avg P(sells)", min_value=0, max_value=1, format="percent"),
        "expected_units_sold": st.column_config.NumberColumn("Exp. sold", format="%.1f"), "shipping_cost": st.column_config.NumberColumn("Shipping", format="%.0f"), "expected_gain": st.column_config.NumberColumn("Expected gain", format="%.0f"),
        "optimizer_pick": st.column_config.CheckboxColumn("Optimizer pick")})
    st.caption("Why can the optimizer's pick differ from the top row? It plans all SKUs together and shares one shipping lane across many batches, so a lane that is already in use is cheaper than it looks for a single batch. Overriding is fine - the table shows the trade-off.")
    st.markdown("**Your allocation** (split across up to two stores)")
    names = ["— none —"] + opt.destination.tolist(); best = opt.destination.iloc[0]
    if S.get("tp_prefill_to") in names: S["tp_d1"] = S.pop("tp_prefill_to")
    for kk, opts_ in (("tp_d1", names[1:]), ("tp_d2", names)):
        if S.get(kk) not in opts_: S.pop(kk, None)
    a, b, c, d = st.columns([2, 1, 2, 1])
    d1 = a.selectbox("Destination 1", names[1:], index=0, key="tp_d1"); u1 = b.number_input("Units", 1, int(r.qty), units, key=f"tp_u1_{bid}")
    d2 = c.selectbox("Destination 2 (optional)", names, key="tp_d2"); u2 = d.number_input("Units ", 0, int(r.qty), 0, key=f"tp_u2_{bid}", disabled=(d2 == "— none —"))
    alloc = [(d1, int(u1), 0)] + ([(d2, int(u2), int(u1))] if d2 != "— none —" and u2 > 0 else []); total = sum(x[1] for x in alloc)
    if total > r.qty: st.error(f"You allocated {total} units but the batch only has {int(r.qty)}."); return
    if len({x[0] for x in alloc}) < len(alloc): st.error("Choose two different destinations."); return
    rows, warns, mapdest = [], [], []
    for dest, u, skip in alloc:
        o2, es = geo.transfer_options(ds, fi, res, r, u, P, picks, skip_last=skip); x = o2[o2.destination == dest].iloc[0]; mapdest.append(dest)
        rows.append(dict(destination=dest, units=u, distance_km=x.distance_km, avg_sell_prob=x.avg_sell_prob, shipping_cost=x.shipping_cost, expected_gain=x.expected_gain, warnings=x.warnings))
        if x.warnings != "✅ ok": warns.append(f"{dest}: {x.warnings}")
        rows[-1]["_row"] = dict(kind="MANUAL_TRANSFER", store_from=store, store_to=dest, sku=r.sku, batch_id=r.batch_id, units=u, expiry_date=str((ds.start + pd.Timedelta(days=int(r.exp))).date()), est_gain=float(x.expected_gain), move_cost=float(x.shipping_cost))
    summ = pd.DataFrame([{k: v for k, v in z.items() if k != "_row"} for z in rows]); st.dataframe(summ, hide_index=True, width="stretch", column_config={"avg_sell_prob": st.column_config.ProgressColumn("Avg P(sells)", min_value=0, max_value=1, format="percent"), "expected_gain": st.column_config.NumberColumn(format="%.0f"), "shipping_cost": st.column_config.NumberColumn(format="%.0f"), "distance_km": st.column_config.NumberColumn(format="%.1f")})
    k = st.columns(3); ui.kpi(k[0], "Units moving", total, f"of {int(r.qty)} in batch"); ui.kpi(k[1], "Shipping cost", ui.money(summ.shipping_cost.sum())); ui.kpi(k[2], "Expected gain", ui.money(summ.expected_gain.sum()), tone="good" if summ.expected_gain.sum() > 0 else "bad")
    mp = _map(ds, store, opt, mapdest)
    if mp is not None: ui.pc(mp, "tp_map")
    else: st.caption("Add store coordinates in 🌍 Geo Map → Edit locations to see this on a map.")
    ack = True
    if warns:
        st.warning("⚠️ " + " | ".join(warns)); ack = st.checkbox("I understand these warnings and want to proceed", key="tp_ack")
        if any("blocked receiver" in w for w in warns) and user["role"] not in ("admin", "manager"): st.error("Only a manager or administrator can send stock to a blocked receiver."); ack = False
    note = st.text_input("Note for the receiving store (optional)", key="tp_note"); auto = user["role"] in ("admin", "manager") and st.checkbox("Approve immediately (manager)", key="tp_auto")
    if st.button("📨 Create transfer request", type="primary", disabled=not ack, key="tp_create"):
        made, skipped = tasks.create_tasks([z["_row"] for z in rows], user, status="APPROVED" if auto else "PROPOSED", note=note, as_of=str(ds.as_of.date()))
        if made: st.toast(f"{made} transfer request(s) created", icon="📨"); st.success(f"Created {made} request(s)" + (" (approved)." if auto else " - awaiting manager approval.") + " Track it in ✅ Task Board.")
        if skipped: st.info(f"{skipped} identical active request(s) already exist - not duplicated.")
