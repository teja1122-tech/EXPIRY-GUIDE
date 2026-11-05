import numpy as np, pandas as pd, plotly.graph_objects as go
import streamlit as st
import ui
from core.risk import markdown_curve


def _best(r, alpha, elasticity, dmax):
    ds_ = np.round(np.arange(0, dmax+1e-9, 0.05), 2); cur = markdown_curve(r.C_prev, int(r.qty), r.mu, alpha, r.unit_price, elasticity, ds_)
    return cur, cur.loc[cur.expected_revenue.idxmax()]


def render():
    ds, fi, res = ui.need_analysis(); sc, alpha = res["sc"], fi["alpha"]; act = res["actions"]
    ui.hero("Markdown Studio", "For units that can't be moved or returned cost-effectively: find the discount that recovers the most cash.")
    st.warning("Discount response is **your assumption**, not learned from data: demand uplift = 1 + elasticity × discount. Validate with a pilot before relying on it.")
    c = st.columns(3); el = c[0].slider("Demand elasticity", 0.0, 5.0, 1.5, 0.25, key="md_el", help="1.5 means a 20% discount lifts demand 30%."); dmax = c[1].slider("Max discount", 0.1, 0.8, 0.5, 0.05, key="md_max")
    scope = c[2].radio("Batches", ["Manual-review units", "All at-risk batches"], key="md_scope")
    cand = sc[(sc.scored) & (sc.at_risk_units > 0)].copy()
    if scope.startswith("Manual") and len(act):
        mr = act[act.action == "MARKDOWN_REVIEW"]; cand = cand[cand.bid.isin(mr.bid)]
    if cand.empty: st.info("No batches in scope."); return
    cand = cand.sort_values("value_at_risk", ascending=False).head(150)
    rows = []
    for r in cand.itertuples():
        cur, b = _best(r, alpha, el, dmax); base = cur.iloc[0]
        rows.append(dict(store=r.store, sku=r.sku, batch_id=r.batch_id, qty=int(r.qty), days_left=int(r.days_left), price=r.unit_price, best_discount=b.discount,
                         sell_through_now=base.sell_through, sell_through_disc=b.sell_through, revenue_now=base.expected_revenue, revenue_disc=b.expected_revenue, extra_cash=b.expected_revenue-base.expected_revenue))
    tab = pd.DataFrame(rows).sort_values("extra_cash", ascending=False)
    m = st.columns(3); ui.kpi(m[0], "Batches analysed", len(tab)); ui.kpi(m[1], "Extra expected cash", ui.money(tab.extra_cash.sum()), "vs. no discount", "good"); ui.kpi(m[2], "Avg. recommended discount", f"{100*tab.best_discount.mean():.0f}%")
    st.dataframe(tab, hide_index=True, width="stretch", height=280, column_config={"best_discount": st.column_config.NumberColumn("Best discount", format="percent"),
                 "sell_through_now": st.column_config.ProgressColumn("Sell-through now", min_value=0, max_value=1, format="percent"), "sell_through_disc": st.column_config.ProgressColumn("Sell-through w/ discount", min_value=0, max_value=1, format="percent"),
                 "revenue_now": st.column_config.NumberColumn("Revenue now", format="%.0f"), "revenue_disc": st.column_config.NumberColumn("Revenue w/ discount", format="%.0f"), "extra_cash": st.column_config.NumberColumn("Extra cash", format="%.0f"), "price": st.column_config.NumberColumn("Price", format="%.2f")})
    st.download_button("⬇️ Download markdown plan (CSV)", tab.to_csv(index=False), "markdown_plan.csv", key="dl_md")
    st.subheader("Single-batch what-if")
    lab = [f"{r.store} · {r.sku} · {r.batch_id} · {int(r.qty)} units · {int(r.days_left)}d" for r in cand.itertuples()]
    i = st.selectbox("Batch", range(len(cand)), format_func=lambda j: lab[j], key="md_pick"); r = cand.iloc[i]
    cur, b = _best(r, alpha, el, dmax)
    f = go.Figure(); f.add_scatter(x=cur.discount, y=cur.expected_revenue, name="Expected revenue", line=dict(color=ui.GREEN, width=3)); f.add_scatter(x=cur.discount, y=cur.sell_through*cur.expected_revenue.max(), name="Sell-through (scaled)", line=dict(color=ui.AMBER, dash="dot"))
    f.add_vline(x=b.discount, line_dash="dash", line_color=ui.RED, annotation_text=f"best: {b.discount:.0%}"); f.update_layout(title="Expected revenue from this batch vs discount", height=340, xaxis_title="Discount", xaxis_tickformat=".0%", yaxis_title="Expected revenue", legend=dict(orientation="h", y=1.12))
    ui.pc(f, "md_curve")
    st.caption("Revenue is cash recovered on this batch's units; purchase cost is already sunk. Margin impact on *other* sales of the same SKU is not modelled.")
