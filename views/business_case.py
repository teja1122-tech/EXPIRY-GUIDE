import os
import numpy as np, pandas as pd, plotly.express as px, plotly.graph_objects as go
import streamlit as st
import ui

PRE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "precomputed")


def render():
    ui.hero("Business Case", "Translate the engine's simulated performance into a projected return for your chain, then inspect the evidence behind it.")
    rob = pd.read_csv(f"{PRE}/seed_robustness.csv"); rob["avoided"] = rob.baseline_writeoff - rob.system_writeoff; rob["capture"] = rob.net_gain/rob.avoided; rob["reduction"] = rob.writeoff_reduction_pct/100
    t1, t2 = st.tabs(["💰 ROI calculator", "🧪 Simulation evidence"])
    with t1:
        cur = st.session_state.currency
        c = st.columns(3)
        cogs = c[0].number_input(f"Annual COGS ({cur})", 1e5, 1e11, 5e7, 1e6, format="%.0f", key="bc_cogs"); loss = c[1].slider("Current expiry loss (% of COGS)", 0.2, 6.0, 1.5, 0.1, key="bc_loss")
        stores = c[2].number_input("Number of stores (info)", 1, 5000, 10, key="bc_st")
        c = st.columns(3); impl = c[0].number_input(f"One-off implementation cost ({cur})", 0.0, 1e9, 500000.0, 50000.0, format="%.0f", key="bc_impl"); run = c[1].number_input(f"Annual running cost ({cur})", 0.0, 1e9, 150000.0, 10000.0, format="%.0f", key="bc_run")
        yrs = c[2].slider("Horizon (years)", 1, 5, 3, key="bc_yrs")
        loss_amt = cogs*loss/100
        scen = {"Low (worst of 5 simulated worlds)": rob.loc[(rob.reduction*rob.capture).idxmin()], "Median": rob.iloc[(rob.reduction*rob.capture - (rob.reduction*rob.capture).median()).abs().argmin()], "High (best simulated world)": rob.loc[(rob.reduction*rob.capture).idxmax()]}
        rows, fig = [], go.Figure()
        for (n, r), col in zip(scen.items(), [ui.RED, ui.AMBER, ui.GREEN]):
            annual = loss_amt*r.reduction*r.capture; cum = [-impl + (annual-run)*y for y in np.linspace(0, yrs, yrs*12+1)]
            pb = impl/max(annual-run, 1e-9)*12 if annual > run else np.inf
            rows.append(dict(scenario=n, write_off_reduction=r.reduction, net_capture=r.capture, annual_net_benefit=annual, payback_months=pb, cumulative=cum[-1]))
            fig.add_scatter(x=np.linspace(0, yrs, yrs*12+1), y=cum, name=n, line=dict(color=col, width=3))
        fig.add_hline(y=0, line_color="#444"); fig.update_layout(title="Cumulative net cash position", height=360, xaxis_title="Years", legend=dict(orientation="h", y=1.15))
        m = st.columns(3); mid = rows[1]
        ui.kpi(m[0], "Current expiry loss / yr", ui.money(loss_amt), f"{stores} stores"); ui.kpi(m[1], "Median net benefit / yr", ui.money(mid["annual_net_benefit"]), "after return & transfer costs", "good")
        ui.kpi(m[2], "Median payback", "never" if np.isinf(mid["payback_months"]) else f"{mid['payback_months']:.1f} months", f"{yrs}-yr net {ui.money(mid['cumulative'])}")
        ui.pc(fig, "bc_cum")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={"write_off_reduction": st.column_config.NumberColumn(format="percent"), "net_capture": st.column_config.NumberColumn("Net capture", format="percent"),
                     "annual_net_benefit": st.column_config.NumberColumn(format="%.0f"), "payback_months": st.column_config.NumberColumn(format="%.1f"), "cumulative": st.column_config.NumberColumn(f"{yrs}-yr net", format="%.0f")})
        st.caption("Annual benefit = expiry loss × write-off reduction × net capture. *Net capture* = share of avoided write-offs that remains after return losses and transfer costs (simulation: 21-50%). Inputs come from 5 simulated chains - replace with your own pilot results.")
    with t2:
        kp = pd.read_csv(f"{PRE}/replay_kpis.csv", index_col=0); b, s = kp["Baseline (no system)"], kp["System (full)"]
        m = st.columns(4); ui.kpi(m[0], "Write-offs (180d)", ui.money(s.writeoff_cost), f"{100*(s.writeoff_cost/b.writeoff_cost-1):.0f}% vs baseline", "good"); ui.kpi(m[1], "Net contribution gain", ui.money(s.net_contribution-b.net_contribution), f"{100*(s.net_contribution/b.net_contribution-1):.1f}%", "good")
        ui.kpi(m[2], "Fill rate", f"{100*s.fill_rate:.2f}%", f"{100*(s.fill_rate-b.fill_rate):+.2f} pts"); ui.kpi(m[3], "Closing stock", ui.money(s.closing_stock_cost), f"{100*(s.closing_stock_cost/b.closing_stock_cost-1):.1f}%")
        cum = pd.read_csv(f"{PRE}/cumulative_writeoff_cost.csv", index_col=0)[["Baseline (no system)", "System (full)"]]
        f = px.line(cum, title="Cumulative write-off cost: same demand, same opening stock", color_discrete_map={"Baseline (no system)": ui.RED, "System (full)": ui.GREEN}); f.update_layout(height=340, xaxis_title=None, yaxis_title=None, legend_title=None); ui.pc(f, "bc_cumwo")
        a, c = st.columns(2)
        ab = pd.DataFrame({"variant": [v for v in kp.columns if v != "Baseline (no system)"], "net_gain": [kp[v].net_contribution - b.net_contribution for v in kp.columns if v != "Baseline (no system)"]})
        f = px.bar(ab, x="variant", y="net_gain", title="Which lever matters? (ablation - levers are complementary)", color_discrete_sequence=[ui.GREEN]); f.update_layout(height=320, xaxis_title=None, yaxis_title=None)
        with a: ui.pc(f, "bc_abl")
        f = px.bar(rob, x=rob.seed.astype(str), y="net_gain", title="Net gain across 5 independent simulated chains", color_discrete_sequence=[ui.TEAL]); f.update_layout(height=320, xaxis_title="Simulation seed", yaxis_title=None)
        with c: ui.pc(f, "bc_rob")
        st.info("All evidence is from simulated chains. Net gain was positive in all five (0.4%-3.4% of baseline contribution), but real chains will differ - run a pilot.")
