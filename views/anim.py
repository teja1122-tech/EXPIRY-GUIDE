"""Animated Plotly figures (play/pause buttons + sliders). Pure functions - they only build figures."""
import numpy as np, pandas as pd, plotly.graph_objects as go
import ui

_PLAY = dict(frame=dict(duration=140, redraw=True), transition=dict(duration=90, easing="linear"), fromcurrent=True, mode="immediate")


def _controls(fig, labels, y=-0.12):
    fig.update_layout(updatemenus=[dict(type="buttons", direction="left", x=0.0, y=y, xanchor="left", yanchor="top", pad=dict(t=0, r=6),
                                        buttons=[dict(label="▶ Play", method="animate", args=[None, _PLAY]),
                                                 dict(label="⏸ Pause", method="animate", args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
                      sliders=[dict(x=0.17, len=0.83, y=y, yanchor="top", currentvalue=dict(prefix="", font=dict(size=13)), pad=dict(t=0, b=0),
                                    steps=[dict(label=l, method="animate", args=[[str(i)], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))]) for i, l in enumerate(labels)])])


def expiry_clock(sc, ds, step=5, horizon=120):
    """Watch expected expiry losses accumulate day by day if nothing is done, by category."""
    v = sc[sc.scored & (sc.days_left >= 1)]
    if v.empty: return None
    cats = sorted(v.category.unique()); days = np.arange(0, horizon + 1, step)
    by = v.groupby(["category", "days_left"]).value_at_risk.sum().unstack(fill_value=0).reindex(index=cats, columns=range(0, horizon + 1), fill_value=0).cumsum(axis=1)
    top = float(by.values.max()) * 1.12 or 1.0; colors = [ui.GREEN, ui.TEAL, ui.AMBER, ui.RED, "#7FBFAE", "#8AA29B", "#C98B7F", "#5E7F9B"]
    frames = []
    for i, d in enumerate(days):
        y = by[d].values; frames.append(go.Frame(name=str(i), data=[go.Bar(x=cats, y=y, marker_color=colors[:len(cats)], text=[f"{x:,.0f}" for x in y], textposition="outside")],
                                                 layout=go.Layout(title_text=f"Expiry clock - day {d} ({(ds.as_of + pd.Timedelta(days=int(d))).date()}): expected loss so far {y.sum():,.0f}")))
    fig = go.Figure(data=frames[0].data, frames=frames)
    fig.update_layout(title=frames[0].layout.title.text, height=430, yaxis=dict(range=[0, top], title="Cumulative expected loss"), xaxis_title=None, showlegend=False)
    _controls(fig, [f"d{d}" for d in days]); fig.update_layout(margin=dict(b=90)); return fig


def add_forecast_reveal(fig, fdates, mu_w, lo, hi, trace_index):
    """Adds Play so the forecast bars grow week by week (trace_index = the forecast trace). Initial view still shows everything."""
    n = len(mu_w); frames = []
    for k in range(0, n + 1):
        frames.append(go.Frame(name=str(k), traces=[trace_index], data=[go.Bar(x=list(fdates[:k]), y=list(mu_w[:k]), marker_color=ui.GREEN,
                                    error_y=dict(type="data", symmetric=False, array=list(hi[:k] - mu_w[:k]), arrayminus=list(mu_w[:k] - lo[:k]), color="#555"))]))
    fig.frames = frames; _controls(fig, [f"+{k}w" for k in range(0, n + 1)], y=-0.14); fig.update_layout(margin=dict(b=90)); return fig


def plan_replay(ds, act):
    """Rebuild the shipping network lane by lane (biggest lane first) on the map."""
    st_ = ds.stores
    if st_.lat.isna().any() or act.empty: return None
    t = act[act.action == "TRANSFER"].groupby(["store_from", "store_to"]).agg(units=("units", "sum"), gain=("est_gain", "sum")).reset_index().sort_values("units", ascending=False)
    if t.empty: return None
    pos = {r.store: (r.lat, r.lon) for r in st_.itertuples()}; L = len(t); mx = max(t.units.max(), 1)
    def lane(i, r, show):
        (a1, o1), (a2, o2) = pos[r.store_from], pos[r.store_to]
        return go.Scattermap(lat=[a1, a2] if show else [None], lon=[o1, o2] if show else [None], mode="lines", line=dict(width=2 + 7*r.units/mx, color="rgba(29,111,95,.75)"),
                             hoverinfo="text", text=f"{r.store_from} → {r.store_to}: {r.units} units", showlegend=False)
    lanes = list(t.itertuples())
    base = go.Scattermap(lat=st_.lat, lon=st_.lon, mode="markers+text", text=st_.store.str.replace("Store-", "S"), textposition="top right", marker=dict(size=14, color=ui.RED), name="Stores", hoverinfo="text", hovertext=st_.store)
    fig = go.Figure(data=[base] + [lane(i, r, True) for i, r in enumerate(lanes)])
    frames = [go.Frame(name=str(k), traces=list(range(1, L + 1)), data=[lane(i, r, i < k) for i, r in enumerate(lanes)],
                       layout=go.Layout(title_text=(f"Plan replay - lane {k}/{L}: {lanes[k-1].store_from} → {lanes[k-1].store_to}, {lanes[k-1].units} units" if k else "Plan replay - start"))) for k in range(0, L + 1)]
    fig.frames = frames
    fig.update_layout(map=dict(style="carto-positron", center=dict(lat=float(st_.lat.mean()), lon=float(st_.lon.mean())), zoom=9.2), height=500, margin=dict(l=0, r=0, t=40, b=70), title="Plan replay", legend=dict(orientation="h", y=1.02))
    _controls(fig, [str(k) for k in range(0, L + 1)], y=-0.02); return fig
