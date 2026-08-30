import sqlite3
import sys
import os
import json
import uuid
import hashlib
import secrets
from datetime import date, datetime, timedelta


def _utc_now() -> str:
    """UTC timestamp for sync ordering (last-write-wins across computers)."""
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


def _sync_log(op: str, payload: dict):
    """Append a change record for the cross-computer sync journal. NEVER breaks
    the data operation itself — sync failures are logged and swallowed."""
    try:
        from utils import sync
        sync.log_change(op, payload)
    except Exception:
        pass


APP_DIR_NAME = "ManhalHaluka"


def _exe_dir() -> str:
    """Directory of the running EXE (frozen) or the source file (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir() -> str:
    """Stable per-user data directory (%APPDATA%\\ManhalHaluka), independent of
    where the EXE lives — so replacing or moving the EXE never loses data.
    Falls back to the EXE directory if %APPDATA% is unavailable."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    try:
        d = os.path.join(base, APP_DIR_NAME)
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return _exe_dir()


# Kept for backward compatibility (older code referenced _app_dir()).
_app_dir = _data_dir

DB_PATH = os.path.join(_data_dir(), "data.db")
BACKUP_DIR = os.path.join(_data_dir(), "backups")
# User-supplied top-bar logo, stored in the writable data dir (NOT inside the EXE
# bundle) so each charity can drop in its own logo and it survives updates.
USER_LOGO_PATH = os.path.join(_data_dir(), "org_logo.png")
CHAT_BG_PATH = os.path.join(_data_dir(), "chat_bg")   # user's chat wallpaper (any image ext)


def _legacy_db_candidates() -> list:
    """Old locations where a pre-upgrade database might live (next to the EXE,
    or inside the Desktop distribution folder)."""
    cands = [os.path.join(_exe_dir(), "data.db")]
    home = os.path.expanduser("~")
    cands.append(os.path.join(home, "Desktop", "מנהל_חלוקה_הפצה", "data.db"))
    return cands


def _copy_db(src_path: str, dst_path: str) -> bool:
    """Copy a SQLite DB using the Online Backup API (captures WAL contents)."""
    try:
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dst_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
        return True
    except Exception:
        return False


def migrate_legacy_db_if_needed(candidates=None, force=False):
    """One-time import of an old next-to-EXE database into the stable data dir.
    Runs only in the packaged app (unless force=True for tests). Returns the
    source path if a copy happened, else None. Never overwrites existing data."""
    if not force and not getattr(sys, "frozen", False):
        return None
    if os.path.exists(DB_PATH):
        return None  # stable location already has data — nothing to migrate
    for legacy in (candidates or _legacy_db_candidates()):
        try:
            if os.path.abspath(legacy) == os.path.abspath(DB_PATH):
                continue
            if os.path.exists(legacy) and _copy_db(legacy, DB_PATH):
                return legacy
        except Exception:
            continue
    return None


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    return conn


def _db_integrity_ok(path: str) -> bool:
    """True if the SQLite file opens and passes integrity_check."""
    try:
        c = sqlite3.connect(path)
        try:
            row = c.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            c.close()
    except Exception:
        return False


def _db_recipient_count(path: str) -> int:
    try:
        c = sqlite3.connect(path)
        try:
            return c.execute("SELECT COUNT(*) FROM recipients").fetchone()[0]
        finally:
            c.close()
    except Exception:
        return -1


def self_heal_db():
    """Recover from a 'database disk image is malformed' before the app touches
    the DB. Two stages, safest first:
      1. A stale/mismatched WAL+SHM sidecar can make an otherwise-fine DB read as
         malformed. Delete the sidecars and re-check — no data lost (a 0-byte or
         orphaned WAL holds no committed rows).
      2. If the DB itself is corrupt, restore the BEST backup (most recipients,
         newest as tiebreak) and set the corrupt file aside as data.corrupt.db.
    Never raises — a failure here just falls through to normal init."""
    try:
        if not os.path.exists(DB_PATH):
            return
        if _db_integrity_ok(DB_PATH):
            return

        # Stage 1: drop stale sidecars, retry.
        for ext in ("-wal", "-shm"):
            side = DB_PATH + ext
            try:
                if os.path.exists(side):
                    os.remove(side)
            except Exception:
                pass
        if _db_integrity_ok(DB_PATH):
            return

        # Stage 2: DB itself is bad — restore the NEWEST usable backup.
        # Selection rule (bug H3): among backups that are integrity-OK AND
        # non-empty (recipient_count > 0), pick the one with the newest mtime.
        #   • Newest-first respects a legitimate recent deletion/cleanup instead of
        #     resurrecting stale data — the old rule keyed on recipient COUNT first,
        #     so an older-but-larger backup would silently win over a newer-smaller
        #     one and bring deleted recipients back.
        #   • The non-empty floor still guards against restoring an empty/partial
        #     backup over what little structure remains (never "restore nothing").
        best, best_mtime = None, -1.0
        if os.path.isdir(BACKUP_DIR):
            for name in os.listdir(BACKUP_DIR):
                if not name.lower().endswith(".db"):
                    continue
                p = os.path.join(BACKUP_DIR, name)
                if not _db_integrity_ok(p):
                    continue
                if _db_recipient_count(p) <= 0:
                    continue   # skip empty/partial backups — never resurrect nothing
                mtime = os.path.getmtime(p)
                if mtime > best_mtime:
                    best, best_mtime = p, mtime
        # Set the corrupt DB aside BEFORE deciding what to restore (bug R1). We
        # NEVER delete or overwrite it — it is renamed to data.db.corrupt.db so it
        # stays available for inspection or manual recovery. Doing this even when
        # there is NO usable backup is what prevents a crash: init_db then opens a
        # MISSING path and recreates a fresh empty schema, instead of failing to
        # open the malformed file (the old code returned here and left the corrupt
        # file in place, so init_db crashed with 'file is not a database').
        try:
            corrupt = DB_PATH + ".corrupt.db"
            if os.path.exists(corrupt):
                os.remove(corrupt)
            os.replace(DB_PATH, corrupt)
        except Exception:
            # Could not even set it aside — nothing more we can safely do here;
            # fall through and let init_db attempt its normal path.
            pass

        if best is None:
            return   # no usable backup — init_db will create a fresh empty schema

        import shutil
        shutil.copy2(best, DB_PATH)
    except Exception:
        pass


def init_db():
    # Recover a corrupt/stale DB before opening it (stale WAL, malformed image).
    self_heal_db()
    # Bring forward data from a pre-upgrade location BEFORE opening (which would
    # otherwise create an empty DB in the stable dir and hide the old data).
    migrate_legacy_db_if_needed()
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS recipients (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name       TEXT NOT NULL,
            phone1          TEXT,
            phone2          TEXT,
            phone3          TEXT,
            address         TEXT,
            area            TEXT DEFAULT '',
            souls           INTEGER DEFAULT 0,
            frequency       TEXT DEFAULT '',
            start_date      TEXT,
            last_distribution TEXT,
            next_distribution TEXT,
            weekly_status   TEXT DEFAULT '',
            status          TEXT DEFAULT 'פעיל',
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            external_id     TEXT DEFAULT '',
            source          TEXT DEFAULT '',
            birth_date      TEXT DEFAULT '',
            spouse_birth_date TEXT DEFAULT '',
            id_number       TEXT DEFAULT '',
            spouse_id_number TEXT DEFAULT '',
            children_home   INTEGER DEFAULT 0,
            children_married INTEGER DEFAULT 0,
            children_total  INTEGER DEFAULT 0,
            marital_status  TEXT DEFAULT '',
            email           TEXT DEFAULT '',
            synagogue       TEXT DEFAULT '',
            housing_expenses TEXT DEFAULT '',
            medical_expenses TEXT DEFAULT '',
            income          TEXT DEFAULT '',
            per_soul        TEXT DEFAULT '',
            work_scope      TEXT DEFAULT '',
            parent_type     TEXT DEFAULT '',
            occupation      TEXT DEFAULT '',
            representative  TEXT DEFAULT '',
            priority        INTEGER,
            priority_raw    TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS distributions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id    INTEGER,
            recipient_name  TEXT NOT NULL,
            dist_date       TEXT NOT NULL,
            area            TEXT,
            souls           INTEGER,
            what_dist       TEXT,
            quantity        INTEGER,
            distributor     TEXT,
            notes           TEXT,
            batch_id        INTEGER,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (recipient_id) REFERENCES recipients(id) ON DELETE SET NULL
        );

        -- One row per distribution EVENT (a batch): the shared header data plus
        -- the multi-product breakdown and a single general note for the whole
        -- distribution. The per-recipient rows in `distributions` link back via
        -- batch_id. Powers the "חלוקות" tab.
        CREATE TABLE IF NOT EXISTS dist_batches (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dist_name       TEXT DEFAULT '',
            dist_date       TEXT NOT NULL,
            products        TEXT DEFAULT '',
            quantity        INTEGER DEFAULT 0,
            distributor     TEXT DEFAULT '',
            general_note    TEXT DEFAULT '',
            recipient_count INTEGER DEFAULT 0,
            souls_total     INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS change_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id    INTEGER,
            recipient_name  TEXT,
            field_changed   TEXT,
            old_value       TEXT,
            new_value       TEXT,
            changed_at      TEXT DEFAULT (datetime('now'))
        );

        -- Team chat between the computers that have the app (manager / secretary /
        -- board member). Rides the same Drive sync as everything else (#ya4f7).
        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            guid          TEXT DEFAULT '',
            author_device TEXT DEFAULT '',
            author_name   TEXT DEFAULT '',
            body          TEXT NOT NULL,
            created_at    TEXT DEFAULT ''
        );

        -- Per-device read markers for the chat (WhatsApp-style ✓✓): each device
        -- records the newest message timestamp it has read. Synced so the sender
        -- can tell whether the team has seen a message (#ya4f7).
        CREATE TABLE IF NOT EXISTS message_reads (
            device      TEXT PRIMARY KEY,
            device_name TEXT DEFAULT '',
            read_ts     TEXT DEFAULT ''
        );

        -- Journal of changes RECEIVED from another computer, with enough 'before'
        -- state to undo them. Powers the manager's change-log (#5rhe9). Local only
        -- (never synced) — each machine records what IT applied.
        CREATE TABLE IF NOT EXISTS sync_incoming (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            applied_at    TEXT DEFAULT '',
            author_device TEXT DEFAULT '',
            author_name   TEXT DEFAULT '',
            op            TEXT DEFAULT '',
            target_guid   TEXT DEFAULT '',
            target_name   TEXT DEFAULT '',
            summary       TEXT DEFAULT '',
            before_json   TEXT DEFAULT '',
            after_json    TEXT DEFAULT '',
            undone        INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );

        INSERT OR IGNORE INTO settings (key, value) VALUES ('backup_folder', '');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('last_backup_at', '');
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(recipients)")}
        _migrations = [
            ("weekly_status",      "TEXT DEFAULT ''"),
            ("external_id",        "TEXT DEFAULT ''"),
            ("source",             "TEXT DEFAULT ''"),
            ("birth_date",         "TEXT DEFAULT ''"),
            ("spouse_birth_date",  "TEXT DEFAULT ''"),
            ("id_number",          "TEXT DEFAULT ''"),
            ("spouse_id_number",   "TEXT DEFAULT ''"),
            ("children_home",      "INTEGER DEFAULT 0"),
            ("children_married",   "INTEGER DEFAULT 0"),
            ("children_total",     "INTEGER DEFAULT 0"),
            ("marital_status",     "TEXT DEFAULT ''"),
            ("email",              "TEXT DEFAULT ''"),
            ("synagogue",          "TEXT DEFAULT ''"),
            ("housing_expenses",   "TEXT DEFAULT ''"),
            ("medical_expenses",   "TEXT DEFAULT ''"),
            ("income",             "TEXT DEFAULT ''"),
            ("per_soul",           "TEXT DEFAULT ''"),
            ("work_scope",         "TEXT DEFAULT ''"),
            ("parent_type",        "TEXT DEFAULT ''"),
            ("occupation",         "TEXT DEFAULT ''"),
            ("representative",     "TEXT DEFAULT ''"),
            ("priority",           "INTEGER"),
            ("priority_raw",       "TEXT DEFAULT ''"),
            # v2.61: community balance + cross-computer sync
            ("representative_auto", "INTEGER DEFAULT 0"),  # 1 = נציג שויך אוטומטית
            ("updated_at",         "TEXT DEFAULT ''"),     # UTC iso — last-write-wins for sync
            ("guid",               "TEXT DEFAULT ''"),     # stable cross-device identity
            # v2.75 (#aka27): first/last name split. full_name stays the authoritative
            # identity (history / print / sync) and is kept = first + ' ' + last.
            ("first_name",         "TEXT DEFAULT ''"),
            ("last_name",          "TEXT DEFAULT ''"),
        ]
        newly_added = set()
        for col, definition in _migrations:
            if col not in columns:
                conn.execute(f"ALTER TABLE recipients ADD COLUMN {col} {definition}")
                newly_added.add(col)
        # First time the name columns appear: back-fill them by splitting the
        # existing full_name (last token = family name). Done ONCE, only for rows
        # not yet populated — never re-splits a name the operator later edits.
        if "first_name" in newly_added or "last_name" in newly_added:
            for r in conn.execute(
                    "SELECT id, full_name FROM recipients "
                    "WHERE COALESCE(first_name,'')='' AND COALESCE(last_name,'')=''").fetchall():
                fn, ln = split_full_name(r["full_name"] or "")
                conn.execute("UPDATE recipients SET first_name=?, last_name=? WHERE id=?",
                             (fn, ln, r["id"]))

        # Distributions: link each per-recipient row to its batch (added later,
        # so an older DB needs the column back-filled as NULL).
        dist_cols = {row["name"] for row in conn.execute("PRAGMA table_info(distributions)")}
        if "batch_id" not in dist_cols:
            conn.execute("ALTER TABLE distributions ADD COLUMN batch_id INTEGER")
        # received: 1 = the recipient actually got the distribution, 0 = they were
        # on the list but did NOT receive (a recorded no-show). Every pre-existing
        # row predates the flag and means "received", so the default is 1.
        if "received" not in dist_cols:
            conn.execute("ALTER TABLE distributions ADD COLUMN received INTEGER DEFAULT 1")
        if "guid" not in dist_cols:
            conn.execute("ALTER TABLE distributions ADD COLUMN guid TEXT DEFAULT ''")
        batch_cols = {row["name"] for row in conn.execute("PRAGMA table_info(dist_batches)")}
        if "guid" not in batch_cols:
            conn.execute("ALTER TABLE dist_batches ADD COLUMN guid TEXT DEFAULT ''")

        # Back-fill stable guids (v2.61, cross-computer sync): every row gets a
        # random identity ONCE; new rows get theirs at insert time.
        for table in ("recipients", "distributions", "dist_batches"):
            missing = [r["id"] for r in conn.execute(
                f"SELECT id FROM {table} WHERE guid IS NULL OR guid=''")]
            for rid in missing:
                conn.execute(f"UPDATE {table} SET guid=? WHERE id=?",
                             (uuid.uuid4().hex, rid))

        # Indexes are created AFTER the column migrations so that an older DB
        # (missing a column an index references) is upgraded first, not crashed.
        conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_recipients_status
            ON recipients(status);
        CREATE INDEX IF NOT EXISTS idx_recipients_name
            ON recipients(full_name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_distributions_recipient
            ON distributions(recipient_id);
        CREATE INDEX IF NOT EXISTS idx_distributions_name
            ON distributions(recipient_name);
        CREATE INDEX IF NOT EXISTS idx_distributions_date
            ON distributions(dist_date);
        CREATE INDEX IF NOT EXISTS idx_distributions_batch
            ON distributions(batch_id);
        CREATE INDEX IF NOT EXISTS idx_dist_batches_date
            ON dist_batches(dist_date);
        """)

        # ── Password migration ────────────────────────────────────────────────
        # Seed a hashed default password ('1234') for fresh installs, and
        # transparently upgrade any legacy plaintext password to a hash.
        row = conn.execute("SELECT value FROM settings WHERE key='password'").fetchone()
        if row is None:
            conn.execute("INSERT INTO settings (key, value) VALUES ('password', ?)",
                         (_hash_password("1234"),))
        elif not str(row["value"]).startswith("pbkdf2$"):
            # Legacy plaintext password — hash it in place.
            conn.execute("UPDATE settings SET value=? WHERE key='password'",
                         (_hash_password(str(row["value"])),))


# ─── Password hashing ─────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    """Return a salted PBKDF2 hash string: 'pbkdf2$<salt_hex>$<hash_hex>'."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(plain: str) -> bool:
    """Check a plaintext password against the stored hash (constant-time)."""
    stored = get_setting("password")
    if not stored or not stored.startswith("pbkdf2$"):
        return False
    try:
        _, salt_hex, hash_hex = stored.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 200_000)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def set_password(plain: str):
    """Store a new password as a salted hash."""
    set_setting("password", _hash_password(plain))
    # Remember only the LENGTH (not the password) so the settings screen can show
    # the correct number of mask dots. The hash itself reveals nothing about it.
    set_setting("password_len", str(len(plain or "")))


# ─── Manager code (#5rhe9) — gates designating a computer as the manager ──────

def manager_code_is_set() -> bool:
    return bool((get_setting("manager_code_hash") or "").startswith("pbkdf2$"))


def set_manager_code(plain: str):
    """Define the manager code (shared/synced, so both computers agree on it)."""
    set_setting("manager_code_hash", _hash_password(plain))


def verify_manager_code(plain: str) -> bool:
    stored = get_setting("manager_code_hash") or ""
    if not stored.startswith("pbkdf2$"):
        return False
    try:
        _, salt_hex, hash_hex = stored.split("$", 2)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"),
                                 bytes.fromhex(salt_hex), 200_000)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ------------------------------------------------------------------------------- Settings ────────────────────────────────────────────────────────────────

def get_setting(key: str) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""


def set_setting(key: str, value: str):
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    _sync_log("setting", {"key": key, "value": value})


# ─── Recipients ──────────────────────────────────────────────────────────────

def get_all_recipients(status_filter=None):
    with get_connection() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM recipients WHERE status=? ORDER BY full_name COLLATE NOCASE",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM recipients ORDER BY full_name COLLATE NOCASE"
            ).fetchall()
        return [dict(r) for r in rows]


def get_recipient(rec_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM recipients WHERE id=?", (rec_id,)).fetchone()
        return dict(row) if row else None


# Fields searched as free text, and fields searched as digit-only (phones / IDs).
_SEARCH_TEXT_FIELDS = [
    "full_name", "address", "area", "email", "synagogue", "occupation",
    "representative", "source", "notes", "external_id",
]
_SEARCH_DIGIT_FIELDS = [
    "phone1", "phone2", "phone3", "id_number", "spouse_id_number", "external_id",
]


def _only_digits(val) -> str:
    return "".join(ch for ch in str(val or "") if ch.isdigit())


def filter_recipients(rows: list, query: str, limit: int = None):
    """Filter an already-loaded list of recipient dicts across ALL key fields —
    name, phones, IDs (husband/wife), address, email, etc. A digit query also
    matches phone / ID numbers ignoring spaces and dashes. Empty query returns
    everyone. Results sorted by name. Pure (no DB access) so the search tab can
    cache rows once and filter in-memory on each keystroke.

    `limit=None` (the default) returns EVERY match — the app supports an
    unbounded number of recipients, so the search list is never truncated
    (#4zque). Pass a positive int only when a caller deliberately wants a cap."""
    q = (query or "").strip().lower()
    if not q:
        out = sorted(rows, key=lambda r: r.get("full_name", ""))
        return out[:limit] if limit else out

    q_digits = _only_digits(q)
    out = []
    for r in rows:
        haystack = " ".join(str(r.get(f, "") or "") for f in _SEARCH_TEXT_FIELDS).lower()
        matched = q in haystack
        if not matched and q_digits:
            digits = " ".join(_only_digits(r.get(f, "")) for f in _SEARCH_DIGIT_FIELDS)
            matched = q_digits in digits
        if matched:
            out.append(r)
    out = sorted(out, key=lambda r: r.get("full_name", ""))
    return out[:limit] if limit else out


def search_recipients(query: str, limit: int = None):
    """Convenience wrapper — loads all recipients then filters across all fields."""
    return filter_recipients(get_all_recipients(), query, limit)


def find_duplicate_groups():
    """Find data-quality issues for the review tab: recipients that share a
    full name, and phone numbers shared across different recipients.
    Returns a list of {'type', 'key', 'members': [recipient dicts]} groups."""
    recs = get_all_recipients()
    groups = []

    # ── duplicate full names ──────────────────────────────────────────────────
    by_name = {}
    for r in recs:
        nm = (r.get("full_name") or "").strip()
        if nm:
            by_name.setdefault(nm, []).append(r)
    for nm, members in by_name.items():
        if len(members) > 1:
            groups.append({"type": "שם כפול", "key": nm, "members": members})

    # ── phone numbers shared by more than one recipient ───────────────────────
    by_phone = {}
    for r in recs:
        seen = set()
        for f in ("phone1", "phone2", "phone3"):
            p = _only_digits(r.get(f))
            if len(p) >= 9 and p not in seen:
                seen.add(p)
                by_phone.setdefault(p, []).append(r)
    for phone, members in by_phone.items():
        uniq = list({m["id"]: m for m in members}.values())
        if len(uniq) > 1:
            groups.append({"type": "טלפון משותף", "key": phone, "members": uniq})

    # names first, then phones; each group's members kept together
    groups.sort(key=lambda g: (g["type"] != "שם כפול", g["key"]))
    return groups


def bulk_insert_recipients(rows: list) -> int:
    """Insert every row with a valid name as a NEW record (no dedup/merge) —
    used by 'replace' import so duplicates are preserved for review instead of
    being silently dropped. Returns the number inserted."""
    cols = _RECIPIENT_FIELDS
    sql = f"INSERT INTO recipients ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})"
    i_name, i_status = cols.index("full_name"), cols.index("status")
    count = 0
    new_ids = []
    with get_connection() as conn:
        for row in rows:
            name = (row.get("full_name") or "").strip()
            if not name or name in ("None", "0"):
                continue
            row = _apply_name_fields(row)   # derive/keep first_name+last_name (#aka27)
            name = (row.get("full_name") or "").strip()
            vals = [_coerce(c, row.get(c, "")) for c in cols]
            vals[i_name] = name
            if not vals[i_status]:
                vals[i_status] = "פעיל"
            cur = conn.execute(sql, vals)
            conn.execute("UPDATE recipients SET guid=?, updated_at=? WHERE id=?",
                         (uuid.uuid4().hex, _utc_now(), cur.lastrowid))
            new_ids.append(cur.lastrowid)
            count += 1
    for rid in new_ids:
        _sync_log("rec_upsert", _rec_sync_payload(rid))
    return count


_RECIPIENT_FIELDS = [
    "full_name", "first_name", "last_name", "phone1", "phone2", "phone3", "address", "area",
    "souls", "frequency", "start_date", "last_distribution", "next_distribution",
    "status", "notes",
    "external_id", "source", "birth_date", "spouse_birth_date",
    "id_number", "spouse_id_number",
    "children_home", "children_married", "children_total",
    "marital_status", "email", "synagogue",
    "housing_expenses", "medical_expenses", "income", "per_soul",
    "work_scope", "parent_type", "occupation", "representative",
    "priority", "priority_raw",
]

_INT_FIELDS = {"souls", "children_home", "children_married", "children_total"}
# Nullable integer fields — '' / None stays NULL instead of being coerced to 0.
_NULLABLE_INT_FIELDS = {"priority"}


def _coerce(field: str, val):
    if field in _NULLABLE_INT_FIELDS:
        if val in ("", None):
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None
    if field in _INT_FIELDS:
        try:
            return int(float(val)) if val not in ("", None) else 0
        except (ValueError, TypeError):
            return 0
    return val if val is not None else ""


def _rec_sync_payload(rec_id: int) -> dict:
    """The full recipient row (minus the local numeric id) — the unit the sync
    journal carries so another computer can upsert an identical card by guid."""
    rec = get_recipient(rec_id)
    if not rec:
        return {}
    data = {k: v for k, v in rec.items() if k != "id"}
    return {"guid": rec.get("guid") or "", "data": data}


def split_full_name(full: str):
    """Split a combined name into (first, last). This app's full_name convention
    is FAMILY-FIRST (the import builds 'משפחה פרטי'), so the FIRST whitespace
    token is the family name and the rest is the given name. A single word → it's
    the given name, family blank. The operator can correct any split in the
    recipient form (#aka27). Returns (first_name, last_name)."""
    parts = (full or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[1:]), parts[0]


def join_name(first: str, last: str) -> str:
    """Build full_name from a split, FAMILY-FIRST to match the app convention
    ('משפחה פרטי') so identity/history/printouts are unchanged."""
    return f"{(last or '').strip()} {(first or '').strip()}".strip()


def _apply_name_fields(data: dict) -> dict:
    """Keep full_name / first_name / last_name consistent on every write (#aka27).
    A provided first/last split rebuilds full_name (family-first); a lone
    full_name derives the split. Returns a NEW dict — never mutates the caller's."""
    data = dict(data)
    gave_split = ("first_name" in data) or ("last_name" in data)
    fn = (data.get("first_name") or "").strip()
    ln = (data.get("last_name") or "").strip()
    if gave_split and (fn or ln):
        data["first_name"], data["last_name"] = fn, ln
        data["full_name"] = join_name(fn, ln)
    elif (data.get("full_name") or "").strip():
        f, l = split_full_name(data["full_name"])
        data.setdefault("first_name", f)
        data.setdefault("last_name", l)
    return data


def add_recipient(data: dict) -> int:
    data = _apply_name_fields(data)
    cols = _RECIPIENT_FIELDS
    vals = [_coerce(c, data.get(c, "")) for c in cols]
    sql = f"INSERT INTO recipients ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})"
    guid = (data.get("guid") or "").strip() or uuid.uuid4().hex
    stamp = data.get("updated_at") or _utc_now()
    with get_connection() as conn:
        cur = conn.execute(sql, vals)
        rec_id = cur.lastrowid
        conn.execute("UPDATE recipients SET guid=?, updated_at=?, representative_auto=? WHERE id=?",
                     (guid, stamp, int(data.get("representative_auto") or 0), rec_id))
    _sync_log("rec_upsert", _rec_sync_payload(rec_id))
    return rec_id


def update_recipient(rec_id: int, data: dict):
    data = _apply_name_fields(data)
    old = get_recipient(rec_id)
    tracked_fields = {"status": "סטטוס"}
    cols = [k for k in data if k != "id"]
    if not cols:
        return
    with get_connection() as conn:
        for field, label in tracked_fields.items():
            if field in data and old and str(data[field]) != str(old.get(field, "")):
                conn.execute(
                    "INSERT INTO change_log (recipient_id, recipient_name, field_changed, old_value, new_value) VALUES (?,?,?,?,?)",
                    (rec_id, old["full_name"], label, old.get(field, ""), data[field])
                )
        # A manual edit of the נציג clears the 'שויך אוטומטית' mark — the operator
        # has now decided the community by hand.
        if ("representative" in data and old
                and str(data["representative"]) != str(old.get("representative") or "")
                and "representative_auto" not in data):
            data = dict(data)
            data["representative_auto"] = 0
            cols = [k for k in data if k != "id"]
        sets = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [rec_id]
        conn.execute(f"UPDATE recipients SET {sets} WHERE id=?", vals)
        if "updated_at" not in data:
            conn.execute("UPDATE recipients SET updated_at=? WHERE id=?",
                         (_utc_now(), rec_id))
    _sync_log("rec_upsert", _rec_sync_payload(rec_id))


def delete_recipient(rec_id: int):
    """Delete a recipient. Raises ValueError if they have distribution history."""
    rec = get_recipient(rec_id)
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM distributions WHERE recipient_id=?", (rec_id,)
        ).fetchone()["c"]
        if count > 0:
            raise ValueError(
                f"למקבל זה יש {count} חלוקות בהיסטוריה.\n"
                "לא ניתן למחוק — שנה סטטוס ל'הסתיים' במקום."
            )
        conn.execute("DELETE FROM recipients WHERE id=?", (rec_id,))
    if rec and rec.get("guid"):
        _sync_log("rec_delete", {"guid": rec["guid"], "force": False})


def force_delete_recipient(rec_id: int):
    """Delete a recipient AND all their distribution history. Use with caution."""
    rec = get_recipient(rec_id)
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions WHERE recipient_id=?", (rec_id,))
        conn.execute("DELETE FROM change_log WHERE recipient_id=?", (rec_id,))
        conn.execute("DELETE FROM recipients WHERE id=?", (rec_id,))
    if rec and rec.get("guid"):
        _sync_log("rec_delete", {"guid": rec["guid"], "force": True})


# ─── Next Wednesday + frequency-aware next distribution ───────────────────────

def next_wednesday(from_date: date = None) -> date:
    d = from_date or date.today()
    days_ahead = 2 - d.weekday()  # Wednesday = 2
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def calculate_next_dist(last_date_str: str, frequency: str) -> date:
    """Return the correct next distribution date based on frequency."""
    if not last_date_str:
        # Never served yet: the recipient is due at the UPCOMING distribution
        # (the coming Wednesday, or today if today is Wednesday) — not a week
        # out. Otherwise a regular added on distribution day gets pushed to next
        # week and silently drops off the current list (bug #pv59q).
        if frequency == "חד-פעמי":
            return next_wednesday()
        today = date.today()
        return today if today.weekday() == 2 else next_wednesday(today)
    try:
        last = date.fromisoformat(last_date_str)
    except ValueError:
        last = date.today()

    if frequency == "שבועי":
        return next_wednesday(last + timedelta(days=1))
    elif frequency == "דו-שבועי":
        return next_wednesday(last + timedelta(days=13))
    elif frequency == "חודשי":
        return next_wednesday(last + timedelta(days=29))
    else:
        # חד-פעמי or empty — use next Wednesday from today
        return next_wednesday()


# ─── Weekly distribution list ─────────────────────────────────────────────────

def get_weekly_list(days_ahead: int = 0, area_filter: str = "הכל"):
    """Returns active recurring recipients due by the cutoff, sorted by name.

    By default the window reaches ONLY the upcoming distribution Wednesday
    (inclusive) — so THIS week's list shows just those actually due now. A
    bi-weekly/monthly recipient who was served last week has a next-distribution
    further out and is therefore NOT shown again until their turn. `days_ahead`
    can still widen the window for other callers (reports/tests). The cutoff
    always includes the upcoming Wednesday no matter which weekday the app is
    opened, so the list is never empty on the day-before/day-of distribution.

    "Regular" = anyone who is not one-time: a real recurring frequency, OR marked
    priority 'קבוע' (4) even if the frequency field was left blank — otherwise a
    person tagged קבוע without a frequency would silently drop off the list.
    """
    today = date.today()
    base_wed = today if today.weekday() == 2 else next_wednesday(today)
    cutoff = max(today + timedelta(days=days_ahead), base_wed)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE status='פעיל' "
            "AND frequency != 'חד-פעמי' AND (frequency != '' OR priority = 4) "
            "ORDER BY full_name"
        ).fetchall()
        result = []
        updates = []
        for r in rows:
            r = dict(r)
            if area_filter != "הכל" and r.get("area", "") != area_filter:
                continue
            nd_str = r.get("next_distribution") or ""
            try:
                nd = date.fromisoformat(nd_str) if nd_str else None
            except ValueError:
                nd = None
            if nd is None:
                nd = calculate_next_dist(r.get("last_distribution") or "", r.get("frequency") or "")
                r["next_distribution"] = nd.isoformat()
                updates.append((r["next_distribution"], r["id"]))
            # A never-served active regular is due at the upcoming distribution —
            # never a week out. Self-heals records whose next_distribution was
            # stored a week ahead at add-time (bug #pv59q: a קבוע added on the
            # distribution day would otherwise not show on this week's list).
            if not (r.get("last_distribution") or "").strip() and nd != base_wed:
                nd = base_wed
                r["next_distribution"] = nd.isoformat()
                updates.append((r["next_distribution"], r["id"]))
            r["_status"] = r.get("weekly_status", "") or ""
            r["days_left"] = (nd - today).days
            # A regular is on this week's list if their turn is due by the cutoff,
            # OR they were already served for THIS week's cycle — so recording a
            # distribution to a regular doesn't make them vanish the same week and
            # you can still hand them another round (bug 2).
            ld_str2 = r.get("last_distribution") or ""
            try:
                ld2 = date.fromisoformat(ld_str2) if ld_str2 else None
            except ValueError:
                ld2 = None
            # "Served for this cycle" = last_distribution falls anywhere from the
            # last 6 days up to the UPCOMING distribution Wednesday (base_wed).
            # Including that near-future window is essential: the operator normally
            # dates a distribution on the coming Wednesday, which pushes
            # next_distribution a week out — without this the regular would vanish
            # from the list the instant the distribution is saved (bug: קבועים
            # disappear after one distribution). Dates BEYOND base_wed (a real
            # data-entry error) are still excluded, so a stray far-future date
            # can't pin someone to every week's list forever.
            served_recently = (ld2 is not None
                               and (today - timedelta(days=6)) <= ld2 <= base_wed)
            if nd <= cutoff or served_recently:
                result.append(r)
        if updates:
            conn.executemany("UPDATE recipients SET next_distribution=? WHERE id=?", updates)
    return sorted(result, key=lambda x: x["full_name"])


# ------------------------------------------------------------------------------- One-time recipients ──────────────────────────────────────────────────────

# ─── Need-score (priority ranking within a tier) ──────────────────────────────
# The scoring logic itself (factors, parsing, normalization) is pure business
# logic and lives in scoring.py. This module keeps only the DB side (reading /
# writing the user-tunable weights) plus re-exports so existing callers and
# tests keep working via `db.NEED_FACTORS`, `db._need_num`, etc.
import scoring
import selection
from scoring import (NEED_FACTORS, DEFAULT_NEED_WEIGHTS, PRIORITY_TIERS,
                     _need_num, _norm)


def get_need_weights() -> dict:
    """Return the per-factor need-score weights {key: float}, read from settings
    and falling back to DEFAULT_NEED_WEIGHTS for any missing/invalid value."""
    with get_connection() as conn:
        stored = {row["key"]: row["value"] for row in
                  conn.execute("SELECT key, value FROM settings WHERE key LIKE 'need_w_%'")}
    weights = {}
    for f in NEED_FACTORS:
        raw = stored.get("need_w_" + f["key"])
        try:
            w = float(raw)
            w = 0.0 if w < 0 else w
        except (TypeError, ValueError):
            w = DEFAULT_NEED_WEIGHTS.get(f["key"], 0.0)
        weights[f["key"]] = w
    return weights


def set_need_weights(weights: dict):
    """Persist need-score weights. Accepts a {key: number} dict (keys from
    NEED_FACTORS); negatives clamp to 0, unknown keys are ignored."""
    valid = {f["key"] for f in NEED_FACTORS}
    with get_connection() as conn:
        for key, val in weights.items():
            if key not in valid:
                continue
            try:
                w = max(0.0, float(val))
            except (TypeError, ValueError):
                continue
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                         ("need_w_" + key, str(w)))


def recency_days(rec: dict, today: date = None) -> int:
    """Days used for the ותק (recency) need factor. Counts from the last
    distribution; for someone who NEVER received, from their REGISTRATION date
    (start_date, falling back to created_at) — NOT an arbitrary year-2000 epoch,
    which made every never-served recipient look 26 years overdue and flattened
    the recency scale for everyone who HAS received. So a freshly-registered
    recipient starts with little 'waiting' credit and earns it over time, while a
    veteran who registered long ago and never received ranks as genuinely overdue.
    A future date (data-entry error) clamps to 0, never a negative wait."""
    today = today or date.today()
    for key in ("last_distribution", "start_date", "created_at"):
        s = str(rec.get(key) or "").strip()
        if not s:
            continue
        try:
            d = date.fromisoformat(s[:10])   # created_at is 'YYYY-MM-DD HH:MM:SS'
        except ValueError:
            continue
        return max(0, (today - d).days)
    return 0


def get_one_time_list(area_filter: str = "הכל"):
    """One-time recipients ranked for the priority distribution: priority-3 first
    then priority-2, each ordered by need-score (desc). Other codes
    (1/0/none/חובת בירור) are kept visible but listed afterwards, by recency."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE status='פעיל' AND frequency='חד-פעמי' ORDER BY full_name"
        ).fetchall()
    result = []
    for r in rows:
        r = dict(r)
        if area_filter != "הכל" and r.get("area", "") != area_filter:
            continue
        ld_str = r.get("last_distribution") or ""
        try:
            ld = date.fromisoformat(ld_str) if ld_str else date(2000, 1, 1)
        except ValueError:
            ld = date(2000, 1, 1)
        r["last_dist_date"] = ld
        r["days_since"] = recency_days(r)
        r["in_distribution"] = r.get("priority") in PRIORITY_TIERS
        result.append(r)

    in_dist = [r for r in result if r["in_distribution"]]
    others = [r for r in result if not r["in_distribution"]]
    # RULE 1 (one-time priority distribution): priority DOMINATES — every ראשונה(3)
    # before every שנייה(2), need-score orders only WITHIN a tier. Ranking lives in
    # the pure selection core (distinct from the merged scored mode's pure-score).
    in_dist = selection.rank_one_time_priority(in_dist, get_need_weights())
    for r in others:
        r["need_score"] = None
    others.sort(key=lambda x: (x["last_dist_date"], -(x.get("souls") or 0)))
    return in_dist + others


def get_regulars_scored(area_filter: str = "הכל"):
    """Regulars (frequency != חד-פעמי / not empty) ranked by need-score for the
    'קבועים לפי ניקוד' distribution mode: every active regular gets a need_score
    (same scoring the one-time list uses) and the list is ordered by that score
    (desc), NOT by the schedule. Each row is flagged `_scored_regular` so the UI
    can style/label it distinctly."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE status='פעיל' "
            "AND frequency != 'חד-פעמי' AND (frequency != '' OR priority = 4) "
            "ORDER BY full_name"
        ).fetchall()
    result = []
    for r in rows:
        r = dict(r)
        if area_filter != "הכל" and r.get("area", "") != area_filter:
            continue
        ld_str = r.get("last_distribution") or ""
        try:
            ld = date.fromisoformat(ld_str) if ld_str else date(2000, 1, 1)
        except ValueError:
            ld = date(2000, 1, 1)
        r["last_dist_date"] = ld
        r["days_since"] = recency_days(r)
        r["_scored_regular"] = True
        result.append(r)
    # Highest need first, ties by NAME only — the one pure ranking used everywhere.
    return selection.rank_by_need(result, get_need_weights())


def get_scored_all(area_filter: str = "הכל"):
    """Merged need-score ranking of EVERYONE active in a distribution — the
    regulars AND the one-time priority candidates — scored on ONE shared scale
    and ordered by need (highest first). This powers the 'קבועים לפי ניקוד' mode,
    where both groups compete for the same portions by their need-score.

    Included: every active regular (recurring, or priority 4 = קבוע), plus every
    active one-timer whose priority is a distribution tier (3/2). Data-only rows
    (empty frequency and not קבוע, or one-timers with no distribution priority)
    are excluded. Regulars are flagged `_scored_regular`; one-timers keep their
    'חד-פעמי' frequency so the UI tints them distinctly."""
    today = date.today()
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM recipients WHERE status='פעיל'").fetchall()
    result = []
    for r in rows:
        r = dict(r)
        if area_filter != "הכל" and r.get("area", "") != area_filter:
            continue
        freq = r.get("frequency") or ""
        if freq == "חד-פעמי":
            if r.get("priority") not in PRIORITY_TIERS:
                continue                      # one-timer not up for distribution
        elif freq != "" or r.get("priority") == 4:
            r["_scored_regular"] = True        # a regular
        else:
            continue                           # data-only row
        ld_str = r.get("last_distribution") or ""
        try:
            ld = date.fromisoformat(ld_str) if ld_str else date(2000, 1, 1)
        except ValueError:
            ld = date(2000, 1, 1)
        r["last_dist_date"] = ld
        r["days_since"] = recency_days(r, today)
        result.append(r)
    # Highest need first, ties by NAME only — the one pure ranking used everywhere.
    return selection.rank_by_need(result, get_need_weights())


def get_regulars_mode() -> str:
    """Distribution mode for regulars: 'schedule' (default — auto by timetable),
    'none' (regulars excluded), 'scored' (regulars only, ranked by need-score) or
    'filter' (a custom broad filter over ALL active recipients — see
    get_filtered_list). 'all' (EVERYONE ranked by need) is a legacy value that was
    dropped from the picker on 26/08 (#7ycrg); it maps back to 'schedule'."""
    mode = get_setting("dist_regulars_mode") or "schedule"
    if mode == "all":
        return "schedule"
    return mode if mode in ("schedule", "none", "scored", "filter") else "schedule"


# ─── Custom broad filter (mode 'filter') ─────────────────────────────────────
def get_filter_criteria() -> dict:
    """The persisted broad-filter thresholds (mode 'filter'), as
    {field: {'min': float|None, 'max': float|None}}. Empty dict if never set."""
    raw = get_setting("dist_filter_criteria")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def set_filter_criteria(criteria: dict):
    """Persist the broad-filter thresholds as JSON."""
    set_setting("dist_filter_criteria", json.dumps(criteria or {}))


def get_filtered_list(criteria: dict = None, area_filter: str = "הכל"):
    """The distribution list for the custom 'filter' mode: every ACTIVE recipient
    that satisfies the numeric thresholds (priority/frequency are ignored — this
    is a deliberate broad filter over the whole list). Rows are need-scored and
    ordered by need (highest first) so limited products go to the neediest of the
    matching set; clicking a name still shows the score breakdown.

    Community balance (#lejmr): when the criteria carry balance_communities=True
    (the default) AND a products count is set, the pick is split between
    communities (by שם נציג) — each community gets a share proportional to its
    size (or the operator-pinned percent from settings), filled from its own
    members. Whoever falls off because of the balance is simply not listed."""
    if criteria is None:
        criteria = get_filter_criteria()
    rows = get_all_recipients(status_filter="פעיל")
    if area_filter != "הכל":
        rows = [r for r in rows if r.get("area", "") == area_filter]
    for r in rows:
        r["days_since"] = recency_days(r)
        r["_filtered"] = True
    balance = (criteria or {}).get("balance_communities", True)
    try:
        products = int(get_setting("available_products") or 0)
    except (TypeError, ValueError):
        products = 0
    if balance and products > 0:
        return selection.balance_by_community(
            rows, criteria, get_need_weights(), products, get_community_quotas())
    rows = selection.filter_by_criteria(rows, criteria)
    return selection.rank_by_need(rows, get_need_weights())


# ─── Communities (שם נציג) — balance data + auto-assignment ──────────────────

def get_communities() -> list:
    """Sorted distinct נציג names across ACTIVE recipients (blank excluded)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT TRIM(representative) AS rep FROM recipients "
            "WHERE status='פעיל' AND TRIM(COALESCE(representative,'')) != '' "
            "ORDER BY rep COLLATE NOCASE").fetchall()
    return [r["rep"] for r in rows]


def get_community_sizes() -> dict:
    """{נציג: active member count}, including '' for the rep-less group."""
    sizes = {}
    for r in get_all_recipients(status_filter="פעיל"):
        sizes[selection.community_key(r)] = sizes.get(selection.community_key(r), 0) + 1
    return sizes


def get_no_community(status_filter: str = "פעיל") -> list:
    """Active recipients that have NO נציג — the group the operator can assign
    (manually or by the synagogue-majority auto-fill)."""
    return [r for r in get_all_recipients(status_filter=status_filter)
            if not selection.community_key(r)]


def get_community_quotas() -> dict:
    """Operator-pinned percent per community, {נציג: percent}. Communities not
    listed split the leftover percent proportionally to size (see selection)."""
    raw = get_setting("community_quotas")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: float(v) for k, v in data.items()
                if isinstance(v, (int, float)) and float(v) > 0} if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def set_community_quotas(quotas: dict):
    set_setting("community_quotas", json.dumps(quotas or {}, ensure_ascii=False))


def apply_inferred_representatives() -> int:
    """Auto-assign a community to rep-less recipients by their synagogue's
    majority נציג (selection.infer_communities). Writes the נציג to the card
    marked representative_auto=1 — visible and correctable by the operator.
    Returns how many cards were filled."""
    rows = get_all_recipients(status_filter="פעיל")
    suggestions = selection.infer_communities(rows)
    for rid, rep in suggestions.items():
        update_recipient(rid, {"representative": rep, "representative_auto": 1})
    return len(suggestions)


def compute_suggested_n(total_products: int) -> tuple[int, int]:
    """Returns (n_for_one_time, regular_count). Regulars are served first; the
    rest of the products go to the one-time priority list. In 'none'/'scored'
    modes regulars are no longer auto-served first, so regular_count is 0 and all
    products feed the list.

    regular_count counts ONLY the regulars actually due on THIS week's list (the
    same set get_weekly_list shows), NOT every active regular — a bi-weekly or
    monthly recipient who isn't due this week doesn't consume a portion now, so
    counting them would wrongly reserve products away from the one-time list."""
    if get_regulars_mode() != "schedule":
        return max(0, total_products), 0
    regular_count = len(get_weekly_list())
    n = max(0, total_products - regular_count)
    return n, regular_count


# ─── Distributions (history) ─────────────────────────────────────────────────

def bulk_add_distributions(records: list[dict], dist_date: str, what_dist: str,
                           quantity, distributor: str,
                           dist_name: str = "", general_note: str = "",
                           not_received: list[dict] = None):
    """Add many distributions at once and update recipients' last/next distribution.

    Also records ONE batch row (the distribution event) that the "חלוקות" tab
    lists — capturing the shared header, the multi-product breakdown (carried in
    `what_dist`), and a single general note for the whole distribution. Each
    per-recipient row links back to the batch via batch_id. Returns the batch id.

    `not_received` is the optional list of recipients who were on the list but did
    NOT get the distribution (recorded no-shows). They are written as rows with
    received=0 under the same batch, but their last/next distribution is left
    UNTOUCHED: a no-show didn't get anything, so their seniority clock keeps
    running and they stay due for the next round."""
    not_received = not_received or []
    souls_total = 0
    for rec in records:
        try:
            souls_total += int(rec.get("souls", 0) or 0)
        except (ValueError, TypeError):
            pass
    sync_rows = []
    with get_connection() as conn:
        batch_guid = uuid.uuid4().hex
        cur = conn.execute(
            "INSERT INTO dist_batches "
            "(dist_name, dist_date, products, quantity, distributor, general_note, "
            " recipient_count, souls_total, guid) VALUES (?,?,?,?,?,?,?,?,?)",
            (dist_name or "", dist_date, what_dist, quantity or 0, distributor or "",
             general_note or "", len(records), souls_total, batch_guid)
        )
        batch_id = cur.lastrowid

        def _rec_guid(conn, rec):
            rid = rec.get("id")
            if rid is None:
                return ""
            row = conn.execute("SELECT guid FROM recipients WHERE id=?", (rid,)).fetchone()
            return (row["guid"] if row else "") or ""

        for rec in records:
            row_guid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO distributions "
                "(recipient_id, recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes, batch_id, received, guid) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                (rec.get("id"), rec.get("full_name", ""), dist_date,
                 rec.get("area", ""), rec.get("souls", 0),
                 what_dist, quantity, distributor,
                 rec.get("notes", ""), batch_id, row_guid)
            )
            freq = rec.get("frequency", "")
            nw = "" if freq == "חד-פעמי" else calculate_next_dist(dist_date, freq).isoformat()
            # Reset the weekly checkmark — it belongs to the cycle that just ended,
            # so it must not bleed into the next week's distribution list.
            conn.execute(
                "UPDATE recipients SET last_distribution=?, next_distribution=?, weekly_status='' WHERE id=?",
                (dist_date, nw, rec.get("id"))
            )
            sync_rows.append({"guid": row_guid, "rec_guid": _rec_guid(conn, rec),
                              "recipient_name": rec.get("full_name", ""),
                              "area": rec.get("area", ""), "souls": rec.get("souls", 0),
                              "notes": rec.get("notes", ""), "received": 1,
                              "frequency": rec.get("frequency", "")})
        # No-shows: record the fact (received=0) WITHOUT advancing their dates.
        for rec in not_received:
            row_guid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO distributions "
                "(recipient_id, recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes, batch_id, received, guid) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
                (rec.get("id"), rec.get("full_name", ""), dist_date,
                 rec.get("area", ""), rec.get("souls", 0),
                 what_dist, 0, distributor,
                 rec.get("notes", ""), batch_id, row_guid)
            )
            sync_rows.append({"guid": row_guid, "rec_guid": _rec_guid(conn, rec),
                              "recipient_name": rec.get("full_name", ""),
                              "area": rec.get("area", ""), "souls": rec.get("souls", 0),
                              "notes": rec.get("notes", ""), "received": 0,
                              "frequency": rec.get("frequency", "")})
    _sync_log("batch_add", {
        "guid": batch_guid,
        "batch": {"dist_name": dist_name or "", "dist_date": dist_date,
                  "products": what_dist, "quantity": quantity or 0,
                  "distributor": distributor or "", "general_note": general_note or "",
                  "recipient_count": len(records), "souls_total": souls_total},
        "rows": sync_rows,
    })
    return batch_id


def get_distribution_batches(limit: int = 500):
    """Every distribution event (batch), newest first — one row per distribution
    for the 'חלוקות' tab."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM dist_batches ORDER BY dist_date DESC, id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_no_show_threshold() -> int:
    """How many consecutive recorded no-shows earn a warning badge (v2.60).
    Operator-tunable in Settings; 0 disables the warnings entirely."""
    try:
        return max(0, int(get_setting("no_show_alert_threshold") or 3))
    except (TypeError, ValueError):
        return 3


def no_show_streaks(rec_ids) -> dict:
    """{recipient_id: N} — the CURRENT run of consecutive recorded no-shows
    (received=0) for each requested recipient, counted from their most recent
    history row backwards and broken by the first actual receipt. Recipients
    with no streak (last row is a receipt, or no history) are omitted."""
    ids = [int(i) for i in rec_ids if i is not None]
    if not ids:
        return {}
    out = {}
    done = set()
    with get_connection() as conn:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT recipient_id, received FROM distributions "
            f"WHERE recipient_id IN ({marks}) "
            f"ORDER BY dist_date DESC, id DESC", ids).fetchall()
    for row in rows:
        rid = row["recipient_id"]
        if rid in done:
            continue
        if (row["received"] if row["received"] is not None else 1) == 0:
            out[rid] = out.get(rid, 0) + 1
        else:
            done.add(rid)   # streak broken by an actual receipt
    return {k: v for k, v in out.items() if v > 0}


def consecutive_no_shows(rec_id: int) -> int:
    """The single-recipient form of no_show_streaks()."""
    return no_show_streaks([rec_id]).get(rec_id, 0)


def get_batch_recipients(batch_id: int):
    """The per-recipient rows recorded under one batch (who received)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM distributions WHERE batch_id=? ORDER BY recipient_name COLLATE NOCASE",
            (batch_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_batch_export_rows(batch_id: int) -> list[dict]:
    """Full recipient details for every person recorded under one batch, joined
    from the recipients table, plus a `received` flag and the batch header info
    (#dancj). A history row whose recipient was since deleted still exports with
    the name/area stored on the history row itself."""
    with get_connection() as conn:
        batch = conn.execute("SELECT * FROM dist_batches WHERE id=?", (batch_id,)).fetchone()
        drows = conn.execute(
            "SELECT * FROM distributions WHERE batch_id=? ORDER BY received DESC, "
            "recipient_name COLLATE NOCASE", (batch_id,)).fetchall()
        out = []
        for d in drows:
            rec = None
            if d["recipient_id"] is not None:
                rec = conn.execute("SELECT * FROM recipients WHERE id=?",
                                   (d["recipient_id"],)).fetchone()
            merged = dict(rec) if rec else {}
            merged["full_name"] = d["recipient_name"] or (merged.get("full_name") or "")
            merged.setdefault("area", d["area"] or "")
            merged.setdefault("souls", d["souls"] or 0)
            merged["received"] = d["received"] if d["received"] is not None else 1
            merged["_batch_name"] = (batch["dist_name"] if batch else "") or ""
            merged["_batch_date"] = (batch["dist_date"] if batch else "") or ""
            merged["notes"] = d["notes"] or merged.get("notes", "")
            out.append(merged)
        return out


def get_all_history_export_rows() -> list[dict]:
    """Full recipient details for EVERY recorded distribution across all batches
    (#dancj), newest batch first. Each row carries its batch name/date and the
    received flag, so the whole history can be reviewed in one sheet."""
    out = []
    for b in get_distribution_batches():
        out.extend(get_batch_export_rows(b["id"]))
    return out


def find_matching_batch(dist_date, dist_name, recipient_ids):
    """Return an existing batch (dict) that looks like the SAME distribution round
    as one about to be imported — same dist_date AND same dist_name AND at least
    one overlapping recorded recipient — else None.

    Read-only. Used to WARN before a volunteer checklist is imported a second time
    (bug H2: the import had no idempotency guard, so a round sent/imported twice
    silently produced duplicate history rows and double-advanced dates). It never
    blocks or deletes anything — the caller decides what to do. Dates and names are
    compared trimmed, so a blank name only matches a blank name (never a catch-all).
    A different name OR a different date OR zero recipient overlap → not a match
    (a legitimately different distribution is never flagged)."""
    dd = (dist_date or "").strip()
    dn = (dist_name or "").strip()
    ids = set()
    for i in (recipient_ids or []):
        try:
            ids.add(int(i))
        except (TypeError, ValueError):
            pass
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM dist_batches "
            "WHERE TRIM(COALESCE(dist_date,''))=? AND TRIM(COALESCE(dist_name,''))=? "
            "ORDER BY id DESC",
            (dd, dn)).fetchall()
        for b in rows:
            if not ids:
                return dict(b)   # same date+name and no ids to compare → a match
            recorded = conn.execute(
                "SELECT recipient_id FROM distributions WHERE batch_id=?",
                (b["id"],)).fetchall()
            batch_ids = {r["recipient_id"] for r in recorded
                         if r["recipient_id"] is not None}
            if ids & batch_ids:
                return dict(b)
    return None


def _recompute_recipient_dates(conn, rec_id):
    """Re-derive a recipient's last_distribution / next_distribution from the
    distribution rows that REMAIN for them, after some history was deleted.

    This keeps the two stores in sync: the `distributions` history table and the
    denormalized `recipients.last_distribution` field. Without it, deleting a
    distribution left the recipient's last_distribution pointing at an event that
    no longer exists — so the one-time / weekly lists still showed them as
    "received" on a date whose record was gone (the 'two data sources out of
    sync' bug). last becomes the newest remaining dist_date (or empty if none);
    next is recomputed from it by the recipient's frequency."""
    row = conn.execute("SELECT frequency FROM recipients WHERE id=?", (rec_id,)).fetchone()
    if not row:
        return
    freq = row["frequency"] or ""
    # received=1 only: a recorded no-show must never become someone's
    # "last distribution" — they didn't actually receive anything.
    last_row = conn.execute(
        "SELECT MAX(dist_date) AS m FROM distributions WHERE recipient_id=? AND received=1", (rec_id,)
    ).fetchone()
    last = (last_row["m"] if last_row else "") or ""
    if last and freq and freq != "חד-פעמי":
        nxt = calculate_next_dist(last, freq).isoformat()
    else:
        nxt = ""
    conn.execute("UPDATE recipients SET last_distribution=?, next_distribution=? WHERE id=?",
                 (last, nxt, rec_id))


def delete_batch(batch_id: int):
    """Delete a distribution batch AND its per-recipient history rows, then roll
    back each affected recipient's last/next distribution to whatever history
    REMAINS (keeps the denormalized dates in sync with the history table)."""
    with get_connection() as conn:
        row = conn.execute("SELECT guid FROM dist_batches WHERE id=?", (batch_id,)).fetchone()
        batch_guid = (row["guid"] if row else "") or ""
        rec_ids = [r["recipient_id"] for r in conn.execute(
            "SELECT DISTINCT recipient_id FROM distributions "
            "WHERE batch_id=? AND recipient_id IS NOT NULL", (batch_id,))]
        conn.execute("DELETE FROM distributions WHERE batch_id=?", (batch_id,))
        conn.execute("DELETE FROM dist_batches WHERE id=?", (batch_id,))
        for rid in rec_ids:
            _recompute_recipient_dates(conn, rid)
    if batch_guid:
        _sync_log("batch_delete", {"guid": batch_guid})


def delete_distribution(dist_id: int):
    """Delete a single distribution history record by its id. Used by the search
    tab to remove stray/old records (including legacy rows that carry no batch
    link and so can't be removed from the 'חלוקות' batch view). Rolls back the
    recipient's last/next distribution to the remaining history."""
    with get_connection() as conn:
        row = conn.execute("SELECT recipient_id, guid FROM distributions WHERE id=?",
                           (dist_id,)).fetchone()
        conn.execute("DELETE FROM distributions WHERE id=?", (dist_id,))
        if row and row["recipient_id"] is not None:
            _recompute_recipient_dates(conn, row["recipient_id"])
    if row and (row["guid"] or ""):
        _sync_log("dist_delete", {"guid": row["guid"]})


def get_distributions(recipient_name: str = None, limit: int = 1000):
    with get_connection() as conn:
        if recipient_name:
            rows = conn.execute(
                "SELECT * FROM distributions WHERE recipient_name=? ORDER BY dist_date DESC LIMIT ?",
                (recipient_name, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM distributions ORDER BY dist_date DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_distributions_for_recipient(rec_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM distributions WHERE recipient_id=? ORDER BY dist_date DESC",
            (rec_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── Change log ───────────────────────────────────────────────────────────────

def get_change_log(limit: int = 200):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM change_log ORDER BY changed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─── Team chat (#ya4f7) ───────────────────────────────────────────────────────

def add_message(body: str, author_name: str = "", author_device: str = "",
                guid: str = "", created_at: str = "") -> int:
    """Post one chat message and journal it for the other computers. Returns the
    local row id. author_name/device come from the sync identity (passed by the
    UI, which already imports the sync module)."""
    body = (body or "").strip()
    if not body:
        return 0
    guid = (guid or "").strip() or uuid.uuid4().hex
    created_at = created_at or _utc_now()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (guid, author_device, author_name, body, created_at) "
            "VALUES (?,?,?,?,?)", (guid, author_device, author_name, body, created_at))
        mid = cur.lastrowid
    _sync_log("msg_add", {"guid": guid, "author_device": author_device,
                          "author_name": author_name, "body": body,
                          "created_at": created_at})
    return mid


def delete_message(guid: str) -> bool:
    """Delete a chat message (its author removes it) and journal the removal so it
    disappears on the other computers too (#msgdel). Idempotent by guid."""
    guid = (guid or "").strip()
    if not guid:
        return False
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM messages WHERE guid=?", (guid,))
        deleted = cur.rowcount > 0
    if deleted:
        _sync_log("msg_delete", {"guid": guid})
    return deleted


def get_messages(limit: int = 400):
    """Return the most recent chat messages in chronological order (oldest first)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY created_at ASC, id ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def messages_after(ts: str, exclude_device: str = ""):
    """Messages created strictly after `ts` (UTC iso), optionally excluding this
    device's own — used to count unread for the tab badge."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE created_at > ? AND author_device <> ? "
            "ORDER BY created_at ASC", (ts or "", exclude_device or "")).fetchall()
        return [dict(r) for r in rows]


def set_read_marker(device: str, device_name: str, read_ts: str):
    """Record (and journal) that `device` has read the chat up to `read_ts`.
    Only advances forward; a no-op if we already knew of an equal/newer read.
    Powers the ✓✓ read receipts (#ya4f7)."""
    if not device or not read_ts:
        return
    with get_connection() as conn:
        row = conn.execute("SELECT read_ts FROM message_reads WHERE device=?",
                           (device,)).fetchone()
        if row and (row["read_ts"] or "") >= read_ts:
            return
        conn.execute(
            "INSERT INTO message_reads (device, device_name, read_ts) VALUES (?,?,?) "
            "ON CONFLICT(device) DO UPDATE SET device_name=excluded.device_name, "
            "read_ts=excluded.read_ts",
            (device, device_name or "", read_ts))
    _sync_log("msg_read", {"device": device, "device_name": device_name or "",
                           "read_ts": read_ts})


def latest_other_read_ts(exclude_device: str = "") -> str:
    """The newest read_ts among OTHER devices — a message created at/before it has
    been seen by the team (→ ✓✓)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(read_ts) AS m FROM message_reads WHERE device <> ?",
            (exclude_device or "",)).fetchone()
        return (row["m"] or "") if row else ""


# ─── Manager change-log + undo (#5rhe9) ───────────────────────────────────────

def get_recipient_by_guid(guid: str):
    if not guid:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM recipients WHERE guid=?", (guid,)).fetchone()
        return dict(row) if row else None


def get_incoming_log(limit: int = 200, include_undone: bool = True):
    """Changes received FROM another computer (for the manager's review/undo)."""
    with get_connection() as conn:
        q = "SELECT * FROM sync_incoming"
        if not include_undone:
            q += " WHERE undone=0"
        q += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in conn.execute(q, (limit,))]


def undo_incoming(incoming_id: int):
    """Revert a change another computer made (#5rhe9). The revert is a normal
    local write, so it syncs back and (being newer) overrides the change on every
    computer. Returns (ok, message)."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM sync_incoming WHERE id=?",
                           (incoming_id,)).fetchone()
        if not row:
            return False, "השינוי לא נמצא"
        if row["undone"]:
            return False, "השינוי כבר בוטל"
        row = dict(row)
    op = row["op"]
    guid = row["target_guid"] or ""
    try:
        before = json.loads(row["before_json"] or "null")
    except (ValueError, TypeError):
        before = None
    try:
        if op == "rec_upsert":
            local = get_recipient_by_guid(guid)
            if before is None:
                # The other computer ADDED this recipient → undo = remove it.
                if local:
                    try:
                        delete_recipient(local["id"])
                    except ValueError:
                        force_delete_recipient(local["id"])
            else:
                fields = {k: v for k, v in before.items()
                          if k not in ("id", "updated_at", "created_at")}
                if local:
                    update_recipient(local["id"], fields)
                else:
                    add_recipient(before)          # vanished locally → recreate
        elif op == "rec_delete":
            if before is not None and not get_recipient_by_guid(guid):
                add_recipient(before)              # restore the deleted recipient
        else:
            return False, "סוג שינוי זה אינו נתמך לביטול"
    except Exception as e:                          # noqa: BLE001 — surface to UI
        return False, f"שגיאה בביטול: {e}"
    with get_connection() as conn:
        conn.execute("UPDATE sync_incoming SET undone=1 WHERE id=?", (incoming_id,))
    return True, "השינוי בוטל והוחזר המצב הקודם"


# ─── Summary stats ────────────────────────────────────────────────────────────

def get_summary():
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    with get_connection() as conn:
        active = conn.execute("SELECT COUNT(*) as c FROM recipients WHERE status='פעיל'").fetchone()["c"]
        suspended = conn.execute("SELECT COUNT(*) as c FROM recipients WHERE status='מושהה'").fetchone()["c"]
        ended = conn.execute("SELECT COUNT(*) as c FROM recipients WHERE status='הסתיים'").fetchone()["c"]
        total_souls = conn.execute(
            "SELECT COALESCE(SUM(souls),0) as s FROM recipients WHERE status='פעיל'"
        ).fetchone()["s"]
        # Stats count actual receipts only — recorded no-shows (received=0) are
        # not distributions that happened.
        dists_month = conn.execute(
            "SELECT COUNT(*) as c FROM distributions WHERE dist_date >= ? AND received=1", (month_start,)
        ).fetchone()["c"]
        dists_total = conn.execute("SELECT COUNT(*) as c FROM distributions WHERE received=1").fetchone()["c"]

        overdue = conn.execute(
            "SELECT COUNT(*) as c FROM recipients "
            "WHERE status='פעיל' AND frequency != 'חד-פעמי' AND frequency != '' "
            "AND next_distribution != '' "
            "AND date(next_distribution) < date('now')"
        ).fetchone()["c"]

        by_freq = conn.execute(
            "SELECT frequency, COUNT(*) as c, COALESCE(SUM(souls),0) as s "
            "FROM recipients WHERE status='פעיל' GROUP BY frequency"
        ).fetchall()
        by_area = conn.execute(
            "SELECT area, COUNT(*) as c FROM recipients WHERE status='פעיל' GROUP BY area"
        ).fetchall()

    return {
        "active": active, "suspended": suspended, "ended": ended,
        "total_souls": total_souls, "dists_month": dists_month, "dists_total": dists_total,
        "overdue": overdue,
        "by_freq": [dict(r) for r in by_freq],
        "by_area": [dict(r) for r in by_area],
    }


# ─── Reset ───────────────────────────────────────────────────────────────────

def reset_all_data():
    """Delete ALL recipients, distributions, distribution batches, and change_log.
    Settings are kept. dist_batches must be cleared too — otherwise a reset leaves
    orphaned batch rows behind, so the 'חלוקות' tab keeps showing phantom
    distributions whose per-recipient rows are already gone (bug H1)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions")
        conn.execute("DELETE FROM dist_batches")
        conn.execute("DELETE FROM change_log")
        conn.execute("DELETE FROM recipients")


# ─── Import helpers ───────────────────────────────────────────────────────────

def import_recipients_from_list(rows: list[dict]) -> tuple[int, int, list[dict]]:
    """Bulk import - adds new records; for existing ones, fills only empty fields.
    Returns (added, updated, conflicts) counts."""
    updatable = ["phone1", "phone2", "phone3", "address", "area", "souls",
                 "frequency", "start_date", "last_distribution", "next_distribution",
                 "external_id", "source", "birth_date", "spouse_birth_date",
                 "id_number", "spouse_id_number",
                 "children_home", "children_married", "children_total",
                 "marital_status", "email", "synagogue",
                 "housing_expenses", "medical_expenses", "income", "per_soul",
                 "work_scope", "parent_type", "occupation", "representative",
                 "priority", "priority_raw"]
    phone_fields = ("phone1", "phone2", "phone3")

    def _is_empty(val) -> bool:
        return not val or str(val) in ("", "0", "None")

    def _clean_phone(val) -> str:
        digits = "".join(ch for ch in str(val or "") if ch.isdigit())
        if len(digits) == 9:
            digits = "0" + digits
        return digits

    with get_connection() as conn:
        existing = {}
        for r in conn.execute("SELECT * FROM recipients").fetchall():
            existing[r["full_name"]] = dict(r)

        added = 0
        updated = 0
        conflicts = []
        for row_idx, row in enumerate(rows, start=1):
            name = (row.get("full_name") or "").strip()
            if not name:
                continue

            if name in existing:
                ex = existing[name]
                conflict_reason = ""
                for field in phone_fields:
                    new_phone = _clean_phone(row.get(field))
                    old_phone = _clean_phone(ex.get(field))
                    if new_phone and old_phone and new_phone != old_phone:
                        conflict_reason = f"טלפון סותר בשדה {field}"
                        break
                if conflict_reason:
                    conflicts.append({
                        "row": row_idx,
                        "full_name": name,
                        "reason": conflict_reason,
                        "existing_phone1": ex.get("phone1", ""),
                        "existing_phone2": ex.get("phone2", ""),
                        "existing_phone3": ex.get("phone3", ""),
                        "incoming_phone1": row.get("phone1", ""),
                        "incoming_phone2": row.get("phone2", ""),
                        "incoming_phone3": row.get("phone3", ""),
                    })
                    continue

                updates = {}
                for field in updatable:
                    new_val = row.get(field)
                    if not _is_empty(new_val) and _is_empty(ex.get(field)):
                        updates[field] = _coerce(field, new_val) if field == "souls" else new_val
                if updates:
                    sets = ", ".join(f"{k}=?" for k in updates)
                    vals = list(updates.values()) + [ex["id"]]
                    conn.execute(f"UPDATE recipients SET {sets} WHERE id=?", vals)
                    ex.update(updates)
                    updated += 1
            else:
                row = _apply_name_fields(row)   # derive first/last (#aka27)
                insert_cols = _RECIPIENT_FIELDS
                insert_vals = [_coerce(c, row.get(c, "")) for c in insert_cols]
                # override full_name and status from parsed values
                idx_name = insert_cols.index("full_name")
                idx_status = insert_cols.index("status")
                insert_vals[idx_name] = name
                if not insert_vals[idx_status]:
                    insert_vals[idx_status] = "פעיל"
                cur = conn.execute(
                    f"INSERT INTO recipients ({','.join(insert_cols)}) "
                    f"VALUES ({','.join(['?']*len(insert_cols))})",
                    insert_vals
                )
                existing[name] = {"id": cur.lastrowid, "full_name": name,
                                  **{c: row.get(c, "") for c in insert_cols if c != "full_name"}}
                added += 1
    return added, updated, conflicts


# Fields an import may change on an EXISTING recipient (name/status excluded —
# name is the match key, status is managed in-app).
_IMPORT_DIFF_FIELDS = [
    "phone1", "phone2", "phone3", "address", "area", "souls", "frequency",
    "external_id", "source", "birth_date", "spouse_birth_date",
    "id_number", "spouse_id_number", "children_home", "children_married",
    "children_total", "marital_status", "email", "synagogue",
    "housing_expenses", "medical_expenses", "income", "per_soul",
    "work_scope", "parent_type", "occupation", "representative",
    "priority", "priority_raw",
]


def _norm_val(field, val) -> str:
    """Normalised string form for change detection (so '0'/''/None and 3 vs '3'
    don't look like edits)."""
    if val is None:
        return ""
    s = str(val).strip()
    if field in _INT_FIELDS or field == "priority":
        if s in ("", "None"):
            return ""
        try:
            return str(int(float(s)))
        except (ValueError, TypeError):
            return s
    return "" if s in ("None",) else s


def diff_incoming_recipients(rows: list[dict]) -> dict:
    """Compare an imported list against the DB WITHOUT writing anything.
    Returns {'new': [row,...], 'updates': [{'id','full_name','changes':
    {field: {'old','new'}}}], 'unmatched_dupes': int}. Matching prefers a
    unique non-empty external_id, else a unique full_name. Used by the import
    confirmation dialog (#hlcmj) so the operator approves changes to existing
    recipients before they are applied."""
    with get_connection() as conn:
        db_rows = [dict(r) for r in conn.execute("SELECT * FROM recipients")]
    by_name = {}
    by_ext = {}
    for r in db_rows:
        by_name.setdefault((r.get("full_name") or "").strip(), []).append(r)
        ext = (r.get("external_id") or "").strip()
        if ext:
            by_ext.setdefault(ext, []).append(r)

    new_rows, updates, dupes = [], [], 0
    for row in rows:
        name = (row.get("full_name") or "").strip()
        if not name:
            continue
        match = None
        ext = (row.get("external_id") or "").strip()
        if ext and len(by_ext.get(ext, [])) == 1:
            match = by_ext[ext][0]
        elif len(by_name.get(name, [])) == 1:
            match = by_name[name][0]
        elif len(by_name.get(name, [])) > 1:
            dupes += 1
            continue
        if match is None:
            new_rows.append(row)
            continue
        changes = {}
        for field in _IMPORT_DIFF_FIELDS:
            if field not in row:
                continue
            new_norm = _norm_val(field, row.get(field))
            old_norm = _norm_val(field, match.get(field))
            # Only a real, non-emptying change counts — never let a blank cell in
            # the file wipe existing data.
            if new_norm and new_norm != old_norm:
                changes[field] = {"old": match.get(field), "new": row.get(field)}
        if changes:
            updates.append({"id": match["id"], "full_name": name, "changes": changes})
    return {"new": new_rows, "updates": updates, "unmatched_dupes": dupes}


def apply_import_confirmed(new_rows: list[dict], updates: list[dict]) -> tuple[int, int]:
    """Apply an import the operator confirmed: insert every row in new_rows and
    apply the approved field changes in updates (each {'id', 'changes': {field:
    {'new':...}}} — the dialog drops fields/rows the operator unchecked). Returns
    (added, updated). Goes through add_recipient/update_recipient so sync + the
    change log see every write."""
    added = 0
    for row in new_rows:
        add_recipient(row)
        added += 1
    updated = 0
    for u in updates:
        fields = {f: _coerce(f, ch["new"]) if f in _INT_FIELDS else ch["new"]
                  for f, ch in u.get("changes", {}).items()}
        if fields:
            update_recipient(u["id"], fields)
            updated += 1
    return added, updated
