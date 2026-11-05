import pandas as pd
import streamlit as st
import ui
from core import auth, tasks
from views.task_board import acting_stores


def render():
    S = st.session_state; user = S.user
    ui.hero("Alerts", f"What needs your attention today, {user['display_name']}.")
    ds, res = S.ds, ui.ensure_plan()
    ui.tiles([("✅", "Open Task Board", "Approve, dispatch, receive", "✅ Task Board"), ("⚠️", "Investigate risk", "Batches likely to expire", "⚠️ Risk Explorer"), ("🌍", "Open the map", "Where stock sits", "🌍 Geo Map")], prefix="tile_al")
    universe = ds.stores.store.tolist() if ds is not None else []
    allowed = auth.allowed_stores(user, universe) if ds is not None else user["stores"]
    restricted = user["role"] == "store_staff" or bool(user["stores"])
    df = tasks.list_tasks(stores=(allowed if restricted else None)); mystores = acting_stores(user, universe)
    todo = pd.DataFrame()
    if len(df):
        act = df[df.status.isin(tasks.ACTIVE)]
        todo = act[[bool(tasks.next_actions(r, user, mystores) and tasks.next_actions(r, user, mystores) != ["CANCELLED"]) for r in act.to_dict("records")]]
    c = st.columns(4); ui.kpi(c[0], "Tasks waiting for you", len(todo), "approve / dispatch / receive", "bad" if len(todo) else "")
    soon = exp_b = pd.DataFrame()
    if res is not None:
        sc = res["sc"]; sc = sc[sc.store.isin(allowed)] if restricted else sc
        soon = sc[(sc.days_left <= 14) & (sc.p_unsold >= 0.7)].sort_values("value_at_risk", ascending=False)
        e = ds.expired.copy(); e["store"] = ds.stores.store.values[e.s]; e["sku"] = ds.skus.sku.values[e.k]; e["value"] = e.qty*ds.cost[e.k.values]; exp_b = e[e.store.isin(allowed)] if restricted else e
        ui.kpi(c[1], "Expiring ≤14d & likely unsold", len(soon), ui.money(soon.stock_value.sum()) if len(soon) else "", "bad" if len(soon) else ""); ui.kpi(c[2], "Already expired", len(exp_b), ui.money(exp_b.value.sum()) if len(exp_b) else "", "bad" if len(exp_b) else "")
    else: st.info("No analysis available yet. An analyst needs to run and **publish** one from the Data Hub.")
    ui.kpi(c[3], "Open tasks (your scope)", int(df.status.isin(tasks.ACTIVE).sum()) if len(df) else 0)
    if len(todo):
        st.subheader("✋ Waiting for you")
        st.dataframe(todo[["id", "status", "kind", "store_from", "store_to", "sku", "units", "expiry_date", "created_by"]], hide_index=True, width="stretch"); st.caption("Open **✅ Task Board** to act on them.")
    if len(exp_b): st.subheader("⛔ Pull from shelves now (expired)"); st.dataframe(exp_b[["store", "sku", "batch_id", "expiry_date", "qty", "value"]], hide_index=True, width="stretch")
    if len(soon):
        st.subheader("⏰ Expiring within 14 days and very likely to go unsold")
        st.dataframe(soon[["store", "sku", "batch_id", "qty", "days_left", "p_unsold", "value_at_risk"]], hide_index=True, width="stretch", column_config={"p_unsold": st.column_config.ProgressColumn("P(expire)", min_value=0, max_value=1, format="percent")})
    if not len(todo) and not len(soon) and not len(exp_b) and res is not None: st.success("Nothing urgent. 🎉")
    digest = "\n".join([f"Alerts for {user['display_name']}", f"Tasks waiting: {len(todo)}", f"Expiring <=14d & likely unsold: {len(soon)}", f"Already expired: {len(exp_b)}"])
    st.download_button("⬇️ Download digest (text)", digest, "alerts_digest.txt", key="al_dl")
