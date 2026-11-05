import os, json
import pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui

PRE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "precomputed")


def render():
    ds, fi, res = ui.need_analysis()
    ui.hero("Model Health", "How much to trust the numbers: data quality, forecast accuracy, and whether risk scores have come true.")
    c = st.columns(4); ui.kpi(c[0], "Data quality", f"{ds.quality:.0f}/100", "; ".join(ds.quality_notes) or "no issues"); ui.kpi(c[1], "Forecast method", fi["method"]); ui.kpi(c[2], "Over-dispersion α", f"{fi['alpha']:.3f}", "demand variability"); ui.kpi(c[3], "History", f"{ds.T} days")
    for n in fi["notes"]: st.warning(n)
    st.subheader("Forecast accuracy on weeks the model had not seen")
    bt = fi.get("backtest")
    if bt is not None:
        f = px.bar(bt, x="model", y=100*bt.WAPE_28d, title="28-day WAPE % (lower is better)", color="model", color_discrete_sequence=[ui.GREEN, ui.GREY, "#CBD3D0"]); f.update_layout(height=320, showlegend=False, xaxis_title=None, yaxis_title="WAPE %"); ui.pc(f, "mh_bt")
        st.dataframe(bt.style.format({"WAPE_28d": "{:.1%}", "bias": "{:+.1%}", "daily_poisson_deviance": "{:.3f}"}), hide_index=True, width="stretch")
        gbm = bt.iloc[0]; naive = bt.iloc[1:].WAPE_28d.min()
        (st.success if gbm.WAPE_28d < naive else st.warning)(f"Model error {gbm.WAPE_28d:.1%} vs best naive baseline {naive:.1%}." + (" The ML model is adding value." if gbm.WAPE_28d < naive else " The ML model is NOT beating a simple average on your data - treat risk scores with extra caution."))
    else: st.info("Backtest needs 18+ months of history. Upload a longer sales history to unlock accuracy reporting.")
    st.subheader("Do risk scores come true? (reference check on simulated history)")
    cal = pd.read_csv(f"{PRE}/risk_calibration.csv"); sm = json.load(open(f"{PRE}/risk_calibration_summary.json"))
    f = go.Figure(); f.add_scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(dash="dash", color="#999"), name="Perfect calibration")
    f.add_scatter(x=cal.predicted, y=cal.actual, mode="markers+lines", marker=dict(size=cal.batches/12+6, color=ui.GREEN), name="Observed"); f.update_layout(title="Predicted vs actual share of batches that expired", height=340, xaxis_title="Predicted P(expire)", yaxis_title="Actual", legend=dict(orientation="h", y=1.15)); ui.pc(f, "mh_cal")
    st.caption(f"Reference run: AUC {sm['auc']:.3f} on {sm['n_batches']:,} batches; expected {sm['exp_units']:,.0f} unsold units vs {sm['actual_units']:,.0f} actual (scores ~14% conservative). On your own data, re-check after a few cycles: compare past 'Run History' risk scores with what really expired.")
    with st.expander("Limitations to keep in mind"):
        st.markdown("- Sales are treated as demand; stock-outs hide true demand, so fast sellers can be under-forecast.\n- Promotions, new launches and prescription-pattern shifts are not modelled.\n- Return terms, shipping costs and discount response are assumptions you set.\n- Inter-store transfers may be restricted by drug-licence or cold-chain rules - confirm with compliance.\n- Estimated gains are lower bounds per unit, not guarantees.")
