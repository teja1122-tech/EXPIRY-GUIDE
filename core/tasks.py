"""Task workflow: PROPOSED -> APPROVED -> DISPATCHED -> COMPLETED (transfers) or PROPOSED -> APPROVED -> COMPLETED (returns/markdowns)."""
import time
import pandas as pd
from .db import conn
from .auth import audit

ACTIVE = ["PROPOSED", "APPROVED", "DISPATCHED"]
STATUSES = ACTIVE + ["COMPLETED", "REJECTED", "CANCELLED"]
KIND_LABEL = {"TRANSFER": "Transfer", "MANUAL_TRANSFER": "Transfer (manual)", "RETURN": "Return to distributor", "MARKDOWN_REVIEW": "Markdown review"}


def _now(): return time.strftime("%Y-%m-%d %H:%M:%S")


def _ev(c, tid, user, event, comment=""): c.execute("INSERT INTO task_events(task_id,ts,username,event,comment) VALUES(?,?,?,?,?)", (tid, _now(), user, event, comment))


def create_tasks(rows, user, status="PROPOSED", note="", as_of=""):
    """rows: iterable of dicts (kind, store_from, store_to, sku, batch_id, units, expiry_date, est_gain, credit, move_cost). Skips duplicates of active tasks."""
    made = skipped = 0
    with conn() as c:
        for r in rows:
            dup = c.execute("SELECT id FROM tasks WHERE kind=? AND store_from=? AND store_to=? AND sku=? AND batch_id=? AND status IN ('PROPOSED','APPROVED','DISPATCHED')",
                            (r["kind"], r["store_from"], r.get("store_to", ""), r["sku"], str(r["batch_id"]))).fetchone()
            if dup: skipped += 1; continue
            cur = c.execute("INSERT INTO tasks(created_at,created_by,kind,store_from,store_to,sku,batch_id,units,expiry_date,est_gain,credit,move_cost,note,status,as_of,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (_now(), user["username"], r["kind"], r["store_from"], r.get("store_to", ""), r["sku"], str(r["batch_id"]), int(r["units"]), str(r.get("expiry_date", "")),
                             float(r.get("est_gain", 0)), float(r.get("credit", 0)), float(r.get("move_cost", 0)), note, status, as_of, _now(), user["username"]))
            _ev(c, cur.lastrowid, user["username"], f"created as {status}", note); made += 1
    if made: audit(user["username"], "tasks_created", f"{made} task(s), {skipped} duplicate(s) skipped")
    return made, skipped


def list_tasks(statuses=None, stores=None):
    q, args = "SELECT * FROM tasks", []
    with conn() as c: df = pd.DataFrame([dict(r) for r in c.execute(q + " ORDER BY id DESC")])
    if df.empty: return df
    if statuses: df = df[df.status.isin(statuses)]
    if stores is not None: df = df[df.store_from.isin(stores) | df.store_to.isin(stores)]
    return df.reset_index(drop=True)


def task_events(tid):
    with conn() as c: return pd.DataFrame([dict(r) for r in c.execute("SELECT ts,username,event,comment FROM task_events WHERE task_id=? ORDER BY id", (tid,))])


def next_actions(task, user, user_stores):
    """Which status changes this user may perform on this task. user_stores = stores the user may act for (all for admin/manager)."""
    s, kind, role = task["status"], task["kind"], user["role"]; mgr = role in ("admin", "manager")
    at_from = task["store_from"] in user_stores; at_to = task["store_to"] in user_stores; out = []
    if s == "PROPOSED":
        if mgr: out += ["APPROVED", "REJECTED"]
        if mgr or task["created_by"] == user["username"]: out.append("CANCELLED")
    elif s == "APPROVED":
        if kind in ("TRANSFER", "MANUAL_TRANSFER"):
            if mgr or at_from: out.append("DISPATCHED")
        elif mgr or at_from: out.append("COMPLETED")
        if mgr: out.append("CANCELLED")
    elif s == "DISPATCHED":
        if mgr or at_to: out.append("COMPLETED")
    return out


def update_status(tid, new_status, user, user_stores, comment=""):
    with conn() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if r is None: raise ValueError("Task not found.")
        if new_status not in next_actions(dict(r), user, user_stores): raise PermissionError(f"You cannot move this task from {r['status']} to {new_status}.")
        c.execute("UPDATE tasks SET status=?, updated_at=?, updated_by=? WHERE id=?", (new_status, _now(), user["username"], tid))
        _ev(c, tid, user["username"], f"{r['status']} → {new_status}", comment)
    audit(user["username"], "task_status", f"#{tid}: {r['status']} → {new_status}")


def add_comment(tid, user, comment):
    if comment.strip():
        with conn() as c: _ev(c, tid, user["username"], "comment", comment.strip())
