import pandas as pd, plotly.express as px
import streamlit as st
import ui
from core import auth, tasks

ICON = {"PROPOSED": "🟡", "APPROVED": "🟢", "DISPATCHED": "🚚", "COMPLETED": "✅", "REJECTED": "⛔", "CANCELLED": "⚪"}


def acting_stores(user, universe):
    """Stores this user may act for in the workflow. Analysts are read-only (they can still cancel their own proposals)."""
    if user["role"] == "analyst": return []
    return auth.allowed_stores(user, universe)


def render():
    S = st.session_state; user = S.user
    ui.hero("Task Board", "Every approved move becomes a tracked task: propose → approve → dispatch → receive, with an audit trail.")
    allt = tasks.list_tasks()
    universe = S.ds.stores.store.tolist() if S.ds is not None else (sorted(set(allt.store_from) | set(allt.store_to) - {""}) if len(allt) else [])
    mystores = acting_stores(user, universe); vis = auth.allowed_stores(user, universe) if (user["role"] == "store_staff" or user["stores"]) else None
    df = tasks.list_tasks(stores=vis)
    if df.empty: st.info("No tasks yet. Create them from **🚚 Action Center** (send approved actions) or **🔀 Transfer Planner**."); return
    c = st.columns(6)
    for col, s in zip(c, tasks.STATUSES): ui.kpi(col, f"{ICON[s]} {s.title()}", int((df.status == s).sum()))
    f1, f2, f3 = st.columns([2, 2, 1]); stt = f1.multiselect("Status", tasks.STATUSES, default=tasks.ACTIVE, key="tb_status"); kd = f2.multiselect("Type", sorted(df.kind.unique()), key="tb_kind"); onlyme = f3.checkbox("Created by me", key="tb_me")
    v = df[df.status.isin(stt)] if stt else df
    if kd: v = v[v.kind.isin(kd)]
    if onlyme: v = v[v.created_by == user["username"]]
    st.dataframe(v[["id", "status", "kind", "store_from", "store_to", "sku", "batch_id", "units", "expiry_date", "est_gain", "created_by", "created_at"]], hide_index=True, width="stretch", height=280, column_config={"est_gain": st.column_config.NumberColumn("Est. gain", format="%.0f")})
    st.download_button("⬇️ Export tasks (CSV)", v.to_csv(index=False), "tasks.csv", key="tb_dl")
    if v.empty: return
    st.subheader("Task detail")
    tid = st.selectbox("Task", v.id.tolist(), format_func=lambda i: f"#{i} · {v.set_index('id').loc[i, 'status']} · {v.set_index('id').loc[i, 'kind']} · {v.set_index('id').loc[i, 'store_from']} → {v.set_index('id').loc[i, 'store_to'] or '—'} · {v.set_index('id').loc[i, 'sku']}", key="tb_pick")
    t = v[v.id == tid].iloc[0].to_dict(); a, b = st.columns([1, 1])
    with a:
        st.markdown(f"**{ICON[t['status']]} {t['status']}** · {tasks.KIND_LABEL.get(t['kind'], t['kind'])}")
        st.write(f"**{t['units']} units** of **{t['sku']}** (batch {t['batch_id']}, expires {t['expiry_date']})")
        st.write(f"From **{t['store_from']}**" + (f" → **{t['store_to']}**" if t["store_to"] else ""))
        st.caption(f"Created by {t['created_by']} on {t['created_at']} · est. gain {ui.money(t['est_gain'])}" + (f" · note: {t['note']}" if t["note"] else ""))
    with b:
        st.markdown("**History**"); ev = tasks.task_events(tid)
        for e in ev.itertuples(): st.markdown(f"- `{e.ts}` **{e.username}** · {e.event}" + (f" — _{e.comment}_" if e.comment else ""))
    comment = st.text_input("Comment (optional)", key="tb_comment"); nxt = tasks.next_actions(t, user, mystores)
    if nxt:
        cols = st.columns(len(nxt) + 1)
        for col, s in zip(cols, nxt):
            lab = {"APPROVED": "✅ Approve", "REJECTED": "⛔ Reject", "CANCELLED": "Cancel task", "DISPATCHED": "🚚 Mark dispatched", "COMPLETED": "✅ Mark completed / received"}[s]
            if col.button(lab, key=f"tb_act_{s}", type="primary" if s in ("APPROVED", "DISPATCHED", "COMPLETED") else "secondary"):
                try:
                    tasks.update_status(tid, s, user, mystores, comment); ui.queue_toast(f"Task #{tid} → {s.title()}", "🎉" if s == "COMPLETED" else "✅")
                    if s == "COMPLETED": st.session_state["_balloons"] = True
                    st.rerun()
                except (PermissionError, ValueError) as e: st.error(str(e))
    else: st.caption("No actions available to you on this task right now.")
    if st.button("💬 Add comment only", key="tb_addc", disabled=not comment.strip()): tasks.add_comment(tid, user, comment); st.rerun()
