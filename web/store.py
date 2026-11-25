# -*- coding: utf-8 -*-
"""The site's own small database (SQLite) — what is KEPT.

Only four things are stored: the cards, the history (weeks that have passed), the
settings, and — from stage 2 — what the manager set by hand for a week. A list of a
coming week is never stored: it is computed each time from these (web/planner.py).

The derived dates of the desktop program (last_distribution / next_distribution) do not
exist here at all: nothing can drift from the history because nothing is copied from it.
"""
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime

SCHEMA_VERSION = 1

# The card, as in the desktop program (same column names — the engine reads them), minus
# the three derived / screen-state columns that are computed here instead of stored.
RECIPIENT_COLUMNS = [
    "full_name", "first_name", "last_name", "status", "frequency", "priority", "priority_raw",
    "souls", "phone1", "phone2", "phone3", "address", "area", "start_date", "notes",
    "created_at", "updated_at", "external_id", "source", "birth_date", "spouse_birth_date",
    "id_number", "spouse_id_number", "children_home", "children_married", "children_total",
    "marital_status", "email", "synagogue", "housing_expenses", "medical_expenses", "income",
    "per_soul", "work_scope", "parent_type", "occupation", "representative",
    "representative_auto", "holiday_support", "holidays", "last_dist_base",
]
_INT_COLUMNS = {"priority", "souls", "children_home", "children_married", "children_total",
                "representative_auto", "holiday_support"}
HISTORY_COLUMNS = ["guid", "recipient_guid", "recipient_name", "dist_date", "received", "holiday",
                   "what_dist", "quantity", "distributor", "notes", "area", "souls", "batch_guid",
                   "created_at", "source"]
BATCH_COLUMNS = ["guid", "dist_name", "dist_date", "products", "quantity", "distributor",
                 "general_note", "recipient_count", "souls_total", "holiday", "created_at", "source"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL UNIQUE,
    %(recipient_columns)s
);
CREATE TABLE IF NOT EXISTS batches (
    guid TEXT PRIMARY KEY,
    dist_name TEXT NOT NULL DEFAULT '', dist_date TEXT NOT NULL, products TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 0, distributor TEXT NOT NULL DEFAULT '',
    general_note TEXT NOT NULL DEFAULT '', recipient_count INTEGER NOT NULL DEFAULT 0,
    souls_total INTEGER NOT NULL DEFAULT 0, holiday TEXT NOT NULL DEFAULT '',
    created_at TEXT, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL UNIQUE,
    recipient_guid TEXT, recipient_name TEXT NOT NULL DEFAULT '',
    dist_date TEXT NOT NULL, received INTEGER NOT NULL DEFAULT 1, holiday TEXT NOT NULL DEFAULT '',
    what_dist TEXT, quantity INTEGER, distributor TEXT, notes TEXT, area TEXT, souls INTEGER,
    batch_guid TEXT, created_at TEXT, source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_by_recipient ON history (recipient_guid, dist_date);
CREATE TABLE IF NOT EXISTS weeks (
    week_wed TEXT PRIMARY KEY,
    portions INTEGER NOT NULL, reserve INTEGER NOT NULL, main_count INTEGER NOT NULL,
    closed_at TEXT NOT NULL, source TEXT NOT NULL, batch_guid TEXT
);
CREATE TABLE IF NOT EXISTS week_members (
    week_wed TEXT NOT NULL, recipient_guid TEXT NOT NULL, role TEXT NOT NULL,
    position INTEGER NOT NULL, kind TEXT NOT NULL, why TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (week_wed, recipient_guid)
);
-- stage 2: what the manager set by hand for a coming week (it survives every recompute)
CREATE TABLE IF NOT EXISTS week_manual (
    week_wed TEXT NOT NULL, recipient_guid TEXT NOT NULL, action TEXT NOT NULL, set_at TEXT NOT NULL,
    PRIMARY KEY (week_wed, recipient_guid)
);
CREATE TABLE IF NOT EXISTS week_numbers (
    week_wed TEXT PRIMARY KEY, portions INTEGER, reserve INTEGER, set_at TEXT NOT NULL
);
-- the list as it stood when it was last printed / exported: only for the note
-- "changed since it was printed" — it never holds the list in place
CREATE TABLE IF NOT EXISTS week_prints (
    week_wed TEXT PRIMARY KEY, printed_at TEXT NOT NULL, how TEXT NOT NULL,
    main TEXT NOT NULL, reserve TEXT NOT NULL
);
"""


def _recipient_ddl() -> str:
    parts = []
    for c in RECIPIENT_COLUMNS:
        if c == "full_name":
            parts.append("full_name TEXT NOT NULL")
        elif c == "status":
            parts.append("status TEXT NOT NULL DEFAULT 'פעיל'")
        elif c == "frequency":
            parts.append("frequency TEXT NOT NULL DEFAULT ''")
        elif c == "priority":
            parts.append("priority INTEGER")
        elif c in _INT_COLUMNS:
            parts.append(f"{c} INTEGER NOT NULL DEFAULT 0")
        else:
            parts.append(f"{c} TEXT NOT NULL DEFAULT ''")
    return ",\n    ".join(parts)


def connect(path: str) -> sqlite3.Connection:
    """A connection in autocommit mode — every write goes through `tx()`."""
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """One all-or-nothing write. BEGIN IMMEDIATE: two requests can never interleave."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def create(path: str) -> None:
    """Create an empty database (tables only). Existing tables are left as they are."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(_SCHEMA % {"recipient_columns": _recipient_ddl()})
        with tx(conn):
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                         (str(SCHEMA_VERSION),))
    finally:
        conn.close()


_ensured = set()


def ensure_schema(path: str) -> None:
    """Bring an existing database up to the current tables (additive only: new tables are
    created, nothing is changed or dropped). Cheap, and done once per run for each file."""
    if path in _ensured or not os.path.exists(path):
        return
    create(path)
    _ensured.add(path)


# ── what the manager set by hand ──────────────────────────────────────────────
def load_manual(conn) -> dict:
    """{Wednesday: {guid: action}}"""
    out = {}
    for r in conn.execute("SELECT week_wed, recipient_guid, action FROM week_manual"):
        try:
            out.setdefault(date.fromisoformat(r["week_wed"]), {})[r["recipient_guid"]] = r["action"]
        except ValueError:
            continue
    return out


def set_manual(conn, wed: date, guid: str, action, now: datetime) -> None:
    """action None = back to automatic for this person in this week."""
    if action is None:
        conn.execute("DELETE FROM week_manual WHERE week_wed=? AND recipient_guid=?", (wed.isoformat(), guid))
    else:
        conn.execute(
            "INSERT INTO week_manual (week_wed, recipient_guid, action, set_at) VALUES (?,?,?,?) "
            "ON CONFLICT(week_wed, recipient_guid) DO UPDATE SET action=excluded.action, set_at=excluded.set_at",
            (wed.isoformat(), guid, action, now.strftime("%Y-%m-%d %H:%M:%S")))


def load_numbers(conn) -> dict:
    """{Wednesday: {"portions": n, "reserve": n}} — only the numbers that were set."""
    out = {}
    for r in conn.execute("SELECT week_wed, portions, reserve FROM week_numbers"):
        try:
            wed = date.fromisoformat(r["week_wed"])
        except ValueError:
            continue
        out[wed] = {k: r[k] for k in ("portions", "reserve") if r[k] is not None}
    return out


def set_numbers(conn, wed: date, portions, reserve, now: datetime) -> None:
    """None for both = back to the ordinary numbers for this week."""
    if portions is None and reserve is None:
        conn.execute("DELETE FROM week_numbers WHERE week_wed=?", (wed.isoformat(),))
    else:
        conn.execute(
            "INSERT INTO week_numbers (week_wed, portions, reserve, set_at) VALUES (?,?,?,?) "
            "ON CONFLICT(week_wed) DO UPDATE SET portions=excluded.portions, reserve=excluded.reserve, "
            "set_at=excluded.set_at", (wed.isoformat(), portions, reserve, now.strftime("%Y-%m-%d %H:%M:%S")))


def load_prints(conn) -> dict:
    """{Wednesday: {"printed_at", "how", "main": [guid], "reserve": [guid]}}"""
    import json
    out = {}
    for r in conn.execute("SELECT * FROM week_prints"):
        try:
            out[date.fromisoformat(r["week_wed"])] = {
                "printed_at": r["printed_at"], "how": r["how"],
                "main": json.loads(r["main"]), "reserve": json.loads(r["reserve"])}
        except ValueError:
            continue
    return out


def set_print(conn, wed: date, how: str, main: list, reserve: list, now: datetime) -> None:
    import json
    conn.execute(
        "INSERT INTO week_prints (week_wed, printed_at, how, main, reserve) VALUES (?,?,?,?,?) "
        "ON CONFLICT(week_wed) DO UPDATE SET printed_at=excluded.printed_at, how=excluded.how, "
        "main=excluded.main, reserve=excluded.reserve",
        (wed.isoformat(), now.strftime("%Y-%m-%d %H:%M"), how, json.dumps(main), json.dumps(reserve)))


# ── meta / settings ───────────────────────────────────────────────────────────
def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def get_settings(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def set_setting(conn, key: str, value) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def int_setting(settings: dict, key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(float(settings.get(key))))
    except (TypeError, ValueError, OverflowError):
        return default


# ── reading ───────────────────────────────────────────────────────────────────
def load_recipients(conn) -> list:
    rows = []
    for r in conn.execute("SELECT * FROM recipients ORDER BY full_name, id"):
        d = dict(r)
        d["frequency"] = d.get("frequency") or ""
        d["status"] = d.get("status") or ""
        rows.append(d)
    return rows


def load_received(conn) -> list:
    """The history rows the planner counts: who received, when, and whether the round was
    an extra one (holiday / bonus). No-shows and rows without a card are left out."""
    return [dict(r) for r in conn.execute(
        "SELECT recipient_guid, dist_date, received, holiday FROM history "
        "WHERE received=1 AND recipient_guid IS NOT NULL AND recipient_guid<>''")]


def closed_through(conn):
    """The last Wednesday that is already history (None on a database never set up)."""
    s = get_meta(conn, "closed_through")
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


# ── closing a week: the list as it stood becomes history ──────────────────────
def week_batch_guid(wed: date) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"manhal-haluka/web/week/{wed.isoformat()}").hex


def week_row_guid(wed: date, recipient_guid: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL,
                      f"manhal-haluka/web/week/{wed.isoformat()}/{recipient_guid}").hex


def close_week(conn, week: dict, now: datetime, source: str = "auto") -> bool:
    """Write a week that has passed into the history, exactly as the planner laid it out:
    everybody on the MAIN list received (nobody ticks who came — decision 25/11/2026), the
    reserve is kept for the record but did not receive. One transaction; a week that is
    already closed is left alone (returns False), so two requests can never write it twice.
    The caller holds the transaction (`with tx(conn):`)."""
    wed = week["date"]
    iso = wed.isoformat()
    if conn.execute("SELECT 1 FROM weeks WHERE week_wed=?", (iso,)).fetchone():
        return False
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    batch = week_batch_guid(wed)
    main = week["main"]
    conn.execute(
        "INSERT INTO batches (guid, dist_name, dist_date, quantity, recipient_count, created_at, source) "
        "VALUES (?,?,?,?,?,?,?)",
        (batch, f"חלוקת רביעי {wed.strftime('%d/%m/%Y')}", iso, week["portions"], len(main), stamp, "web"))
    for e in main:
        conn.execute(
            "INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, received, holiday, "
            "batch_guid, created_at, source) VALUES (?,?,?,?,1,'',?,?,?)",
            (week_row_guid(wed, e["guid"]), e["guid"], e["name"], iso, batch, stamp, "web"))
    pos = 0
    for role, entries in (("main", main), ("reserve", week["reserve_list"])):
        for e in entries:
            pos += 1
            conn.execute(
                "INSERT INTO week_members (week_wed, recipient_guid, role, position, kind, why) "
                "VALUES (?,?,?,?,?,?)", (iso, e["guid"], role, pos, e["kind"], e["why"]))
    conn.execute(
        "INSERT INTO weeks (week_wed, portions, reserve, main_count, closed_at, source, batch_guid) "
        "VALUES (?,?,?,?,?,?,?)", (iso, week["portions"], week["reserve"], len(main), stamp, source, batch))
    prev = closed_through(conn)
    if prev is None or wed > prev:
        set_meta(conn, "closed_through", iso)
    return True


# ── backup ────────────────────────────────────────────────────────────────────
def backup(path: str, backup_dir: str, reason: str, now: datetime = None) -> str:
    """A full copy of the database (SQLite's own backup, safe while the site is running).
    Returns the new file's path, or '' when there is no database yet. Never deletes."""
    if not os.path.exists(path):
        return ""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch for ch in reason if ch.isalnum() or ch in "-_") or "backup"
    dest = os.path.join(backup_dir, f"haluka-{stamp}-{safe}.db")
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(backup_dir, f"haluka-{stamp}-{safe}-{n}.db")
    src = sqlite3.connect(path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest
