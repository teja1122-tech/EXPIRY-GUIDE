"""Publish an analysis so every user (including store staff who cannot upload data) sees the same numbers.
Snapshot = pickle written by the server only (trusted writers: admin/manager/analyst)."""
import json, pickle, time
from .db import workdir
from .auth import audit


def _dir():
    d = workdir() / "published"; d.mkdir(parents=True, exist_ok=True); return d


def publish(ds, fi, user):
    d = _dir(); pickle.dump({"ds": ds, "fi": fi}, open(d / "latest.pkl", "wb"), protocol=4)
    meta = dict(published_at=time.strftime("%Y-%m-%d %H:%M:%S"), published_by=user["username"], as_of=str(ds.as_of.date()), stores=ds.N, skus=ds.K, method=fi["method"])
    json.dump(meta, open(d / "latest.json", "w")); audit(user["username"], "analysis_published", f"as of {meta['as_of']}"); return meta


def published_meta():
    f = _dir() / "latest.json"; return json.load(open(f)) if f.exists() else None


def load_published():
    f = _dir() / "latest.pkl"
    if not f.exists(): return None
    return pickle.load(open(f, "rb"))
