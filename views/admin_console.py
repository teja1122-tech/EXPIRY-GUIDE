import streamlit as st
import ui
from core import auth
from core.publish import published_meta


def render():
    S = st.session_state; me = S.user
    ui.hero("Admin Console", "Manage users and roles, restrict people to their stores, and review the audit trail.")
    t1, t2, t3 = st.tabs(["👥 Users", "📜 Audit log", "⚙️ System"])
    universe = S.ds.stores.store.tolist() if S.ds is not None else []
    with t1:
        users = auth.list_users()
        st.dataframe(users[["username", "display_name", "role", "stores", "active", "last_login", "created_at"]], hide_index=True, width="stretch")
        st.markdown("**Roles** - *Administrator*: everything. *Manager*: all analysis, approves tasks. *Analyst*: uploads data, runs analyses, publishes, proposes tasks (read-only on approvals). *Store staff*: sees only assigned stores; dispatches/receives their stock.")
        a, b = st.columns(2)
        with a:
            st.subheader("Add a user")
            with st.form("add_user"):
                u = st.text_input("Username", key="au_user"); n = st.text_input("Display name", key="au_name"); e = st.text_input("Email (optional)", key="au_email")
                r = st.selectbox("Role", auth.ROLES, format_func=lambda x: auth.ROLE_LABEL[x], index=2, key="au_role")
                stl = st.multiselect("Restrict to stores (empty = all; required for store staff)", universe, key="au_stores") if universe else [x.strip() for x in st.text_input("Stores (comma-separated, optional)", key="au_stores_txt").split(",") if x.strip()]
                pw = st.text_input("Temporary password", type="password", key="au_pw", help="User must change it at first sign-in.")
                ok = st.form_submit_button("Create user", type="primary", key="au_submit")
            if ok:
                try: auth.create_user(u, pw, r, n, e, stl, must_change=True, actor=me["username"]); st.success(f"Created {u.strip().lower()}. They must change the password at first sign-in."); st.rerun()
                except ValueError as ex: st.error(str(ex))
        with b:
            st.subheader("Edit a user")
            sel = st.selectbox("User", users.username.tolist(), key="eu_pick"); cur = users[users.username == sel].iloc[0]
            with st.form("edit_user"):
                r = st.selectbox("Role", auth.ROLES, index=auth.ROLES.index(cur.role), format_func=lambda x: auth.ROLE_LABEL[x], key=f"eu_role_{sel}")
                stl = st.multiselect("Stores (empty = all)", sorted(set(universe) | set(cur.stores)), default=list(cur.stores), key=f"eu_stores_{sel}")
                act = st.checkbox("Active", bool(cur.active), key=f"eu_active_{sel}"); np_ = st.text_input("Reset password (leave blank to keep)", type="password", key=f"eu_pw_{sel}")
                ok = st.form_submit_button("Save changes", key="eu_submit")
            if ok:
                admins = users[(users.role == "admin") & (users.active)]
                if sel == me["username"] and (r != "admin" or not act): st.error("You cannot remove your own administrator access or deactivate yourself.")
                elif cur.role == "admin" and len(admins) <= 1 and (r != "admin" or not act): st.error("At least one active administrator is required.")
                else:
                    try:
                        auth.update_user(sel, actor=me["username"], role=r, stores=stl, active=act)
                        if np_: auth.set_password(sel, np_, must_change=True, actor=me["username"])
                        st.success("Saved."); st.rerun()
                    except ValueError as ex: st.error(str(ex))
    with t2:
        log = auth.list_audit(2000); c = st.columns(2)
        who = c[0].multiselect("User", sorted(log.username.unique()) if len(log) else [], key="ad_who"); what = c[1].multiselect("Action", sorted(log.action.unique()) if len(log) else [], key="ad_what")
        if who: log = log[log.username.isin(who)]
        if what: log = log[log.action.isin(what)]
        st.dataframe(log, hide_index=True, width="stretch", height=420); st.download_button("⬇️ Export audit log (CSV)", log.to_csv(index=False), "audit_log.csv", key="ad_dl")
    with t3:
        m = published_meta(); st.markdown("**Published analysis (what store staff see)**")
        st.json(m) if m else st.info("Nothing published yet. Run an analysis in the Data Hub and click *Publish*.")
        st.caption("Security notes: passwords are salted scrypt hashes; 5 failed sign-ins lock an account for 15 minutes; every sign-in, upload, publish, task change and location edit is logged. Serve over HTTPS and consider SSO for production.")
