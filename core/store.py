"""Run history: every analysis can be saved to disk so users can upload new data each period and compare over time."""
import json, os, time
from pathlib import Path
import pandas as pd

WORK = Path(os.environ.get("EXPIRY_WORKDIR", "workspace")) / "runs"


def save_run(label, ds, fi, res, user=None):
    WORK.mkdir(parents=True, exist_ok=True)
    rid = time.strftime("%Y%m%d-%H%M%S"); d = WORK / rid; d.mkdir()
    meta = dict(run_id=rid, label=label, saved_by=user or "", saved_at=time.strftime("%Y-%m-%d %H:%M:%S"), as_of=str(ds.as_of.date()), history_days=ds.T,
                stores=ds.N, skus=ds.K, quality=ds.quality, method=fi["method"], alpha=fi["alpha"], params=res["params"].as_dict(), **res["kpis"])
    json.dump(meta, open(d / "summary.json", "w"), indent=1, default=float)
    res["sc"].drop(columns=["scored"], errors="ignore").to_csv(d / "risk.csv.gz", index=False)
    if len(res["actions"]): res["actions"].to_csv(d / "actions.csv.gz", index=False)
    return rid


def list_runs():
    rows = []
    if WORK.exists():
        for d in sorted(WORK.iterdir()):
            f = d / "summary.json"
            if f.exists(): rows.append(json.load(open(f)))
    return pd.DataFrame(rows)


def delete_run(rid):
    d = WORK / rid
    if d.exists():
        for f in d.iterdir(): f.unlink()
        d.rmdir()


def load_risk(rid):
    f = WORK / rid / "risk.csv.gz"; return pd.read_csv(f) if f.exists() else pd.DataFrame()
