"""Authentication, roles, store-level permissions and audit log.
Passwords: scrypt with a per-user random salt, constant-time comparison, lockout after 5 failures (15 min)."""
import hashlib, hmac, json, re, secrets, time
import pandas as pd
from .db import conn

ROLES = ["admin", "manager", "analyst", "store_staff"]
ROLE_LABEL = {"admin": "Administrator", "manager": "Manager", "analyst": "Analyst", "store_staff": "Store staff"}
ALL, NOT_STAFF = set(ROLES), {"admin", "manager", "analyst"}
PAGE_ROLES = {   # which roles may open which page
    "🏠 Data Hub": NOT_STAFF, "📊 Command Center": NOT_STAFF, "🔔 Alerts": ALL, "🔮 Forecast Explorer": ALL, "⚠️ Risk Explorer": ALL,
    "🚚 Action Center": NOT_STAFF, "🔀 Transfer Planner": ALL, "✅ Task Board": ALL, "🌍 Geo Map": ALL, "🏷️ Markdown Studio": NOT_STAFF,
    "🧪 Scenario Lab": NOT_STAFF, "💰 Business Case": NOT_STAFF, "🗂️ Run History & Reports": NOT_STAFF, "🩺 Model Health": NOT_STAFF,
    "👥 Admin Console": {"admin"}}
MAX_FAILS, LOCK_SECONDS = 5, 900


def _now(): return time.strftime("%Y-%m-%d %H:%M:%S")


def _hash(pw, salt): return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


def password_problems(pw):
    p = []
    if len(pw) < 8: p.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw): p.append("both letters and numbers")
    return p


def audit(username, action, detail=""):
    with conn() as c: c.execute("INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)", (_now(), username or "-", action, str(detail)[:500]))


def list_audit(limit=1000):
    with conn() as c: return pd.DataFrame([dict(r) for r in c.execute("SELECT ts,username,action,detail FROM audit ORDER BY id DESC LIMIT ?", (limit,))])


def user_count():
    with conn() as c: return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def _public(r):
    return dict(id=r["id"], username=r["username"], display_name=r["display_name"] or r["username"], email=r["email"] or "", role=r["role"],
                stores=json.loads(r["stores"] or "[]"), active=bool(r["active"]), must_change=bool(r["must_change"]), last_login=r["last_login"], created_at=r["created_at"])


def create_user(username, password, role="analyst", display_name="", email="", stores=None, must_change=False, actor=None):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", username): raise ValueError("Username: 3-32 characters, letters/digits/._- only.")
    if role not in ROLES: raise ValueError("Unknown role.")
    prob = password_problems(password)
    if prob: raise ValueError("Password needs " + " and ".join(prob) + ".")
    salt = secrets.token_bytes(16)
    try:
        with conn() as c:
            c.execute("INSERT INTO users(username,display_name,email,role,pw_hash,salt,stores,must_change,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (username, display_name.strip() or username, email.strip(), role, _hash(password, salt), salt.hex(), json.dumps(list(stores or [])), int(must_change), _now()))
    except Exception as e:
        if "UNIQUE" in str(e): raise ValueError("That username is already taken.")
        raise
    audit(actor or username, "user_created", f"{username} ({role})")


def authenticate(username, password):
    """Returns (user|None, message). Generic message on failure so usernames are not revealed."""
    username = (username or "").strip().lower(); events = []; result = (None, "Invalid username or password.")
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if r is None:
            _hash(password or "x", b"0"*16); events.append(("login_failed", "unknown user"))      # same timing as a real check
        elif r["locked_until"] and r["locked_until"] > time.time():
            result = (None, f"Account locked after repeated failures. Try again in {int((r['locked_until']-time.time())/60)+1} minute(s).")
        elif not hmac.compare_digest(_hash(password or "", bytes.fromhex(r["salt"])), r["pw_hash"]):
            fails = r["failed_attempts"] + 1; lock = time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0
            c.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (0 if lock else fails, lock, r["id"]))
            events.append(("login_failed", "bad password" + (" - account locked" if lock else "")))
        elif not r["active"]:
            events.append(("login_blocked", "inactive")); result = (None, "This account is deactivated. Contact an administrator.")
        else:
            c.execute("UPDATE users SET failed_attempts=0, locked_until=0, last_login=? WHERE id=?", (_now(), r["id"]))
            events.append(("login", "")); result = (_public(r), "ok")
    for ev, d in events: audit(username, ev, d)
    return result


def get_user(username):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone(); return _public(r) if r else None


def list_users():
    with conn() as c: return pd.DataFrame([_public(r) for r in c.execute("SELECT * FROM users ORDER BY username")])


def set_password(username, new_password, must_change=False, actor=None):
    prob = password_problems(new_password)
    if prob: raise ValueError("Password needs " + " and ".join(prob) + ".")
    salt = secrets.token_bytes(16)
    with conn() as c: c.execute("UPDATE users SET pw_hash=?, salt=?, must_change=?, failed_attempts=0, locked_until=0 WHERE username=?", (_hash(new_password, salt), salt.hex(), int(must_change), username))
    audit(actor or username, "password_changed", username)


def change_own_password(username, old, new):
    u, msg = authenticate(username, old)
    if u is None: raise ValueError("Current password is incorrect.")
    set_password(username, new, must_change=False, actor=username)


def update_user(username, actor=None, **f):
    allowed = {"role", "display_name", "email", "stores", "active"}; sets, vals = [], []
    for k, v in f.items():
        if k not in allowed: continue
        if k == "role" and v not in ROLES: raise ValueError("Unknown role.")
        sets.append(f"{k}=?"); vals.append(json.dumps(list(v)) if k == "stores" else (int(v) if k == "active" else v))
    if sets:
        with conn() as c: c.execute(f"UPDATE users SET {', '.join(sets)} WHERE username=?", (*vals, username))
        audit(actor, "user_updated", f"{username}: " + ", ".join(f"{k}={v}" for k, v in f.items() if k in allowed))


def can_open(user, page): return user is not None and user["role"] in PAGE_ROLES.get(page, set())


def allowed_stores(user, all_stores):
    """Admins see everything; anyone else with assigned stores is restricted to them; unassigned store staff see nothing."""
    if user is None: return []
    if user["role"] == "admin": return list(all_stores)
    if user["stores"]: return [s for s in all_stores if s in set(user["stores"])]
    return [] if user["role"] == "store_staff" else list(all_stores)
