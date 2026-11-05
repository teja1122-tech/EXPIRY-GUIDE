"""Headless end-to-end UI test (auth, roles, all pages, planner, tasks, geo, publish). Run: python tests/test_app.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
WORK = tempfile.mkdtemp(); os.environ["EXPIRY_WORKDIR"] = WORK
from streamlit.testing.v1 import AppTest
from core import auth, tasks, publish

APP = os.path.join(os.path.dirname(__file__), "..", "app.py"); fails = []; N = 0


def check(at, label, cond=True, extra=""):
    global N; N += 1
    errs = [e.value for e in at.exception]; bad = bool(errs) or not cond
    print(("FAIL " if bad else "ok   ") + label + (f"  {errs[:1]}" if errs else "") + (f"  {extra}" if bad and extra else ""))
    if bad: fails.append(label)


def go(at, page): at.radio(key="page").set_value(page).run()


def login(at, u, p):
    at.text_input(key="login_user").set_value(u); at.text_input(key="login_pw").set_value(p); at.button(key="login_submit").click().run()


# ================= 1. first-run setup + login =================
at = AppTest.from_file(APP, default_timeout=240).run(); check(at, "first run shows setup", [s.value for s in at.subheader] == ["First-time setup"])
at.text_input(key="setup_user").set_value("admin"); at.text_input(key="setup_name").set_value("Ada Admin")
at.text_input(key="setup_pw").set_value("weakpass"); at.text_input(key="setup_pw2").set_value("weakpass"); at.button(key="setup_submit").click().run()
check(at, "weak admin password rejected", len(at.error) > 0 and at.session_state["user"] is None)
at.text_input(key="setup_pw").set_value("Adm1nPass99"); at.text_input(key="setup_pw2").set_value("Adm1nPass99"); at.button(key="setup_submit").click().run()
check(at, "admin created and signed in", at.session_state["user"] is not None and at.session_state["user"]["role"] == "admin")
# ================= 2. original journey (unchanged features) =================
at.button(key="btn_demo").click().run(); check(at, "load demo A", at.session_state["ds"] is not None)
t = time.time(); at.button(key="btn_run").click().run(); check(at, f"run analysis ({time.time()-t:.0f}s)", at.session_state["res"] is not None)
OLD = ["📊 Command Center", "🔮 Forecast Explorer", "⚠️ Risk Explorer", "🚚 Action Center", "🏷️ Markdown Studio", "🧪 Scenario Lab", "💰 Business Case", "🗂️ Run History & Reports", "🩺 Model Health"]
for p in OLD: go(at, p); check(at, f"[original] {p}")
go(at, "🚚 Action Center")
for f in ["TRANSFER", "RETURN", "MARKDOWN_REVIEW"]: at.radio(key="ac_filter").set_value(f).run(); check(at, f"[original] Action Center filter {f}")
go(at, "⚠️ Risk Explorer"); at.slider(key="re_mp").set_value(0.5).run(); check(at, "[original] Risk Explorer min-prob")
go(at, "🏷️ Markdown Studio"); at.radio(key="md_scope").set_value("All at-risk batches").run(); check(at, "[original] Markdown Studio all batches")
go(at, "🧪 Scenario Lab"); at.slider(key="sl_rc").set_value(0.8).run(); at.button(key="sl_run").click().run(); check(at, "[original] Scenario run", len(at.session_state["scenarios"]) == 1)
at.button(key="sl_sweep").click().run(); check(at, "[original] Scenario sweeps")
# ================= 3. NEW features as admin =================
for p in ["🔔 Alerts", "🔀 Transfer Planner", "✅ Task Board", "🌍 Geo Map", "👥 Admin Console"]: go(at, p); check(at, f"[new] open {p}")
go(at, "🔀 Transfer Planner")
if "tp_ack" in [c.key for c in at.checkbox]: at.checkbox(key="tp_ack").set_value(True).run()
at.button(key="tp_create").click().run(); n1 = len(tasks.list_tasks()); check(at, "Transfer Planner creates a manual request", n1 == 1, f"tasks={n1}")
at.button(key="tp_create").click().run(); check(at, "duplicate request not created twice", len(tasks.list_tasks()) == 1)
go(at, "🚚 Action Center"); at.button(key="ac_send").click().run(); n2 = len(tasks.list_tasks()); check(at, "Action Center sends approved actions to Task Board", n2 > n1, f"tasks={n2}")
go(at, "✅ Task Board"); at.selectbox(key="tb_pick").set_value(int(tasks.list_tasks().id.max())).run()
at.button(key="tb_act_APPROVED").click().run(); st_ = tasks.list_tasks().set_index("id").loc[int(tasks.list_tasks().id.max()), "status"]; check(at, "Task Board: admin approves a task", st_ == "APPROVED", st_)
go(at, "🌍 Geo Map"); at.selectbox(key="gm_style").set_value("white-bg").run(); check(at, "Geo Map: change style"); at.selectbox(key="gm_sel").set_value("Store-03").run(); check(at, "Geo Map: radius circle")
at.selectbox(key="gm_near_store").set_value("Store-05").run(); check(at, "Geo Map: nearby search")
old_d = at.session_state["ds"].dist[0, 1]; at.button(key="gm_save").click().run(); check(at, "Geo Map: save locations")
go(at, "🧪 Scenario Lab"); at.number_input(key="sl_mk").set_value(10.0).run(); at.multiselect(key="sl_br").set_value(["Store-02"]).run(); at.button(key="sl_run").click().run(); check(at, "Scenario Lab: distance limit + blocked receiver", len(at.session_state["scenarios"]) == 2)
# admin creates users
go(at, "👥 Admin Console")
for u, role, stores in [("staff1", "store_staff", ["Store-01"]), ("mgr1", "manager", [])]:
    at.text_input(key="au_user").set_value(u); at.text_input(key="au_name").set_value(u.title()); at.selectbox(key="au_role").set_value(role)
    at.multiselect(key="au_stores").set_value(stores); at.text_input(key="au_pw").set_value("Temp12345"); at.button(key="au_submit").click().run()
check(at, "Admin creates 2 users", set(auth.list_users().username) == {"admin", "staff1", "mgr1"})
at.selectbox(key="eu_pick").set_value("admin").run(); at.selectbox(key="eu_role_admin").set_value("analyst").run(); at.button(key="eu_submit").click().run()
check(at, "Admin cannot demote themselves", auth.get_user("admin")["role"] == "admin")
go(at, "📊 Command Center"); go(at, "🏠 Data Hub"); at.button(key="btn_publish").click().run(); check(at, "Publish analysis", publish.published_meta() is not None)
go(at, "🗂️ Run History & Reports"); check(at, "[original] History page after saves")
# manager approves one task that Store-01 must dispatch (setup for the staff journey)
_all = tasks.list_tasks(); _p = _all[(_all.status == "PROPOSED") & (_all.store_from == "Store-01") & (_all.kind.isin(["TRANSFER", "MANUAL_TRANSFER"]))]
assert len(_p), "demo should contain a proposed Store-01 task"
tasks.update_status(int(_p.id.iloc[0]), "APPROVED", auth.get_user("admin"), [], "approved for dispatch")
# ================= 4. restricted store employee (fresh session) =================
at.button(key="btn_logout").click().run(); check(at, "sign out returns to login", at.session_state["user"] is None)
login(at, "staff1", "wrongpass"); check(at, "wrong password rejected", at.session_state["user"] is None and len(at.error) > 0)
login(at, "staff1", "Temp12345"); check(at, "staff must change temp password", at.session_state["user"] is not None and at.session_state["user"]["must_change"])
at.text_input(key="fp_new").set_value("StaffNew123"); at.text_input(key="fp_new2").set_value("StaffNew123"); at.button(key="fp_submit").click().run()
check(at, "staff sets new password", not at.session_state["user"]["must_change"])
pages = list(at.radio(key="page").options); expect = {"🔔 Alerts", "🔮 Forecast Explorer", "⚠️ Risk Explorer", "🔀 Transfer Planner", "✅ Task Board", "🌍 Geo Map"}
check(at, "staff sees only permitted pages", set(pages) == expect, str(set(pages) ^ expect))
check(at, "published analysis auto-loaded for staff", at.session_state["ds"] is not None)
go(at, "⚠️ Risk Explorer"); check(at, "staff Risk Explorer page")
df_rows = at.dataframe[0].value if len(at.dataframe) else None
check(at, "staff Risk Explorer shows only Store-01", df_rows is not None and set(df_rows["store"]) <= {"Store-01"} and len(df_rows) > 0, str(set(df_rows["store"]) if df_rows is not None else ""))
go(at, "🔮 Forecast Explorer"); check(at, "staff Forecast Explorer", list(at.selectbox(key="fe_store").options) == ["Store-01"])
go(at, "🔀 Transfer Planner"); check(at, "staff Transfer Planner (own store only)", list(at.selectbox(key="tp_store").options) == ["Store-01"])
go(at, "🔔 Alerts"); check(at, "staff Alerts"); go(at, "🌍 Geo Map"); check(at, "staff Geo Map")
go(at, "✅ Task Board"); shown = at.dataframe[0].value; check(at, "staff sees only tasks touching Store-01", all(("Store-01" in (r.store_from, r.store_to)) for r in shown.itertuples()), str(shown[["store_from", "store_to"]].values.tolist()[:4]))
staff_t = tasks.list_tasks(statuses=["APPROVED"], stores=["Store-01"]); staff_t = staff_t[(staff_t.store_from == "Store-01") & staff_t.kind.isin(["TRANSFER", "MANUAL_TRANSFER"])]
if len(staff_t):
    at.multiselect(key="tb_status").set_value(["APPROVED", "PROPOSED", "DISPATCHED"]).run(); at.selectbox(key="tb_pick").set_value(int(staff_t.id.iloc[0])).run()
    check(at, "staff can dispatch, cannot approve", "tb_act_DISPATCHED" in [b.key for b in at.button] and "tb_act_APPROVED" not in [b.key for b in at.button])
    at.button(key="tb_act_DISPATCHED").click().run(); check(at, "staff dispatches approved task", tasks.list_tasks().set_index("id").loc[int(staff_t.id.iloc[0]), "status"] == "DISPATCHED")
else: check(at, "approved task from Store-01 available for staff test", False)
# ================= 5. lockout + audit =================
at.button(key="btn_logout").click().run()
for i in range(5): login(at, "mgr1", "bad" + str(i))
login(at, "mgr1", "Temp12345"); check(at, "account locks after 5 failures", at.session_state["user"] is None and any("locked" in e.value.lower() for e in at.error))
log = auth.list_audit(); acts = set(log.action)
check(at, "audit log captured key events", {"login", "login_failed", "tasks_created", "task_status", "analysis_published", "user_created", "dataset_built", "analysis_run", "locations_saved"} <= acts, str({"login", "login_failed", "tasks_created", "task_status", "analysis_published", "user_created", "dataset_built", "analysis_run", "locations_saved"} - acts))
print(f"\n{N} checks - RESULT:", "ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
