import streamlit as st
from core import auth


def render():
    S = st.session_state
    st.markdown("<div class='hero' style='text-align:center'><h1>💊 ExpiryGuard</h1><p>Near-expiry stock intelligence for pharmacy chains</p></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        if auth.user_count() == 0:
            st.subheader("First-time setup"); st.info("No accounts exist yet. Create the administrator account - it can add everyone else.")
            with st.form("setup_form"):
                u = st.text_input("Username", key="setup_user"); n = st.text_input("Display name", key="setup_name")
                p = st.text_input("Password", type="password", key="setup_pw", help="8+ characters with letters and numbers"); p2 = st.text_input("Confirm password", type="password", key="setup_pw2")
                go = st.form_submit_button("Create administrator", type="primary", key="setup_submit")
            if go:
                if p != p2: st.error("Passwords do not match.")
                else:
                    try:
                        auth.create_user(u, p, "admin", display_name=n); user, _ = auth.authenticate(u, p); S.user = user; st.rerun()
                    except ValueError as e: st.error(str(e))
        else:
            st.subheader("Sign in")
            with st.form("login_form"):
                u = st.text_input("Username", key="login_user"); p = st.text_input("Password", type="password", key="login_pw")
                go = st.form_submit_button("Sign in", type="primary", key="login_submit")
            if go:
                user, msg = auth.authenticate(u, p)
                if user: S.user = user; st.rerun()
                else: st.error(msg)
            st.caption("Forgot your password? Ask an administrator to reset it.")
