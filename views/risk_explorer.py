import numpy as np, pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui
from core import auth
from core.risk import demand_distribution, cdf


def _bids(points):
    out = []
    for p in points:
        cd = p.get("customdata")
        if isinstance(cd, (list, tuple)) and cd: cd = cd[0]
        if cd is not None: out.append(int(cd))
    return out


def render():
    ds, fi, res = ui.need_analysis(); sc = res["sc"]; alpha = fi["alpha"]; P = st.session_state.params
    ui.hero("Risk Explorer", "Filter every batch, then lasso or box-select bubbles on the chart - the table, KPIs and deep-dive follow your selection.")
    c = st.columns([2, 2, 1.5, 1.5])
    _allowed = auth.allowed_stores(st.session_state.user, ds.stores.store.tolist())
    if not _allowed: st.warning("No stores are assigned to your account."); return
    ui.apply_focus("risk", {"re_st": lambda f: [f["store"]] if f["store"] in _allowed else [], "re_cat": lambda f: [f["category"]] if f["category"] else []})
    stores = c[0].multiselect("Stores", _allowed, key="re_st"); cats = c[1].multiselect("Categories", sorted(ds.skus.category.unique()), key="re_cat")
    dl = c[2].slider("Days to expiry ≤", 1, 120, 120, key="re_dl"); mp = c[3].slider("Min P(expire)", 0.0, 1.0, 0.0, 0.05, key="re_mp")
    v = sc[sc.scored & sc.store.isin(_allowed)].copy()
    if stores: v = v[v.store.isin(stores)]
    if cats: v = v[v.category.isin(cats)]
    v = v[(v.days_left <= dl) & (v.p_unsold >= mp)]
    fkey = f"re_scatter_{abs(hash((tuple(stores), tuple(cats), dl, mp)))}"        # new chart (and selection) whenever filters change
    bids = _bids(ui.selected_points(fkey)); vs = v[v.bid.isin(bids)] if bids else v
    m = st.columns(3); ui.kpi(m[0], "Batches shown" if not bids else "Batches selected", len(vs), f"of {len(v)} in filter" if bids else ""); ui.kpi(m[1], "Expected loss" + (" (selected)" if bids else " (shown)"), ui.money(vs.value_at_risk.sum()), tone="bad"); ui.kpi(m[2], "Units expected to expire", f"{vs.exp_unsold_units.sum():,.0f}")
    if v.empty: st.info("No batches match these filters."); return
    f = px.scatter(v, x="days_left", y="p_unsold", size=np.maximum(v.value_at_risk, 1), color="category", custom_data=["bid"], hover_data=["store", "sku", "batch_id", "qty"], size_max=34,
                   title="Each bubble is a batch: urgency vs probability of expiring (bubble = expected loss) · drag to lasso-select")
    f.update_layout(height=420, xaxis_title="Days to expiry", yaxis_title="P(expires unsold)", yaxis_tickformat=".0%", dragmode="lasso", clickmode="event+select")
    ui.pc(f, fkey, select=True, mode=("points", "box", "lasso"))
    if bids: st.markdown(f"<span class='chip focus'>✨ {len(vs)} batch(es) selected on the chart</span> double-click the chart background to clear.", unsafe_allow_html=True)
    st.dataframe(vs.sort_values("value_at_risk", ascending=False)[["store", "sku", "category", "batch_id", "qty", "days_left", "p_unsold", "exp_unsold_units", "value_at_risk"]],
                 hide_index=True, width="stretch", height=300, column_config={"p_unsold": st.column_config.ProgressColumn("P(expire)", min_value=0, max_value=1, format="percent"),
                 "exp_unsold_units": st.column_config.NumberColumn("Exp. unsold units", format="%.1f"), "value_at_risk": st.column_config.NumberColumn("Expected loss", format="%.0f")})
    st.subheader("🔍 Batch deep-dive")
    top = vs.sort_values("value_at_risk", ascending=False).head(200)
    labels = [f"{r.store} · {r.sku} · batch {r.batch_id} · {r.days_left}d left · {ui.money(r.value_at_risk)} at risk" for r in top.itertuples()]
    pick = st.selectbox("Choose a batch", range(len(top)), format_func=lambda i: labels[i], key="re_pick"); r = top.iloc[pick]
    x, pmf = demand_distribution(r.mu, alpha, upto=int(max(r.C*1.6, r.mu*2.2, 20)))
    f = go.Figure(); f.add_bar(x=x, y=pmf, marker_color=[ui.RED if xi <= r.C-1 else ui.TEAL for xi in x], name="P(demand = x)")
    f.add_vline(x=r.C-0.5, line_dash="dash", line_color="#333", annotation_text=f"stock queued up to this batch = {int(r.C)}")
    f.update_layout(title=f"Demand until expiry (expected {r.mu:.1f} units). Red = outcomes where this batch is NOT fully sold", height=340, xaxis_title="Units demanded before expiry", yaxis_title="Probability", showlegend=False)
    a, b = st.columns([1.5, 1])
    with a: ui.pc(f, "re_dist")
    pos = np.arange(int(r.C_prev)+1, int(r.C)+1); ps = 1-cdf(pos-1, r.mu, alpha)
    g = go.Figure(go.Scatter(x=pos, y=ps, fill="tozeroy", line_color=ui.GREEN)); g.add_hline(y=P.theta_src, line_dash="dot", line_color=ui.RED, annotation_text=f"at-risk threshold {P.theta_src:.0%}")
    g.update_layout(title="Chance each unit in this batch sells (by queue position)", height=340, yaxis_tickformat=".0%", xaxis_title="Position in sell-first queue", yaxis_range=[0, 1.02])
    with b: ui.pc(g, "re_curve")
    k = st.columns(4); ui.kpi(k[0], "P(some units expire)", f"{100*r.p_unsold:.0f}%", tone="bad" if r.p_unsold >= .7 else ""); ui.kpi(k[1], "Expected unsold units", f"{r.exp_unsold_units:.1f} of {int(r.qty)}")
    ui.kpi(k[2], "Expected loss", ui.money(r.value_at_risk), tone="bad"); ui.kpi(k[3], "Units flagged at-risk", int(r.at_risk_units), f"≤{P.theta_src:.0%} sell chance each")
    act = res["actions"]
    if len(act):
        mine = act[(act.batch_id == r.batch_id) & (act.store_from == r.store) & (act.sku == r.sku)]
        if len(mine): st.success("Recommended: " + "; ".join(f"{a.action.title().replace('_',' ')} {a.units} unit(s)" + (f" → {a.store_to}" if a.store_to else "") for a in mine.itertuples()))
    l1, l2, l3 = st.columns(3)
    l1.button(f"🔗 Focus on {r.store}", key="re_focus", on_click=lambda s_=r.store, c_=r.category: ui.set_focus(store=s_, category=c_), width="stretch", help="Makes this store and category the global focus on every page")
    l2.button("🔀 Move this batch in the Transfer Planner", key="re_plan", width="stretch", on_click=lambda s_=r.store, b_=int(r.bid): (st.session_state.update(tp_store=s_, tp_batch=b_), ui.goto("🔀 Transfer Planner")))
