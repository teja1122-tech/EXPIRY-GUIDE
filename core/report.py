"""Downloadable reports: a multi-sheet Excel workbook and a self-contained HTML executive summary."""
import io, html
import numpy as np, pandas as pd


def _fmt(x, cur): return f"{cur}{x:,.0f}"


def excel_report(ds, fi, res, cur="₹"):
    k, sc, act = res["kpis"], res["sc"], res["actions"]; buf = io.BytesIO()
    summary = pd.DataFrame([
        ("As-of date", str(ds.as_of.date())), ("History used (days)", ds.T), ("Stores / SKUs", f"{ds.N} / {ds.K}"),
        ("Forecast method", fi["method"]), ("Over-dispersion alpha", round(fi["alpha"], 3)), ("Data quality score", round(ds.quality)),
        ("Stock value (cost)", k["stock_value"]), ("Expected expiry loss, next 120d", k["value_at_risk"]), ("Units expected to expire", round(k["units_at_risk"])),
        ("High-risk batches (>=70%)", k["high_risk_batches"]), ("Already expired stock (cost)", k["expired_value"]),
        ("Plan: transfer units / return units / markdown-review units", f"{k['transfer_units']} / {k['return_units']} / {k['markdown_units']}"),
        ("Plan: estimated net gain (lower bound)", k["est_net_gain"]), ("Plan: distributor credit", k["credit"])], columns=["Metric", "Value"])
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="Summary", index=False)
        cols = ["store", "sku", "category", "batch_id", "qty", "days_left", "p_unsold", "exp_unsold_units", "value_at_risk", "risk_band"]
        sc[sc.scored][cols].sort_values("value_at_risk", ascending=False).to_excel(w, sheet_name="Risk scores", index=False)
        if len(act):
            ac = ["id", "action", "store_from", "store_to", "sku", "batch_id", "units", "days_left", "expiry_date", "unit_cost", "move_cost", "est_gain", "credit", "approve"]
            act[ac].to_excel(w, sheet_name="Action plan", index=False)
            for s_, g in act[act.action.isin(["TRANSFER", "RETURN"])].groupby("store_from"):
                g[["action", "store_to", "sku", "batch_id", "units", "expiry_date"]].to_excel(w, sheet_name=("Pick " + s_)[:31], index=False)
        if len(ds.expired):
            e = ds.expired.copy(); e["store"] = ds.stores.store.values[e.s]; e["sku"] = ds.skus.sku.values[e.k]; e["value"] = e.qty*ds.cost[e.k.values]
            e[["store", "sku", "batch_id", "expiry_date", "qty", "value"]].to_excel(w, sheet_name="Already expired", index=False)
        wk = []
        for wi in range(17):
            sl = fi["fc"][:, :, wi*7:(wi+1)*7].sum(2); wk.append(pd.DataFrame(sl, index=ds.stores.store, columns=ds.skus.sku).stack().rename(f"week_{wi+1}"))
        pd.concat(wk, axis=1).rename_axis(["store", "sku"]).round(2).to_excel(w, sheet_name="Weekly forecast")
        if fi.get("backtest") is not None: fi["backtest"].to_excel(w, sheet_name="Forecast backtest", index=False)
        pd.DataFrame({"issue": [i["message"] for i in ds.issues] or ["none"]}).to_excel(w, sheet_name="Data checks", index=False)
    return buf.getvalue()


def html_summary(ds, fi, res, cur="₹"):
    k, sc, act = res["kpis"], res["sc"], res["actions"]
    top = sc[sc.scored].sort_values("value_at_risk", ascending=False).head(10)
    rows = "".join(f"<tr><td>{html.escape(r.store)}</td><td>{html.escape(r.sku)}</td><td>{r.qty}</td><td>{r.days_left}</td><td>{100*r.p_unsold:.0f}%</td><td>{_fmt(r.value_at_risk, cur)}</td></tr>" for r in top.itertuples())
    card = lambda a, b: f"<div class='c'><div class='l'>{a}</div><div class='v'>{b}</div></div>"
    return f"""<!doctype html><meta charset='utf-8'><title>Expiry-risk summary</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:30px auto;color:#17332e;padding:0 16px}}h1{{color:#1D6F5F}}
.g{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.c{{background:#F3F7F6;border-radius:10px;padding:14px}}.l{{font-size:12px;color:#5b7a73}}.v{{font-size:22px;font-weight:700}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #dde7e4;padding:6px 8px;text-align:left}}</style>
<h1>Expiry-risk summary</h1><p>As of {ds.as_of.date()} &middot; {ds.N} stores &middot; {ds.K} SKUs &middot; forecast: {html.escape(fi['method'])}</p>
<div class='g'>{card('Stock value', _fmt(k['stock_value'], cur))}{card('Expected expiry loss (120d)', _fmt(k['value_at_risk'], cur))}{card('High-risk batches', k['high_risk_batches'])}
{card('Transfer units', k['transfer_units'])}{card('Return units', k['return_units'])}{card('Est. net gain (lower bound)', _fmt(k['est_net_gain'], cur))}</div>
<h2>Top 10 batches by expected loss</h2><table><tr><th>Store</th><th>SKU</th><th>Qty</th><th>Days left</th><th>P(expire)</th><th>Expected loss</th></tr>{rows}</table>
<p style='color:#5b7a73;font-size:12px'>Estimates are model-based; gains are conservative lower bounds. Verify transfer/return rules with your compliance team.</p>"""
