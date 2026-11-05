"""Tests for the interactive layer: linked focus across pages, stepper/tiles/prev-next, slide direction, chart-selection sync, animations."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["EXPIRY_WORKDIR"] = tempfile.mkdtemp()
from streamlit.testing.v1 import AppTest
from core import auth

APP = os.path.join(os.path.dirname(__file__), "..", "app.py"); fails = []; N = 0


def check(label, cond, extra=""):
    global N; N += 1; print(("ok   " if cond else "FAIL ") + label + ("" if cond else f"   {extra}")); 
    if not cond: fails.append(label)


def go(at, page): at.radio(key="page").set_value(page).run()
def focus(at): return at.session_state["focus"]


# ---------- A. chart-selection sync logic (pure session-state harness) ----------
def harness():
    import streamlit as st, ui
    ch = ui.sync_selection("k1", lambda pts: pts[0]["y"] if pts else None, lambda v: ui.set_focus(store=v)); st.session_state["changed"] = ch


h = AppTest.from_function(harness, default_timeout=60).run()
check("selection sync: first run with no selection is a no-op", h.session_state["changed"] is False)
h.session_state["k1"] = {"selection": {"points": [{"y": "Store-04"}]}}; h.run()
check("selection sync: click sets focus store", h.session_state["changed"] is True and h.session_state["focus"]["store"] == "Store-04" and h.session_state["focus"]["version"] == 1)
h.run(); check("selection sync: unchanged selection does not re-fire", h.session_state["changed"] is False and h.session_state["focus"]["version"] == 1)
h.session_state["k1"] = {"selection": {"points": []}}; h.run()
check("selection sync: de-selecting clears focus", h.session_state["focus"]["store"] is None and h.session_state["focus"]["version"] == 2)


def harness2():
    import streamlit as st, ui
    f = ui.get_focus(); ui.apply_focus("pg", {"w_list": lambda f_: [f_["store"]] if f_["store"] else [], "w_one": lambda f_: f_["store"] if f_["store"] == "A" else ui.SKIP, "w_reset": lambda f_: f_["category"]})
    st.session_state["seen"] = dict(st.session_state.get("_focus_seen", {}))


h2 = AppTest.from_function(harness2, default_timeout=60); h2.session_state["w_reset"] = "stale"; h2.run()
check("apply_focus: None resets a widget key, [] seeds multiselect", "w_reset" not in h2.session_state and h2.session_state["w_list"] == [])
h2.session_state["focus"] = dict(store="A", category="Chronic", sku=None, version=1); h2.run()
check("apply_focus: new focus version is pushed to widgets", h2.session_state["w_list"] == ["A"] and h2.session_state["w_one"] == "A" and h2.session_state["w_reset"] == "Chronic")
h2.session_state["w_list"] = ["manual"]; h2.run(); check("apply_focus: user edits are NOT overwritten when focus is unchanged", h2.session_state["w_list"] == ["manual"])

# ---------- B. full app: linked focus across pages ----------
auth.create_user("admin", "Adm1nPass99", "admin", display_name="Ada")
at = AppTest.from_file(APP, default_timeout=240); at.session_state["user"] = auth.get_user("admin"); at.run()
at.button(key="btn_demo").click().run(); at.button(key="btn_run").click().run(); check("setup: demo analysed", at.session_state["res"] is not None and not at.exception)
check("focus bar present with no focus", at.selectbox(key="fb_store").value == "All stores")
go(at, "📊 Command Center"); check("Command Center renders (clock, bar, pills)", not at.exception)
at.button_group(key="cc_cat").set_value("Antibiotic").run(); check("category pill sets global focus", focus(at)["category"] == "Antibiotic" and not at.exception)
go(at, "⚠️ Risk Explorer"); check("Risk Explorer follows category focus", at.multiselect(key="re_cat").value == ["Antibiotic"], str(at.multiselect(key="re_cat").value))
go(at, "🔮 Forecast Explorer"); check("Forecast SKU list narrowed to focused category", all(o.endswith("Antibiotic") for o in at.selectbox(key="fe_sku").options))
at.selectbox(key="fb_store").set_value("Store-04").run(); check("focus bar sets store", focus(at)["store"] == "Store-04" and focus(at)["category"] == "Antibiotic")
check("Forecast Explorer jumps to focused store (same page, live)", at.selectbox(key="fe_store").value == "Store-04")
go(at, "⚠️ Risk Explorer"); check("Risk Explorer follows store focus", at.multiselect(key="re_st").value == ["Store-04"])
go(at, "🌍 Geo Map"); check("Geo Map follows store focus", at.selectbox(key="gm_sel").value == "Store-04" and at.selectbox(key="gm_near_store").value == "Store-04" and not at.exception)
go(at, "🔀 Transfer Planner"); check("Transfer Planner follows store focus (when it has at-risk batches)", at.selectbox(key="tp_store").value == "Store-04" or "Store-04" not in at.selectbox(key="tp_store").options)
go(at, "📊 Command Center"); check("Command Center shows focus chip", any("Store-04" in str(m.value) and "Antibiotic" in str(m.value) for m in at.markdown), "")
at.button(key="fb_clear").click().run(); check("Clear resets focus everywhere", focus(at)["store"] is None and focus(at)["category"] is None and at.selectbox(key="fb_store").value == "All stores")
go(at, "⚠️ Risk Explorer"); check("Risk Explorer filters reset after clear", at.multiselect(key="re_st").value == [] and at.multiselect(key="re_cat").value == [])
# explicit link buttons
at.selectbox(key="re_pick").set_value(0).run(); at.button(key="re_focus").click().run(); check("'Focus on this store' button sets global focus", focus(at)["store"] is not None)
b = focus(at)["store"]; at.button(key="fb_clear").click().run()
at.button(key="re_plan").click().run(); check("'Move this batch' opens Transfer Planner pre-selected", at.session_state["page"] == "🔀 Transfer Planner" and not at.exception)
# ---------- C. navigation gestures ----------
go(at, "🏠 Data Hub"); at.button(key="step_2").click().run(); check("stepper jumps to step 3 (Investigate)", at.session_state["page"] == "⚠️ Risk Explorer")
check("stepper moving forward slides from the right", at.session_state["_dir"] == "fwd")
at.button(key="nav_next").click().run(); check("Next → goes to Decide", at.session_state["page"] == "🚚 Action Center")
at.button(key="nav_prev").click().run(); check("← Back returns to Investigate", at.session_state["page"] == "⚠️ Risk Explorer")
check("moving backwards slides from the left", at.session_state["_dir"] == "back")
go(at, "📊 Command Center"); at.button(key="tile_0").click().run(); check("quick-action tile navigates", at.session_state["page"] == "⚠️ Risk Explorer")
go(at, "🏠 Data Hub"); check("Data Hub keeps next-step tiles visible whenever an analysis exists", "tile_dh_0" in [x.key for x in at.button])
at.button(key="tile_dh_3").click().run(); check("Data Hub tile opens the Geo Map", at.session_state["page"] == "🌍 Geo Map" and not at.exception)
# ---------- D. animation builders ----------
from views import anim
ds, res = at.session_state["ds"], at.session_state["res"]
clk = anim.expiry_clock(res["sc"], ds); last = sum(clk.frames[-1].data[0].y)
check("Expiry Clock last frame equals dashboard expected loss", abs(last - res["sc"].value_at_risk.sum()) < 1e-6 and len(clk.frames) == 25, f"{last} vs {res['sc'].value_at_risk.sum()}")
rp = anim.plan_replay(ds, res["actions"]); check("Plan replay has one frame per lane + start", rp is not None and len(rp.frames) == len(rp.data))
print(f"\n{N} checks - RESULT:", "ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
