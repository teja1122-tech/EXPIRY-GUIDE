import os
import numpy as np, pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui
from core.io import build_dataset, read_table, template_frames, DataError
from core.pipeline import forecast_stage
from core import store, auth, geo, publish

DEMOS = {"Demo A - as of 19 Jun 2024 (10 stores, 40 SKUs)": "demo_a_jun2024", "Demo B - 30 days later (19 Jul 2024)": "demo_b_jul2024"}
BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample_data")
FILES = [("sales", "Sales history", "date, store, sku, units - daily sales. 12+ months recommended."),
         ("inventory", "Current inventory by batch", "store, sku, batch_id, expiry_date, quantity - today's stock."),
         ("skus", "SKU master", "sku, unit_cost (required); category, unit_price (optional)."),
         ("stores", "Store master (optional)", "store, lat, lon - enables distance-based shipping costs.")]


def _load_demo(folder):
    d = f"{BASE}/{folder}"
    return {k: read_table(f"{d}/{k}.csv.gz" if k == "sales" else f"{d}/{k}.csv") for k, _, _ in FILES}


def _build(tabs, as_of):
    S = st.session_state
    try:
        ds = build_dataset(tabs["sales"], tabs["inventory"], tabs["skus"], tabs.get("stores"), as_of)
    except DataError as e:
        S.build_error = e.msgs; return
    geo.apply_overrides(ds)                                   # re-apply saved store locations
    S.build_error = None; S.ds = ds; S.fi = None; S.res = None; S.plan_key = None
    auth.audit(S.user["username"], "dataset_built", f"as of {ds.as_of.date()}, {ds.N} stores, {ds.K} SKUs")


def render():
    S = st.session_state
    ui.hero("Data Hub", "Bring your own data every cycle - upload, validate, and run a fresh expiry-risk analysis in one click.")
    pm = publish.published_meta()
    if pm:
        pc1, pc2 = st.columns([3, 1]); pc1.info(f"📢 Latest published analysis: as of **{pm['as_of']}**, published by **{pm['published_by']}** on {pm['published_at']}.")
        if pc2.button("Load published analysis", key="btn_loadpub"):
            snap = publish.load_published(); S.ds, S.fi = snap["ds"], snap["fi"]; S.fc_cache[S.ds.fingerprint] = S.fi; S.plan_key = None; ui.ensure_plan(); st.rerun()
    t_up, t_demo, t_tpl = st.tabs(["📤 Upload your data", "🧪 Try a demo dataset", "📋 Templates & format guide"])
    with t_up:
        c = st.columns(2); tabs = {}
        for i, (k, title, hint) in enumerate(FILES):
            with c[i % 2]:
                f = st.file_uploader(title, type=["csv", "xlsx", "xls", "gz"], key=f"up_{k}", help=hint); st.caption(hint)
                if f is not None:
                    try: tabs[k] = read_table(f)
                    except Exception as e: st.error(f"Could not read {title}: {e}")
        use_asof = st.checkbox("Set the analysis date manually (default: day after the last sale)")
        as_of = st.date_input("Analysis date", value=pd.Timestamp.today()) if use_asof else None
        ready = all(k in tabs for k in ("sales", "inventory", "skus"))
        if st.button("✅ Validate & build dataset", type="primary", disabled=not ready, key="btn_build_up"): _build(tabs, as_of)
        if not ready: st.caption("Upload at least sales, inventory and SKU master to continue.")
    with t_demo:
        st.write("Pre-built datasets in exactly the upload format. Load **A**, run the analysis, then load **B** (a month later) and compare under *Run History*.")
        name = st.selectbox("Demo dataset", list(DEMOS), key="demo_pick")
        if st.button("Load demo dataset", key="btn_demo"): _build(_load_demo(DEMOS[name]), None)
    with t_tpl:
        st.write("Column names are matched flexibly (e.g. `qty`, `quantity`, `units` all work). Download a template to see the layout:")
        cols = st.columns(4)
        for col, (k, df) in zip(cols, template_frames().items()):
            col.download_button(f"{k}.csv", df.to_csv(index=False), f"template_{k}.csv", key=f"tpl_{k}")
        with st.expander("What each file needs"):
            for k, title, hint in FILES: st.markdown(f"**{title}** - {hint}")
            st.markdown("Missing sales days are treated as zero. Stores/SKUs not in the SKU master are ignored with a warning.")
    if S.get("build_error"):
        for m in S.build_error: st.error(m)
    ds = S.ds
    if ds is None: return
    st.divider(); st.subheader("Dataset check")
    c = st.columns([1.1, 1, 1, 1, 1, 1])
    fig = go.Figure(go.Indicator(mode="gauge+number", value=ds.quality, title={"text": "Data quality"},
                                 gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=ui.GREEN), steps=[dict(range=[0, 60], color="#F3D9D4"), dict(range=[60, 85], color="#F7E9D2"), dict(range=[85, 100], color="#DCEFE9")])))
    fig.update_layout(height=170, margin=dict(l=10, r=10, t=30, b=0)); c[0].plotly_chart(fig, width="stretch", key="gauge_q")
    ui.kpi(c[1], "History", f"{ds.T} days", f"{ds.start.date()} → {ds.as_of.date()}"); ui.kpi(c[2], "Stores", ds.N); ui.kpi(c[3], "SKUs", ds.K)
    ui.kpi(c[4], "Live batches", len(ds.batches), f"{len(ds.expired)} already expired"); ui.kpi(c[5], "Stock value", ui.money(float((ds.batches.qty*ds.cost[ds.batches.k.values]).sum())))
    for i in ds.issues:
        {"warning": st.warning, "info": st.info}.get(i["level"], st.info)(i["message"])
    if ds.quality_notes: st.caption("Quality score reduced by: " + "; ".join(ds.quality_notes))
    g1, g2 = st.columns(2)
    w = pd.Series(ds.S.sum((1, 2)), index=ds.start + pd.to_timedelta(np.arange(ds.T), "D")).resample("W").sum()
    g1.plotly_chart(px.area(w, title="Weekly units sold (all stores)").update_traces(line_color=ui.GREEN).update_layout(showlegend=False, height=300, margin=dict(l=10, r=10, t=45, b=10), yaxis_title=None, xaxis_title=None), width="stretch", key="dh_sales")
    lt = ds.batches.assign(days=ds.batches.exp - ds.T, value=ds.batches.qty*ds.cost[ds.batches.k.values])
    g2.plotly_chart(px.histogram(lt, x="days", y="value", nbins=30, title="Stock value by days to expiry", color_discrete_sequence=[ui.TEAL]).update_layout(height=300, margin=dict(l=10, r=10, t=45, b=10), yaxis_title=None, xaxis_title="Days to expiry"), width="stretch", key="dh_exp")
    st.divider(); st.subheader("Run the analysis")
    c1, c2 = st.columns([2, 1])
    c1.write("Forecast demand → score every batch → optimise transfers & returns. Takes 15–30 s on first run; changing planning settings later is instant.")
    save = c2.checkbox("Save to Run History", value=True, key="save_hist")
    if st.button("🚀 Run analysis", type="primary", key="btn_run"):
        bar = st.progress(0.0, text="Starting...")
        if ds.fingerprint in S.fc_cache: S.fi = S.fc_cache[ds.fingerprint]
        else:
            S.fi = forecast_stage(ds, lambda f, m: bar.progress(min(f, 0.99), text=m)); S.fc_cache[ds.fingerprint] = S.fi
        S.plan_key = None; res = ui.ensure_plan(); bar.progress(1.0, text="Done")
        if save: S.last_saved = store.save_run(f"as of {ds.as_of.date()}", ds, S.fi, res, S.user["username"])
        auth.audit(S.user["username"], "analysis_run", f"as of {ds.as_of.date()}, method {S.fi['method']}")
        st.toast("Analysis complete", icon="🚀"); st.success(f"Analysis complete using **{S.fi['method']}**.")
        for n in S.fi["notes"]: st.warning(n)

    if S.res is not None:
        st.divider(); st.subheader("Next step")
        ui.tiles([("📊", "Open Command Center", "Your risk overview", "📊 Command Center"), ("⚠️", "Investigate risk", "Filter and lasso batches", "⚠️ Risk Explorer"), ("🚚", "Decide actions", "Approve the plan", "🚚 Action Center"), ("🌍", "Open the map", "Where the risk is", "🌍 Geo Map")], prefix="tile_dh")
        st.subheader("Share with your team")
        st.write("Publish this analysis so every user - including store staff, who cannot upload data - sees the same numbers after signing in.")
        if st.button("📢 Publish this analysis to all users", key="btn_publish"):
            meta = publish.publish(S.ds, S.fi, S.user); st.toast("Analysis published to all users", icon="📢"); st.success(f"Published (as of {meta['as_of']}).")
