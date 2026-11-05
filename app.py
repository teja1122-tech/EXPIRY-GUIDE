"""ExpiryGuard - pharmacy near-expiry stock platform.  Run:  streamlit run app.py"""
import streamlit as st
import ui
from core import auth, publish, geo
from core.config import PRESETS
from views import (login, data_hub, command_center, alerts, forecast_explorer, risk_explorer, action_center, transfer_planner, task_board, geo_map,
                   markdown_studio, scenario_lab, business_case, history, model_health, admin_console)

st.set_page_config(page_title="ExpiryGuard", page_icon="💊", layout="wide")
ui.inject_css(); ui.init_state(); S = st.session_state
S.setdefault("user", None)
PAGES = {"🏠 Data Hub": data_hub, "📊 Command Center": command_center, "🔔 Alerts": alerts, "🔮 Forecast Explorer": forecast_explorer, "⚠️ Risk Explorer": risk_explorer,
         "🚚 Action Center": action_center, "🔀 Transfer Planner": transfer_planner, "✅ Task Board": task_board, "🌍 Geo Map": geo_map, "🏷️ Markdown Studio": markdown_studio,
         "🧪 Scenario Lab": scenario_lab, "💰 Business Case": business_case, "🗂️ Run History & Reports": history, "🩺 Model Health": model_health, "👥 Admin Console": admin_console}

# ---------------- sign-in gate ----------------
if S.user is None:
    login.render(); st.stop()
if S.user.get("must_change"):
    ui.hero("Set a new password", "Your administrator issued a temporary password. Choose your own before continuing.")
    with st.form("force_pw"):
        p1 = st.text_input("New password", type="password", key="fp_new", help="8+ characters with letters and numbers"); p2 = st.text_input("Confirm new password", type="password", key="fp_new2")
        go = st.form_submit_button("Save password", type="primary", key="fp_submit")
    if go:
        if p1 != p2: st.error("Passwords do not match.")
        else:
            try: auth.set_password(S.user["username"], p1, must_change=False, actor=S.user["username"]); S.user = auth.get_user(S.user["username"]); st.rerun()
            except ValueError as e: st.error(str(e))
    st.stop()

# everyone sees the latest published analysis automatically (store staff cannot upload data)
if S.ds is None and not S.get("pub_checked"):
    S.pub_checked = True; snap = publish.load_published()
    if snap: S.ds, S.fi = snap["ds"], snap["fi"]; S.fc_cache[S.ds.fingerprint] = S.fi; geo.apply_overrides(S.ds)

user = S.user; allowed_pages = [p for p in PAGES if auth.can_open(user, p)]


def _profile_changed():
    if S.profile in PRESETS: S.params = PRESETS[S.profile]


with st.sidebar:
    st.markdown("## 💊 ExpiryGuard"); st.caption("Near-expiry stock intelligence for pharmacy chains")
    st.markdown(f"<span class='chip'>👤 {user['display_name']}</span><span class='chip'>{auth.ROLE_LABEL[user['role']]}</span>" + (f"<br><span class='chip'>🏬 {', '.join(user['stores'][:3])}{'…' if len(user['stores']) > 3 else ''}</span>" if user["stores"] else ""), unsafe_allow_html=True)
    if S.get("page") not in allowed_pages: S.page = allowed_pages[0]
    page = st.radio("Navigate", allowed_pages, key="page", label_visibility="collapsed")
    st.divider()
    if user["role"] != "store_staff":
        opts = list(PRESETS) + (["Custom (from Scenario Lab)"] if S.params not in PRESETS.values() else [])
        S.profile = S.profile if S.profile in opts else ("Custom (from Scenario Lab)" if S.params not in PRESETS.values() else "Balanced (default)")
        st.selectbox("Planning profile", opts, key="profile", on_change=_profile_changed, help="Controls risk appetite, return terms and shipping costs for every page.")
        st.text_input("Currency symbol", key="currency"); st.divider()
    if S.ds is None: st.markdown("<span class='chip warn'>No data loaded</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='chip'>{S.ds.N} stores</span><span class='chip'>{S.ds.K} SKUs</span><br><span class='chip'>as of {S.ds.as_of.date()}</span>" + ("<span class='chip'>analysed</span>" if S.fi is not None else "<span class='chip warn'>not analysed</span>"), unsafe_allow_html=True)
    with st.expander("🔐 My account"):
        with st.form("chg_pw"):
            o = st.text_input("Current password", type="password", key="cp_old"); n = st.text_input("New password", type="password", key="cp_new")
            ok = st.form_submit_button("Change password", key="cp_submit")
        if ok:
            try: auth.change_own_password(user["username"], o, n); st.success("Password changed.")
            except ValueError as e: st.error(str(e))
        if st.button("Sign out", key="btn_logout"):
            auth.audit(user["username"], "logout", ""); S.user = None; S.pub_checked = False; S.pop("_last_page", None); st.rerun()
# ---------------- animated, linked page shell ----------------
ui.show_toast()
idx = allowed_pages.index(page)
if S.get("_last_page") != page:                       # page changed: pick the slide direction (forward = from right, back = from left)
    S._dir = "fwd" if idx >= S.get("_last_idx", -1) else "back"; S._last_page, S._last_idx = page, idx
ui.stepper(allowed_pages, page)
if S.ds is not None: ui.focus_bar(S.ds, auth.allowed_stores(user, S.ds.stores.store.tolist()), allowed_pages)
with st.container(key=f"pg{S.get('_dir', 'fwd')}_{idx}"):    # new key on every page change = new element = entrance animation replays
    PAGES[page].render()
    ui.prev_next(allowed_pages, page)
