"""SQLite storage for users, audit log, tasks and location overrides. Path: $EXPIRY_WORKDIR/app.db (default ./workspace/app.db)."""
import os, sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display_name TEXT, email TEXT, role TEXT NOT NULL,
  pw_hash TEXT NOT NULL, salt TEXT NOT NULL, stores TEXT DEFAULT '[]', active INTEGER DEFAULT 1, must_change INTEGER DEFAULT 0,
  created_at TEXT, last_login TEXT, failed_attempts INTEGER DEFAULT 0, locked_until REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, created_by TEXT, kind TEXT, store_from TEXT, store_to TEXT, sku TEXT, batch_id TEXT,
  units INTEGER, expiry_date TEXT, est_gain REAL DEFAULT 0, credit REAL DEFAULT 0, move_cost REAL DEFAULT 0, note TEXT DEFAULT '',
  status TEXT, assigned_to TEXT DEFAULT '', as_of TEXT, updated_at TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS task_events(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, ts TEXT, username TEXT, event TEXT, comment TEXT);
CREATE TABLE IF NOT EXISTS geo_overrides(store TEXT PRIMARY KEY, lat REAL, lon REAL, updated_by TEXT, updated_at TEXT);
"""
_ready = set()


def workdir():
    return Path(os.environ.get("EXPIRY_WORKDIR", "workspace"))


@contextmanager
def conn():
    """Short-lived connection: commits on success, rolls back on error, always closes (avoids SQLite lock contention)."""
    d = workdir(); d.mkdir(parents=True, exist_ok=True); path = d / "app.db"
    c = sqlite3.connect(path, timeout=10); c.row_factory = sqlite3.Row
    try:
        if str(path) not in _ready: c.executescript(SCHEMA); c.commit(); _ready.add(str(path))
        yield c; c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()
