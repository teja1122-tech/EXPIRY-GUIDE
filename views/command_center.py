import pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui
from views import anim


def render():
    ds, fi, res = ui.need_analysis(); k, sc_all = res["kpis"], res["sc"]; f = ui.get_focus(); kv = f["version"]
    cats = sorted(ds.skus.category.unique())
    ui.apply_focus("command", {"cc_cat": lambda f_: f_["category"]})
    # a click on a store bar becomes the global focus (read the selection BEFORE drawing anything that depends on it)
    if ui.sync_selection(f"cc_store_bar_{kv}", lambda pts: (pts[0].get("y") if pts else None), lambda v: ui.set_focus(store=v)): st.rerun()
    f = ui.get_focus(); kv = f["version"]
    sc = sc_all
    if f["store"]: sc = sc[sc.store == f["store"]]
    if f["category"]: sc = sc[sc.category == f["category"]]
    ui.hero("Command Center", f"Expiry exposure across {ds.N} stores and {ds.K} SKUs as of {ds.as_of.date()} · forecast: {fi['method']}")
    ui.tiles([("🔍", "Review high-risk batches", "Filter, lasso and deep-dive", "⚠️ Risk Explorer"), ("🚚", "Decide actions", "Approve transfers & returns", "🚚 Action Center"),
              ("🌍", "See it on the map", "Store risk and shipping lanes", "🌍 Geo Map"), ("✅", "Track tasks", "Approve, dispatch, receive", "✅ Task Board")])
    pct = 100*k["value_at_risk"]/max(k["stock_value"], 1)
    c = st.columns(6)
    ui.kpi(c[0], "Stock value (cost)", ui.money(k["stock_value"]), f"{k['n_batches']} live batches")
    ui.kpi(c[1], "Expected expiry loss", ui.money(k["value_at_risk"]), f"{pct:.1f}% of stock · next 120d", "bad")
    ui.kpi(c[2], "High-risk batches", k["high_risk_batches"], "≥70% chance to expire", "bad")
    ui.kpi(c[3], "Expiring ≤ 30 days", ui.money(k["exp30_value"]), "stock value")
    ui.kpi(c[4], "Already expired", ui.money(k["expired_value"]), f"{k['expired_batches']} batches", "bad" if k["expired_batches"] else "")
    ui.kpi(c[5], "Plan: est. net gain", ui.money(k["est_net_gain"]), "conservative lower bound", "good")
    soon = sc_all[(sc_all.days_left <= 14) & (sc_all.p_unsold >= 0.7)]
    if k["expired_batches"]: st.error(f"⛔ {k['expired_batches']} batch(es) worth {ui.money(k['expired_value'])} are expired or expire today - pull from shelves (list in Excel report).")
    if len(soon): st.warning(f"⏰ {len(soon)} batch(es) worth {ui.money(soon.stock_value.sum())} expire within 14 days and are very likely to go unsold.")
    # ---------------- linked controls ----------------
    st.markdown("#### 🔗 Click a store bar or pick a category - every chart below follows")
    a0, b0 = st.columns([1.3, 1])
    base = sc_all[sc_all.scored]
    if f["category"]: base = base[base.category == f["category"]]
    by_store = base.groupby("store").value_at_risk.sum().reindex(ds.stores.store).fillna(0).sort_values()
    bar = go.Figure(go.Bar(x=by_store.values, y=by_store.index, orientation="h", marker_color=[ui.GREEN if s == f["store"] else ui.RED for s in by_store.index],
                           hovertemplate="%{y}: %{x:,.0f}<extra></extra>"))
    bar.update_layout(title="Expected loss by store (click a bar to focus)", height=360, xaxis_title=None, yaxis_title=None, clickmode="event+select")
    with a0: ui.pc(bar, f"cc_store_bar_{kv}", select=True)
    with b0:
        cat = st.pills("Category focus", cats, selection_mode="single", key="cc_cat")
        if cat != f["category"]:
            ui.set_focus(category=cat); st.rerun()
        if f["store"] or f["category"]:
            sub = sc[sc.scored]; st.markdown(f"<span class='chip focus'>Showing: {f['store'] or 'all stores'} · {f['category'] or 'all categories'}</span>", unsafe_allow_html=True)
            m1, m2 = st.columns(2); ui.kpi(m1, "Expected loss (focus)", ui.money(sub.value_at_risk.sum()), tone="bad"); ui.kpi(m2, "High-risk batches (focus)", int((sub.p_unsold >= 0.7).sum()))
        else: st.caption("No focus set. Pick a category or click a store bar - the focus follows you to Risk Explorer, Forecast Explorer, Geo Map and Transfer Planner.")
    a, b = st.columns([1.5, 1])
    hm = sc_all[sc_all.scored].pivot_table(index="store", columns="category", values="value_at_risk", aggfunc="sum").fillna(0)
    fig = px.imshow(hm, aspect="auto", color_continuous_scale="Reds", title="Expected expiry loss by store × category", labels=dict(color="Loss"))
    fig.update_traces(hovertemplate="%{y} · %{x}<br>Expected loss: %{z:,.0f}<extra></extra>"); fig.update_layout(height=380)
    if f["store"] in list(hm.index): i = list(hm.index).index(f["store"]); fig.add_hrect(y0=i-.5, y1=i+.5, line=dict(color=ui.GREEN, width=3))
    if f["category"] in list(hm.columns): j = list(hm.columns).index(f["category"]); fig.add_vrect(x0=j-.5, x1=j+.5, line=dict(color=ui.GREEN, width=3))
    with a: ui.pc(fig, "cc_heat")
    bands = sc.groupby("risk_band").stock_value.sum().reset_index()
    fig = px.pie(bands, names="risk_band", values="stock_value", hole=.55, color="risk_band", color_discrete_map=ui.BAND_COLORS, title="Stock value by risk band" + (" (focus)" if (f["store"] or f["category"]) else ""))
    fig.update_layout(height=380, legend=dict(orientation="h", y=-0.1))
    with b: ui.pc(fig, "cc_pie")
    sc2 = sc.assign(month=pd.to_datetime(ds.start + pd.to_timedelta(sc.exp, "D")).dt.to_period("M").astype(str))
    t = sc2.groupby(["month", "risk_band"]).stock_value.sum().reset_index()
    fig = px.bar(t, x="month", y="stock_value", color="risk_band", color_discrete_map=ui.BAND_COLORS, title="Stock value by expiry month and risk band", category_orders={"risk_band": list(ui.BAND_COLORS)})
    fig.update_layout(height=340, xaxis_title=None, yaxis_title=None, legend_title=None); ui.pc(fig, "cc_timeline")
    st.subheader("⏳ Expiry clock")
    st.caption("Press ▶ Play to watch expected losses build up over the next 120 days if nothing is done. The last frame equals the total expected loss.")
    clock = anim.expiry_clock(sc, ds)
    if clock is not None: ui.pc(clock, "cc_clock")
    else: st.info("No scored batches in the current focus.")
    st.subheader("Top 10 batches by expected loss" + (" (focus)" if (f["store"] or f["category"]) else ""))
    top = sc[sc.scored].sort_values("value_at_risk", ascending=False).head(10)[["store", "sku", "category", "batch_id", "qty", "days_left", "p_unsold", "value_at_risk"]]
    st.dataframe(top, hide_index=True, width="stretch", column_config={
        "p_unsold": st.column_config.ProgressColumn("P(expire)", min_value=0, max_value=1, format="percent"),
        "value_at_risk": st.column_config.NumberColumn("Expected loss", format="%.0f"), "days_left": "Days left", "qty": "Qty"})
