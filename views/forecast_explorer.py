import numpy as np, pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
from scipy.stats import nbinom
import ui
from core import auth
from views import anim


def _weekly(ds, s, k, weeks):
    ser = pd.Series(ds.S[:, s, k], index=ds.start + pd.to_timedelta(np.arange(ds.T), "D"))
    w = ser.iloc[-weeks*7:]; return w.groupby(np.arange(len(w))//7).sum(), w.index[::7]


def render():
    ds, fi, res = ui.need_analysis(); fc, alpha = fi["fc"], fi["alpha"]
    ui.hero("Forecast Explorer", f"Daily demand forecasts per store × SKU for the next 120 days · method: {fi['method']}")
    _allowed = auth.allowed_stores(st.session_state.user, ds.stores.store.tolist())
    if not _allowed: st.warning("No stores are assigned to your account."); return
    foc = ui.get_focus(); sku_rows = [r for r in ds.skus.itertuples() if (not foc["category"] or r.category == foc["category"])] or list(ds.skus.itertuples())
    sku_opts = [f"{r.sku} · {r.category}" for r in sku_rows]
    ui.apply_focus("forecast", {"fe_store": lambda f: f["store"] if f["store"] in _allowed else ui.SKIP})
    if st.session_state.get("fe_sku") not in sku_opts: st.session_state.pop("fe_sku", None)
    c = st.columns([1, 2, 1])
    store = c[0].selectbox("Store", _allowed, key="fe_store")
    sku = c[1].selectbox("SKU", sku_opts, key="fe_sku").split(" · ")[0]
    weeks = c[2].slider("History (weeks)", 8, 52, 26, key="fe_weeks")
    if foc["category"]: st.caption(f"SKU list narrowed to the focused category: **{foc['category']}**")
    s, k = ds.stores.store.tolist().index(store), ds.skus.sku.tolist().index(sku)
    hist, hidx = _weekly(ds, s, k, min(weeks, ds.T//7))
    nfw = 17; mu_w = np.array([fc[s, k, i*7:(i+1)*7].sum() for i in range(nfw)])
    r = 1/alpha; p = r/(r+mu_w); lo, hi = nbinom.ppf(0.1, r, p), nbinom.ppf(0.9, r, p)
    fdates = ds.as_of + pd.to_timedelta(np.arange(nfw)*7, "D")
    fig = go.Figure()
    fig.add_bar(x=hidx[:len(hist)], y=hist.values, name="History (weekly units)", marker_color=ui.GREY)
    fig.add_bar(x=fdates, y=mu_w, name="Forecast (expected)", marker_color=ui.GREEN, error_y=dict(type="data", symmetric=False, array=hi-mu_w, arrayminus=mu_w-lo, color="#555"))
    fig.update_layout(title=f"{store} · {sku}: weekly units, forecast with 80% interval · press ▶ to watch the forecast unfold", height=400, barmode="group", legend=dict(orientation="h", y=1.1), xaxis_title=None, yaxis_title="Units / week")
    anim.add_forecast_reveal(fig, fdates, mu_w, lo, hi, trace_index=1)
    ui.pc(fig, "fe_main")
    stock = int(ds.batches[(ds.batches.s == s) & (ds.batches.k == k)].qty.sum()); f30, f90 = fc[s, k, :30].sum(), fc[s, k, :90].sum(); daily = max(fc[s, k, :30].mean(), 1e-6)
    m = st.columns(4); ui.kpi(m[0], "Forecast next 30 days", f"{f30:,.1f} units"); ui.kpi(m[1], "Forecast next 90 days", f"{f90:,.1f} units")
    ui.kpi(m[2], "Stock on hand", f"{stock} units"); ui.kpi(m[3], "Days of cover", f"{stock/daily:,.0f} days", "at forecast pace", "bad" if stock/daily > 120 else "")
    a, b = st.columns(2)
    comp = pd.DataFrame({"store": ds.stores.store, "Forecast 90d": fc[:, k, :90].sum(1),
                         "On hand": [ds.batches[(ds.batches.s == i) & (ds.batches.k == k)].qty.sum() for i in range(ds.N)]}).melt("store", var_name="metric", value_name="units")
    comp = comp[comp.store.isin(_allowed)] if st.session_state.user["role"] != "admin" and st.session_state.user["stores"] else comp
    kv = foc["version"]; ckey = f"fe_comp_{kv}_{sku}"
    if ui.sync_selection(ckey, lambda pts: (pts[0].get("x") if pts else None), lambda v_: ui.set_focus(store=v_) if v_ in _allowed else False): st.rerun()
    f = px.bar(comp, x="store", y="units", color="metric", barmode="group", title=f"{sku}: stock vs 90-day demand by store · click a store to focus it everywhere", color_discrete_map={"Forecast 90d": ui.GREEN, "On hand": ui.AMBER})
    f.update_layout(height=340, xaxis_title=None, yaxis_title=None, legend_title=None, clickmode="event+select")
    with a: ui.pc(f, ckey, select=True)
    with b:
        if ds.T >= 365:
            d = pd.Series(ds.S[:, :, k].sum(1), index=ds.start + pd.to_timedelta(np.arange(ds.T), "D")); mo = d.groupby(d.index.month).mean()
            f = px.line(x=mo.index, y=mo.values, markers=True, title=f"{sku}: average daily units by calendar month (all stores)"); f.update_traces(line_color=ui.GREEN)
            f.update_layout(height=340, xaxis_title="Month", yaxis_title="Units/day"); ui.pc(f, "fe_seas")
        else: st.info("Seasonality profile appears once you upload 12+ months of history.")
    st.button(f"🔗 Use {store} · {ds.skus.category.iloc[k]} as the global focus", key="fe_focus", on_click=lambda s_=store, c_=ds.skus.category.iloc[k]: ui.set_focus(store=s_, category=c_))
