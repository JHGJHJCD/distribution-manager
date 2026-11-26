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
CREATE INDEX IF NOT EXISTS history_by_batch ON history (batch_guid);
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
-- stage 3: the cards screen. A card that was deleted or merged away is kept whole, so
-- it can always be brought back; nothing is ever really thrown out.
CREATE TABLE IF NOT EXISTS deleted_cards (
    guid TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', deleted_at TEXT NOT NULL,
    reason TEXT NOT NULL, merged_into TEXT NOT NULL DEFAULT '', card TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS merged_guids (drop_guid TEXT PRIMARY KEY, keep_guid TEXT NOT NULL, ts TEXT NOT NULL);
-- "these are two different people": the answer to a look-alike suggestion (a < b)
CREATE TABLE IF NOT EXISTS not_duplicates (
    guid_a TEXT NOT NULL, guid_b TEXT NOT NULL, set_at TEXT NOT NULL, PRIMARY KEY (guid_a, guid_b)
);
-- stage 4: a HOLIDAY EVENT the manager set up (a date, portions, a filter). Like a coming
-- week, its list is never stored while it is ahead: it is computed each time. Once its day
-- has passed it is written to the history (closed_at) and stays as it was.
CREATE TABLE IF NOT EXISTS events (
    guid TEXT PRIMARY KEY,
    event_date TEXT NOT NULL, holiday TEXT NOT NULL,
    portions INTEGER NOT NULL, reserve INTEGER NOT NULL DEFAULT 0,
    criteria TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    closed_at TEXT, main_count INTEGER, batch_guid TEXT,
    deleted_at TEXT                     -- taken away by the manager; can be brought back
);
CREATE TABLE IF NOT EXISTS event_manual (
    event_guid TEXT NOT NULL, recipient_guid TEXT NOT NULL, action TEXT NOT NULL, set_at TEXT NOT NULL,
    PRIMARY KEY (event_guid, recipient_guid)
);
CREATE TABLE IF NOT EXISTS event_prints (
    event_guid TEXT PRIMARY KEY, printed_at TEXT NOT NULL, how TEXT NOT NULL,
    main TEXT NOT NULL, reserve TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_members (
    event_guid TEXT NOT NULL, recipient_guid TEXT NOT NULL, role TEXT NOT NULL,
    position INTEGER NOT NULL, kind TEXT NOT NULL, why TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (event_guid, recipient_guid)
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
        _add_missing_columns(conn)
        with tx(conn):
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                         (str(SCHEMA_VERSION),))
    finally:
        conn.close()


# Columns that were added to a table after it first shipped: {table: {column: its DDL}}.
# Additive only — a column is added when it is missing, nothing is ever changed or dropped.
_LATER_COLUMNS = {"events": {"deleted_at": "TEXT"}}


def _add_missing_columns(conn) -> None:
    for table, columns in _LATER_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


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


# ── stage 4: holiday events ───────────────────────────────────────────────────
def _event(r, manual: dict = None) -> dict:
    import json
    try:
        criteria = json.loads(r["criteria"] or "{}")
    except ValueError:
        criteria = {}
    return {"guid": r["guid"], "date": date.fromisoformat(r["event_date"]), "holiday": r["holiday"],
            "portions": r["portions"], "reserve": r["reserve"],
            "criteria": criteria if isinstance(criteria, dict) else {},
            "created_at": r["created_at"], "updated_at": r["updated_at"], "closed_at": r["closed_at"],
            "deleted_at": r["deleted_at"],
            "main_count": r["main_count"], "batch_guid": r["batch_guid"], "manual": manual or {}}


def load_events(conn, open_only: bool = True) -> list:
    """Holiday events in date order (two on one day: in the order they were created).
    open_only: the ones that are still ahead — not history yet — each with what the
    manager set by hand for it. An event that was taken away is never among them."""
    manual = {}
    for r in conn.execute("SELECT event_guid, recipient_guid, action FROM event_manual"):
        manual.setdefault(r["event_guid"], {})[r["recipient_guid"]] = r["action"]
    out = []
    for r in conn.execute("SELECT * FROM events WHERE deleted_at IS NULL"
                          + (" AND closed_at IS NULL" if open_only else "")
                          + " ORDER BY event_date, created_at, guid"):
        try:
            out.append(_event(r, manual.get(r["guid"])))
        except ValueError:
            continue
    return out


def get_event(conn, guid: str):
    r = conn.execute("SELECT * FROM events WHERE guid=?", (guid,)).fetchone()
    if r is None:
        return None
    manual = {m["recipient_guid"]: m["action"] for m in conn.execute(
        "SELECT recipient_guid, action FROM event_manual WHERE event_guid=?", (guid,))}
    try:
        return _event(r, manual)
    except ValueError:
        return None


def first_passed_event(conn, before: date):
    """The earliest event that is still open although its day is before `before`."""
    r = conn.execute("SELECT guid FROM events WHERE closed_at IS NULL AND deleted_at IS NULL AND event_date < ? "
                     "ORDER BY event_date, created_at, guid LIMIT 1", (before.isoformat(),)).fetchone()
    return get_event(conn, r["guid"]) if r else None


def save_event(conn, guid, day: date, holiday: str, portions: int, reserve: int, criteria: dict,
               now: datetime) -> str:
    """A new event (guid None) or a change to one. The caller holds the transaction and
    has already checked that the event is still ahead."""
    import json
    crit = json.dumps(criteria or {}, ensure_ascii=False, sort_keys=True)
    if guid is None:
        guid = uuid.uuid4().hex
        conn.execute("INSERT INTO events (guid, event_date, holiday, portions, reserve, criteria, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (guid, day.isoformat(), holiday, portions, reserve, crit, _stamp(now), _stamp(now)))
    else:
        conn.execute("UPDATE events SET event_date=?, holiday=?, portions=?, reserve=?, criteria=?, "
                     "updated_at=? WHERE guid=? AND closed_at IS NULL AND deleted_at IS NULL",
                     (day.isoformat(), holiday, portions, reserve, crit, _stamp(now), guid))
    return guid


def delete_event(conn, guid: str, now: datetime) -> None:
    """Take away an event that has NOT happened yet (a plan, never history). Nothing is
    erased: the event is only marked, with everything that was set for it, so that it can be
    brought back (restore_event). An event that is already history is never taken away."""
    done = conn.execute("UPDATE events SET deleted_at=? WHERE guid=? AND closed_at IS NULL AND deleted_at IS NULL",
                        (_stamp(now), guid)).rowcount
    if not done:
        raise LookupError(guid)


def restore_event(conn, guid: str) -> None:
    """Bring back an event that was taken away, as it was (the caller has checked that its
    day has not passed)."""
    done = conn.execute("UPDATE events SET deleted_at=NULL WHERE guid=? AND closed_at IS NULL "
                        "AND deleted_at IS NOT NULL", (guid,)).rowcount
    if not done:
        raise LookupError(guid)


def deleted_events(conn) -> list:
    """The events that were taken away, the latest first."""
    out = []
    for r in conn.execute("SELECT * FROM events WHERE deleted_at IS NOT NULL AND closed_at IS NULL "
                          "ORDER BY deleted_at DESC, guid"):
        try:
            out.append(_event(r))
        except ValueError:
            continue
    return out


def set_event_manual(conn, guid: str, recipient_guid: str, action, now: datetime) -> None:
    """action None = back to automatic for this person in this event."""
    if action is None:
        conn.execute("DELETE FROM event_manual WHERE event_guid=? AND recipient_guid=?", (guid, recipient_guid))
    else:
        conn.execute(
            "INSERT INTO event_manual (event_guid, recipient_guid, action, set_at) VALUES (?,?,?,?) "
            "ON CONFLICT(event_guid, recipient_guid) DO UPDATE SET action=excluded.action, set_at=excluded.set_at",
            (guid, recipient_guid, action, _stamp(now)))


def load_event_prints(conn) -> dict:
    """{event guid: {"printed_at", "how", "main": [guid], "reserve": [guid]}}"""
    import json
    return {r["event_guid"]: {"printed_at": r["printed_at"], "how": r["how"],
                              "main": json.loads(r["main"]), "reserve": json.loads(r["reserve"])}
            for r in conn.execute("SELECT * FROM event_prints")}


def set_event_print(conn, guid: str, how: str, main: list, reserve: list, now: datetime) -> None:
    import json
    conn.execute(
        "INSERT INTO event_prints (event_guid, printed_at, how, main, reserve) VALUES (?,?,?,?,?) "
        "ON CONFLICT(event_guid) DO UPDATE SET printed_at=excluded.printed_at, how=excluded.how, "
        "main=excluded.main, reserve=excluded.reserve",
        (guid, now.strftime("%Y-%m-%d %H:%M"), how, json.dumps(main), json.dumps(reserve)))


def event_batch_guid(guid: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"manhal-haluka/web/event/{guid}").hex


def event_row_guid(guid: str, recipient_guid: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"manhal-haluka/web/event/{guid}/{recipient_guid}").hex


def close_event(conn, plan: dict, name: str, now: datetime) -> bool:
    """Write a holiday event whose day has passed into the history, exactly as the planner
    laid it out: everybody on its MAIN list received — in an EXTRA round (the holiday code
    is on every row, so no regular turn moves) — and the reserve is kept for the record
    only. An event that is already closed is left alone (returns False), so two requests
    can never write it twice. The caller holds the transaction."""
    guid = plan["guid"]
    row = conn.execute("SELECT closed_at, deleted_at FROM events WHERE guid=?", (guid,)).fetchone()
    if row is None or row["closed_at"] or row["deleted_at"]:
        return False
    iso, stamp, batch, code = plan["date"].isoformat(), _stamp(now), event_batch_guid(guid), plan["holiday"]
    main = plan["main"]
    conn.execute(
        "INSERT INTO batches (guid, dist_name, dist_date, quantity, recipient_count, holiday, created_at, source) "
        "VALUES (?,?,?,?,?,?,?,?)", (batch, name, iso, plan["portions"], len(main), code, stamp, "web"))
    for e in main:
        conn.execute(
            "INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, received, holiday, "
            "batch_guid, created_at, source) VALUES (?,?,?,?,1,?,?,?,?)",
            (event_row_guid(guid, e["guid"]), e["guid"], e["name"], iso, code, batch, stamp, "web"))
    pos = 0
    for role, entries in (("main", main), ("reserve", plan["reserve_list"])):
        for e in entries:
            pos += 1
            conn.execute(
                "INSERT INTO event_members (event_guid, recipient_guid, role, position, kind, why) "
                "VALUES (?,?,?,?,?,?)", (guid, e["guid"], role, pos, e["kind"], e["why"]))
    conn.execute("UPDATE events SET closed_at=?, main_count=?, batch_guid=? WHERE guid=?",
                 (stamp, len(main), batch, guid))
    return True


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


# ── stage 3: the cards ────────────────────────────────────────────────────────
def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _version_stamp(now: datetime) -> str:
    """updated_at of a card: the time, plus a few random characters — so two saves in the
    same second are still two different versions (the card screen refuses to save over a
    version it did not see)."""
    return f"{_stamp(now)}.{uuid.uuid4().hex[:6]}"


def get_recipient(conn, guid: str):
    row = conn.execute("SELECT * FROM recipients WHERE guid=?", (guid,)).fetchone()
    return dict(row) if row else None


def _writable(fields: dict) -> dict:
    """Only real card columns are ever written (a name that is not a column is a bug in
    the caller, never something to put into SQL)."""
    bad = [c for c in fields if c not in RECIPIENT_COLUMNS]
    if bad:
        raise KeyError(f"not a card column: {bad}")
    return fields


def insert_recipient(conn, fields: dict, now: datetime, guid: str = None) -> str:
    """A new card; returns its guid. The caller holds the transaction."""
    fields = dict(_writable(fields))
    fields.setdefault("created_at", _stamp(now))
    fields.setdefault("start_date", now.date().isoformat())
    fields["updated_at"] = _version_stamp(now)
    guid = guid or uuid.uuid4().hex
    cols = ["guid"] + list(fields)
    conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 [guid] + list(fields.values()))
    return guid


def update_recipient(conn, guid: str, fields: dict, now: datetime) -> None:
    fields = dict(_writable(fields))
    fields["updated_at"] = _version_stamp(now)
    conn.execute(f"UPDATE recipients SET {', '.join(c + '=?' for c in fields)} WHERE guid=?",
                 list(fields.values()) + [guid])


def history_counts(conn) -> dict:
    """{guid: how many rows of the history carry this card} (received or not)."""
    return {r["recipient_guid"]: r["n"] for r in conn.execute(
        "SELECT recipient_guid, COUNT(*) AS n FROM history "
        "WHERE recipient_guid IS NOT NULL AND recipient_guid<>'' GROUP BY recipient_guid")}


def last_received(conn) -> dict:
    """{guid: the last day this card received} — straight from the history, never stored."""
    return {r["recipient_guid"]: r["d"] for r in conn.execute(
        "SELECT recipient_guid, MAX(dist_date) AS d FROM history WHERE received=1 "
        "AND recipient_guid IS NOT NULL AND recipient_guid<>'' GROUP BY recipient_guid")}


def card_history(conn, guid: str, limit: int = 12) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT dist_date, received, holiday FROM history WHERE recipient_guid=? "
        "ORDER BY dist_date DESC, id DESC LIMIT ?", (guid, limit))]


def _remember_deleted(conn, card: dict, reason: str, now: datetime, merged_into: str = "") -> None:
    import json
    conn.execute(
        "INSERT OR REPLACE INTO deleted_cards (guid, name, deleted_at, reason, merged_into, card) "
        "VALUES (?,?,?,?,?,?)",
        (card["guid"], card.get("full_name") or "", _stamp(now), reason, merged_into,
         json.dumps({k: v for k, v in card.items() if k != "id"}, ensure_ascii=False)))


def delete_recipient(conn, guid: str, now: datetime) -> None:
    """Take a card out — only one that has no history at all (ValueError otherwise: such
    a card is paused, not deleted). The whole card is kept in deleted_cards."""
    card = get_recipient(conn, guid)
    if card is None:
        raise LookupError(guid)
    n = conn.execute("SELECT COUNT(*) AS n FROM history WHERE recipient_guid=?", (guid,)).fetchone()["n"]
    for table in ("week_members", "event_members"):
        n += conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE recipient_guid=?", (guid,)).fetchone()["n"]
    if n:
        raise ValueError("has history")
    _remember_deleted(conn, card, "delete", now)
    for table in ("week_manual", "event_manual"):
        conn.execute(f"DELETE FROM {table} WHERE recipient_guid=?", (guid,))
    conn.execute("DELETE FROM recipients WHERE guid=?", (guid,))


def deleted_cards(conn) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT guid, name, deleted_at, reason, merged_into FROM deleted_cards ORDER BY deleted_at DESC, guid")]


def restore_recipient(conn, guid: str, now: datetime) -> None:
    """Bring back a card that was deleted (not one that was merged into another: its
    history already lives on the other card)."""
    import json
    row = conn.execute("SELECT * FROM deleted_cards WHERE guid=?", (guid,)).fetchone()
    if row is None or row["reason"] != "delete":
        raise LookupError(guid)
    if get_recipient(conn, guid) is not None:
        raise ValueError("already there")
    card = json.loads(row["card"])
    fields = {c: card[c] for c in RECIPIENT_COLUMNS if c in card and card[c] is not None}
    insert_recipient(conn, fields, now, guid=guid)
    conn.execute("DELETE FROM deleted_cards WHERE guid=?", (guid,))


def different_pairs(conn) -> set:
    return {(r["guid_a"], r["guid_b"]) for r in conn.execute("SELECT guid_a, guid_b FROM not_duplicates")}


def set_different(conn, guids: list, now: datetime) -> None:
    """Every pair among these cards = two different people (so it is not suggested again)."""
    guids = sorted(set(guids))
    for i, a in enumerate(guids):
        for b in guids[i + 1:]:
            conn.execute("INSERT OR IGNORE INTO not_duplicates (guid_a, guid_b, set_at) VALUES (?,?,?)",
                         (a, b, _stamp(now)))


def merge_recipients(conn, keep_guid: str, drop_guid: str, fields: dict, now: datetime) -> int:
    """Card `drop` becomes part of card `keep`, in the caller's transaction: `fields` are
    written on the kept card, every history row and every hand-set week of the other card
    moves to it, and the other card goes whole into deleted_cards. Returns how many
    history rows moved. No history row is ever deleted."""
    import json
    drop = get_recipient(conn, drop_guid)
    if keep_guid == drop_guid or drop is None or get_recipient(conn, keep_guid) is None:
        raise LookupError("card")
    update_recipient(conn, keep_guid, fields, now)
    moved = conn.execute("UPDATE history SET recipient_guid=? WHERE recipient_guid=?",
                         (keep_guid, drop_guid)).rowcount
    for table, key in (("week_members", "week_wed"), ("week_manual", "week_wed"),
                       ("event_members", "event_guid"), ("event_manual", "event_guid")):
        # a week / an event that already holds the kept card keeps its own line
        conn.execute(f"DELETE FROM {table} WHERE recipient_guid=? AND {key} IN "
                     f"(SELECT {key} FROM {table} WHERE recipient_guid=?)", (drop_guid, keep_guid))
        conn.execute(f"UPDATE {table} SET recipient_guid=? WHERE recipient_guid=?", (keep_guid, drop_guid))
    for table, key in (("week_prints", "week_wed"), ("event_prints", "event_guid")):
        for r in conn.execute(f"SELECT {key} AS k, main, reserve FROM {table}").fetchall():
            lists = {}
            for col in ("main", "reserve"):
                old = json.loads(r[col])
                new = list(dict.fromkeys(keep_guid if g == drop_guid else g for g in old))
                if new != old:
                    lists[col] = json.dumps(new)
            for col, value in lists.items():
                conn.execute(f"UPDATE {table} SET {col}=? WHERE {key}=?", (value, r["k"]))
    conn.execute("DELETE FROM not_duplicates WHERE guid_a=? OR guid_b=?", (drop_guid, drop_guid))
    conn.execute("INSERT OR REPLACE INTO merged_guids (drop_guid, keep_guid, ts) VALUES (?,?,?)",
                 (drop_guid, keep_guid, _stamp(now)))
    _remember_deleted(conn, drop, "merge", now, merged_into=keep_guid)
    conn.execute("DELETE FROM recipients WHERE guid=?", (drop_guid,))
    return moved


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
