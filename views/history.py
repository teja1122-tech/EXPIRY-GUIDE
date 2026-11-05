import pandas as pd, plotly.graph_objects as go
import streamlit as st
import ui
from core import store, report


def render():
    S = st.session_state
    ui.hero("Run History & Reports", "Every saved analysis is kept, so each new upload shows what improved, what got worse and what is newly at risk.")
    if S.res is not None:
        ds, fi, res = S.ds, S.fi, S.res
        st.subheader("Reports for the current analysis")
        c = st.columns(4)
        c[0].download_button("📊 Excel report", report.excel_report(ds, fi, res, S.currency), f"expiry_report_{ds.as_of.date()}.xlsx", key="dl_xlsx", help="Summary, risk scores, action plan, per-store pick-lists, expired stock, weekly forecast")
        c[1].download_button("📄 HTML summary", report.html_summary(ds, fi, res, S.currency), f"expiry_summary_{ds.as_of.date()}.html", mime="text/html", key="dl_html")
        if c[2].button("💾 Save to history", key="hist_save"): S.last_saved = store.save_run(f"as of {ds.as_of.date()}", ds, fi, res); st.success(f"Saved ({S.last_saved}).")
    runs = store.list_runs()
    if runs.empty: st.info("No saved runs yet. Run an analysis with 'Save to Run History' ticked."); return
    runs = runs.sort_values("as_of").reset_index(drop=True)
    st.subheader("Saved runs")
    st.dataframe(runs[["run_id", "label", "as_of", "history_days", "stores", "skus", "quality", "stock_value", "value_at_risk", "high_risk_batches", "est_net_gain"]], hide_index=True, width="stretch",
                 column_config={"stock_value": st.column_config.NumberColumn(format="%.0f"), "value_at_risk": st.column_config.NumberColumn("Expected loss", format="%.0f"), "est_net_gain": st.column_config.NumberColumn(format="%.0f"), "quality": st.column_config.NumberColumn(format="%.0f")})
    if len(runs) >= 2:
        f = go.Figure(); f.add_scatter(x=runs.as_of, y=runs.value_at_risk, name="Expected expiry loss", mode="lines+markers", line=dict(color=ui.RED, width=3))
        f.add_scatter(x=runs.as_of, y=runs.stock_value, name="Stock value", mode="lines+markers", line=dict(color=ui.GREEN, width=3), yaxis="y2")
        f.update_layout(title="Trend across uploads", height=340, yaxis=dict(title="Expected loss"), yaxis2=dict(title="Stock value", overlaying="y", side="right", showgrid=False), legend=dict(orientation="h", y=1.15)); ui.pc(f, "hist_trend")
        st.subheader("What changed between two uploads?")
        ids = runs.run_id.tolist(); fmt = lambda i: f"{runs.set_index('run_id').loc[i, 'as_of']} · {i}"
        c = st.columns(2); old = c[0].selectbox("Earlier run", ids, index=len(ids)-2, format_func=fmt, key="h_old"); new = c[1].selectbox("Later run", ids, index=len(ids)-1, format_func=fmt, key="h_new")
        a, b = store.load_risk(old), store.load_risk(new)
        if len(a) and len(b) and old != new:
            key = ["store", "sku", "batch_id"]; ha = a[a.p_unsold >= 0.7]; hb = b[b.p_unsold >= 0.7]
            cleared = ha.merge(b[key], on=key, how="left", indicator=True).query("_merge == 'left_only'"); persist = ha.merge(hb[key], on=key, how="inner"); fresh = hb.merge(ha[key], on=key, how="left", indicator=True).query("_merge == 'left_only'")
            m = st.columns(3); ui.kpi(m[0], "High-risk batches cleared", len(cleared), f"{ui.money(cleared.stock_value.sum())} no longer on shelf (sold / moved / returned / expired)", "good")
            ui.kpi(m[1], "Still high-risk", len(persist), f"{ui.money(persist.value_at_risk.sum())} expected loss", "bad"); ui.kpi(m[2], "Newly high-risk", len(fresh), f"{ui.money(fresh.value_at_risk.sum())} expected loss", "bad" if len(fresh) else "")
            t = st.tabs(["Newly high-risk", "Still high-risk", "Cleared"])
            cols = ["store", "sku", "category", "batch_id", "qty", "days_left", "p_unsold", "value_at_risk"]
            for tb, d in zip(t, [fresh, persist, cleared]): tb.dataframe(d[cols].sort_values("value_at_risk", ascending=False), hide_index=True, width="stretch")
    with st.expander("Manage saved runs"):
        d = st.selectbox("Delete a run", runs.run_id.tolist(), key="h_del")
        if st.button("🗑️ Delete", key="h_delbtn"): store.delete_run(d); st.rerun()
