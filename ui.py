"""Shared UI helpers: theme, KPI cards, session state, auto re-planning."""
import json
import streamlit as st
from core.config import Params, PRESETS
from core.pipeline import plan_stage

GREEN, TEAL, RED, AMBER, GREY = "#1D6F5F", "#2FA58E", "#B5483A", "#D9A23B", "#9AA5A1"
BAND_COLORS = {"Low": "#7FBFAE", "Medium": AMBER, "High": RED, "Not scored (>120d)": "#CBD3D0"}

CSS = """<style>
:root{--g:#1D6F5F;--g2:#2FA58E;--ink:#17332e;--mut:#5b7a73;--card:#F3F7F6;--line:#E1ECE8;--ease:cubic-bezier(.2,.8,.2,1)}
.block-container{padding-top:1.4rem;max-width:1320px}
/* ---- page-by-page movement: the keyed wrapper is a NEW element on every page change, so the animation replays only then ---- */
@keyframes slideFromRight{from{opacity:0;transform:translateX(46px) scale(.992)}to{opacity:1;transform:none}}
@keyframes slideFromLeft{from{opacity:0;transform:translateX(-46px) scale(.992)}to{opacity:1;transform:none}}
@keyframes riseIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes heroShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes floaty{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
@keyframes pulseRing{0%{box-shadow:0 0 0 0 rgba(181,72,58,.35)}70%{box-shadow:0 0 0 10px rgba(181,72,58,0)}100%{box-shadow:0 0 0 0 rgba(181,72,58,0)}}
@keyframes chipIn{from{opacity:0;transform:scale(.85)}to{opacity:1;transform:scale(1)}}
[class*="st-key-pgfwd_"]{animation:slideFromRight .55s var(--ease) both}
[class*="st-key-pgback_"]{animation:slideFromLeft .55s var(--ease) both}
/* ---- hero ---- */
.hero{position:relative;overflow:hidden;background:linear-gradient(120deg,#1D6F5F,#2FA58E,#1B8A9A,#1D6F5F);background-size:300% 300%;animation:heroShift 14s ease infinite;color:#fff;border-radius:20px;padding:24px 30px;margin-bottom:16px;box-shadow:0 10px 30px rgba(29,111,95,.22)}
.hero:before,.hero:after{content:"";position:absolute;border-radius:50%;background:rgba(255,255,255,.10);animation:floaty 7s ease-in-out infinite}
.hero:before{width:170px;height:170px;right:-40px;top:-60px}.hero:after{width:90px;height:90px;right:150px;bottom:-45px;animation-delay:-3s}
.hero h1{color:#fff;margin:0;font-size:1.75rem;position:relative}.hero p{margin:.3rem 0 0;opacity:.94;position:relative}
/* ---- cards: staggered entrance + hover lift ---- */
.kpi{background:linear-gradient(180deg,#fff,#F3F7F6);border:1px solid var(--line);border-radius:16px;padding:13px 16px;height:100%;animation:riseIn .6s var(--ease) both;transition:transform .25s var(--ease),box-shadow .25s var(--ease),border-color .25s}
.kpi:hover{transform:translateY(-4px);box-shadow:0 12px 26px rgba(23,51,46,.12);border-color:#b9d6cd}
[data-testid="stColumn"]:nth-child(2) .kpi{animation-delay:.07s}[data-testid="stColumn"]:nth-child(3) .kpi{animation-delay:.14s}[data-testid="stColumn"]:nth-child(4) .kpi{animation-delay:.21s}
[data-testid="stColumn"]:nth-child(5) .kpi{animation-delay:.28s}[data-testid="stColumn"]:nth-child(6) .kpi{animation-delay:.35s}
.kpi .l{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.kpi .v{font-size:25px;font-weight:700;color:var(--ink);line-height:1.25}.kpi .s{font-size:12px;color:var(--mut)}
.kpi.bad .v{color:#B5483A}.kpi.good .v{color:#1D6F5F}.kpi.bad{border-left:4px solid #B5483A}.kpi.good{border-left:4px solid #1D6F5F}
.chip{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;background:#E1ECE8;color:#1D6F5F;margin-right:6px;animation:chipIn .4s var(--ease) both}
.chip.warn{background:#F7E9D2;color:#8a6410}.chip.focus{background:#1D6F5F;color:#fff}.chip.alert{background:#B5483A;color:#fff;animation:pulseRing 2s infinite}
/* ---- gestures: buttons, tabs, inputs ---- */
.stButton>button,.stDownloadButton>button{border-radius:12px;transition:transform .18s var(--ease),box-shadow .18s var(--ease)}
.stButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-2px);box-shadow:0 8px 18px rgba(23,51,46,.14)}
.stButton>button:active{transform:translateY(0) scale(.97)}
.stTabs [data-baseweb="tab"]{transition:background .2s,transform .2s}.stTabs [data-baseweb="tab"]:hover{transform:translateY(-2px)}
[data-testid="stPlotlyChart"]{border-radius:16px;transition:box-shadow .3s}[data-testid="stPlotlyChart"]:hover{box-shadow:0 8px 24px rgba(23,51,46,.08)}
/* ---- sidebar navigation as sliding pills ---- */
[data-testid="stSidebar"] [role="radiogroup"]{gap:2px}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:7px 12px;border-radius:12px;transition:transform .2s var(--ease),background .2s;cursor:pointer}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:#E1ECE8;transform:translateX(5px)}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:linear-gradient(90deg,#1D6F5F,#2FA58E);color:#fff;transform:translateX(5px);box-shadow:0 6px 14px rgba(29,111,95,.25)}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) *{color:#fff!important}
[data-testid="stSidebar"] [role="radiogroup"] label>div:first-child{display:none}
/* ---- workflow stepper + quick-action tiles + focus bar ---- */
[class*="st-key-step_"] button{border-radius:99px;font-size:13px;padding:2px 14px;min-height:34px}
.focusbar{background:#fff;border:1px dashed #b9d6cd;border-radius:14px;padding:6px 12px;margin:2px 0 10px;animation:riseIn .4s var(--ease) both}
.focusbar.on{border:1px solid var(--g);background:linear-gradient(90deg,#F3F7F6,#fff)}
[class*="st-key-tile_"] button{min-height:92px;border-radius:18px;border:1px solid var(--line);background:linear-gradient(135deg,#fff,#F3F7F6);text-align:left;white-space:normal;transition:transform .25s var(--ease),box-shadow .25s,border-color .25s}
[class*="st-key-tile_"] button:hover{transform:translateY(-5px) rotate(-.4deg);box-shadow:0 14px 28px rgba(29,111,95,.16);border-color:var(--g2)}
.st-key-focusbar,.st-key-focusbar_on{background:#fff;border:1px dashed #b9d6cd;border-radius:14px;padding:8px 14px 2px;margin:2px 0 12px;animation:riseIn .45s var(--ease) both}
.st-key-focusbar_on{border:1px solid var(--g);background:linear-gradient(90deg,#F3F7F6,#fff);box-shadow:0 6px 16px rgba(29,111,95,.10)}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
</style>"""


def inject_css(): st.markdown(CSS, unsafe_allow_html=True)


def hero(title, sub): st.markdown(f"<div class='hero'><h1>{title}</h1><p>{sub}</p></div>", unsafe_allow_html=True)


def kpi(col, label, value, sub="", tone=""):
    col.markdown(f"<div class='kpi {tone}'><div class='l'>{label}</div><div class='v'>{value}</div><div class='s'>{sub}&nbsp;</div></div>", unsafe_allow_html=True)


def money(x, cur=None):
    cur = cur or st.session_state.get("currency", "₹"); a = abs(x)
    if a >= 1e6: return f"{cur}{x/1e6:,.2f}M"
    if a >= 1e4: return f"{cur}{x/1e3:,.1f}k"
    return f"{cur}{x:,.0f}"


def init_state():
    S = st.session_state
    S.setdefault("ds", None); S.setdefault("fi", None); S.setdefault("res", None); S.setdefault("plan_key", None)
    S.setdefault("params", Params()); S.setdefault("fc_cache", {}); S.setdefault("scenarios", []); S.setdefault("currency", "₹")
    S.setdefault("profile", "Balanced (default)")


def ensure_plan():
    """Re-plan automatically whenever data or planning parameters change (fast; forecast is cached)."""
    S = st.session_state
    if S.ds is None or S.fi is None: return None
    key = (S.ds.fingerprint + S.ds.geo_hash, json.dumps(S.params.as_dict(), sort_keys=True))
    if S.plan_key != key:
        with st.spinner("Re-planning with current settings..."):
            S.res = plan_stage(S.ds, S.fi, S.params)
        S.plan_key = key
    return S.res


def need_analysis():
    """Guard used by every analysis page."""
    res = ensure_plan()
    if res is None:
        st.info("No analysis yet. Go to **🏠 Data Hub**, upload your files (or load a demo dataset) and click **Run analysis**.")
        st.stop()
    return st.session_state.ds, st.session_state.fi, res


def pc(fig, key=None, select=False, mode=("points",)):
    """Render a Plotly chart with smooth transitions. select=True enables click/box/lasso selection and returns the event."""
    fig.update_layout(margin=dict(l=10, r=10, t=45, b=10), font=dict(family="sans-serif", size=13), plot_bgcolor="white", paper_bgcolor="white",
                      transition=dict(duration=450, easing="cubic-in-out"), hoverlabel=dict(font_size=13))
    if select: return st.plotly_chart(fig, width="stretch", key=key, on_select="rerun", selection_mode=mode)
    st.plotly_chart(fig, width="stretch", key=key)


# =====================  linked focus, navigation helpers, toasts  =====================
SKIP = object()
FLOW = ["🏠 Data Hub", "📊 Command Center", "⚠️ Risk Explorer", "🚚 Action Center", "🔀 Transfer Planner", "✅ Task Board"]
FLOW_LABEL = {"🏠 Data Hub": "Upload", "📊 Command Center": "Overview", "⚠️ Risk Explorer": "Investigate", "🚚 Action Center": "Decide", "🔀 Transfer Planner": "Plan", "✅ Task Board": "Track"}


def goto(page):
    """on_click callback: jump to a page."""
    st.session_state.page = page


def queue_toast(msg, icon="✅"):
    st.session_state["_toast"] = (msg, icon)


def show_toast():
    t = st.session_state.pop("_toast", None)
    if t: st.toast(t[0], icon=t[1])
    if st.session_state.pop("_balloons", False): st.balloons()


def get_focus():
    return st.session_state.setdefault("focus", dict(store=None, category=None, sku=None, version=0))


def set_focus(**kw):
    """Update the global focus. Returns True if anything changed (callers then st.rerun() so every view agrees)."""
    f = get_focus(); changed = False
    for k, v in kw.items():
        if f.get(k) != v: f[k] = v; changed = True
    if changed: f["version"] += 1
    return changed


def clear_focus():
    return set_focus(store=None, category=None, sku=None)


def apply_focus(page, mapping):
    """Push the global focus into THIS page's widget keys, once per focus change, BEFORE the widgets are created.
    mapping: {widget_key: fn(focus) -> value | None (reset to default) | SKIP (leave alone)}."""
    S = st.session_state; f = get_focus(); seen = S.setdefault("_focus_seen", {})
    if seen.get(page) == f["version"]: return
    for key, fn in mapping.items():
        v = fn(f)
        if v is SKIP: continue
        if v is None: S.pop(key, None)
        else: S[key] = v
    seen[page] = f["version"]


def selected_points(key):
    """Points currently selected in a chart rendered with select=True (read before or after the chart)."""
    v = st.session_state.get(key)
    try: return list(v["selection"]["points"])
    except Exception: return []


def sync_selection(key, extract, apply):
    """When the user's chart selection CHANGES, translate it into a focus update. extract(points)->value, apply(value)->bool changed."""
    S = st.session_state; sig = repr(selected_points(key)); seen = S.setdefault("_selsig", {})
    if seen.get(key) == sig: return False
    first = key not in seen; seen[key] = sig
    if first and sig == "[]": return False
    return bool(apply(extract(selected_points(key))))


def stepper(allowed, page):
    steps = [p for p in FLOW if p in allowed]
    if page not in steps or len(steps) < 2: return
    cols = st.columns(len(steps))
    for i, (c, p) in enumerate(zip(cols, steps)):
        c.button(f"{i+1} · {FLOW_LABEL[p]}", key=f"step_{i}", on_click=goto, args=(p,), type="primary" if p == page else "secondary", width="stretch")


def prev_next(allowed, page):
    steps = [p for p in FLOW if p in allowed]
    if page not in steps: return
    i = steps.index(page); c = st.columns([1, 4, 1])
    if i > 0: c[0].button(f"← {FLOW_LABEL[steps[i-1]]}", key="nav_prev", on_click=goto, args=(steps[i-1],), width="stretch")
    if i < len(steps) - 1: c[2].button(f"{FLOW_LABEL[steps[i+1]]} →", key="nav_next", on_click=goto, args=(steps[i+1],), type="primary", width="stretch")


def tiles(items, prefix="tile"):
    """Quick-action tiles: items = [(icon, title, description, page)]. Each is a big button that jumps to the page."""
    cols = st.columns(len(items))
    for i, (c, (icon, title, desc, page)) in enumerate(zip(cols, items)):
        c.button(f"{icon}  {title}", key=f"{prefix}_{i}", on_click=goto, args=(page,), width="stretch"); c.caption(desc)


def _fb_changed():
    S = st.session_state
    set_focus(store=None if S.get("fb_store") in (None, "All stores") else S.fb_store, category=None if S.get("fb_cat") in (None, "All categories") else S.fb_cat)


def focus_bar(ds, allowed_stores, allowed_pages):
    """Global linked filter shown on every page. Charts, tables and maps on all pages follow it."""
    S = st.session_state; f = get_focus(); cats = sorted(ds.skus.category.unique()); on = bool(f["store"] or f["category"] or f["sku"])
    S.fb_store = f["store"] if f["store"] in allowed_stores else "All stores"; S.fb_cat = f["category"] if f["category"] in cats else "All categories"
    with st.container(key="focusbar_on" if on else "focusbar"):
        c = st.columns([1.05, 1.5, 1.5, 0.9, 3])
        c[0].markdown("**🔗 Linked focus**" + ("" if on else "<br><span style='font-size:11px;color:#5b7a73'>click a chart or pick here</span>"), unsafe_allow_html=True)
        c[1].selectbox("Store", ["All stores"] + list(allowed_stores), key="fb_store", on_change=_fb_changed, label_visibility="collapsed")
        c[2].selectbox("Category", ["All categories"] + cats, key="fb_cat", on_change=_fb_changed, label_visibility="collapsed")
        c[3].button("✕ Clear", key="fb_clear", on_click=clear_focus, disabled=not on, width="stretch")
        with c[4]:
            if on:
                jump = [("⚠️ Risk Explorer", "Risk"), ("🔮 Forecast Explorer", "Forecast"), ("🌍 Geo Map", "Map"), ("🔀 Transfer Planner", "Planner")]
                jump = [(p, l) for p, l in jump if p in allowed_pages]; jc = st.columns(len(jump) + 1); jc[0].markdown("<span style='font-size:13px;color:#5b7a73'>Open in →</span>", unsafe_allow_html=True)
                for col, (p, l) in zip(jc[1:], jump): col.button(l, key=f"fbj_{l}", on_click=goto, args=(p,), width="stretch")
