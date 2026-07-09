import sqlite3
import sys
import os
import hashlib
import secrets
from datetime import date, datetime, timedelta


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

        # Stage 2: DB itself is bad — restore the best backup we have.
        best, best_score = None, (-1, -1.0)
        if os.path.isdir(BACKUP_DIR):
            for name in os.listdir(BACKUP_DIR):
                if not name.lower().endswith(".db"):
                    continue
                p = os.path.join(BACKUP_DIR, name)
                if not _db_integrity_ok(p):
                    continue
                score = (_db_recipient_count(p), os.path.getmtime(p))
                if score > best_score:
                    best, best_score = p, score
        if best is None:
            return   # nothing to restore from — let init recreate schema

        try:
            corrupt = DB_PATH + ".corrupt.db"
            if os.path.exists(corrupt):
                os.remove(corrupt)
            os.replace(DB_PATH, corrupt)
        except Exception:
            pass
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
        ]
        for col, definition in _migrations:
            if col not in columns:
                conn.execute(f"ALTER TABLE recipients ADD COLUMN {col} {definition}")

        # Distributions: link each per-recipient row to its batch (added later,
        # so an older DB needs the column back-filled as NULL).
        dist_cols = {row["name"] for row in conn.execute("PRAGMA table_info(distributions)")}
        if "batch_id" not in dist_cols:
            conn.execute("ALTER TABLE distributions ADD COLUMN batch_id INTEGER")

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


# ------------------------------------------------------------------------------- Settings ────────────────────────────────────────────────────────────────

def get_setting(key: str) -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""


def set_setting(key: str, value: str):
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))


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


def filter_recipients(rows: list, query: str, limit: int = 500):
    """Filter an already-loaded list of recipient dicts across ALL key fields —
    name, phones, IDs (husband/wife), address, email, etc. A digit query also
    matches phone / ID numbers ignoring spaces and dashes. Empty query returns
    everyone. Results sorted by name. Pure (no DB access) so the search tab can
    cache rows once and filter in-memory on each keystroke."""
    q = (query or "").strip().lower()
    if not q:
        return sorted(rows, key=lambda r: r.get("full_name", ""))[:limit]

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
    return sorted(out, key=lambda r: r.get("full_name", ""))[:limit]


def search_recipients(query: str, limit: int = 500):
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
    with get_connection() as conn:
        for row in rows:
            name = (row.get("full_name") or "").strip()
            if not name or name in ("None", "0"):
                continue
            vals = [_coerce(c, row.get(c, "")) for c in cols]
            vals[i_name] = name
            if not vals[i_status]:
                vals[i_status] = "פעיל"
            conn.execute(sql, vals)
            count += 1
    return count


_RECIPIENT_FIELDS = [
    "full_name", "phone1", "phone2", "phone3", "address", "area",
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


def add_recipient(data: dict) -> int:
    cols = _RECIPIENT_FIELDS
    vals = [_coerce(c, data.get(c, "")) for c in cols]
    sql = f"INSERT INTO recipients ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})"
    with get_connection() as conn:
        cur = conn.execute(sql, vals)
        return cur.lastrowid


def update_recipient(rec_id: int, data: dict):
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
        sets = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [rec_id]
        conn.execute(f"UPDATE recipients SET {sets} WHERE id=?", vals)


def delete_recipient(rec_id: int):
    """Delete a recipient. Raises ValueError if they have distribution history."""
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


def force_delete_recipient(rec_id: int):
    """Delete a recipient AND all their distribution history. Use with caution."""
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions WHERE recipient_id=?", (rec_id,))
        conn.execute("DELETE FROM change_log WHERE recipient_id=?", (rec_id,))
        conn.execute("DELETE FROM recipients WHERE id=?", (rec_id,))


# ─── Next Wednesday + frequency-aware next distribution ───────────────────────

def next_wednesday(from_date: date = None) -> date:
    d = from_date or date.today()
    days_ahead = 2 - d.weekday()  # Wednesday = 2
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def calculate_next_dist(last_date_str: str, frequency: str) -> date:
    """Return the correct next distribution date based on frequency."""
    try:
        last = date.fromisoformat(last_date_str) if last_date_str else date.today()
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

def get_areas() -> list:
    """Distinct non-empty areas present in the data, sorted — so the area filter
    reflects whatever areas actually exist (not a hard-coded pair)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT area FROM recipients "
            "WHERE area IS NOT NULL AND TRIM(area) != '' ORDER BY area"
        ).fetchall()
    return [r[0] for r in rows]


def get_weekly_list(days_ahead: int = 30, area_filter: str = "הכל"):
    """Returns active recurring recipients due by the cutoff, sorted by name.

    The cutoff ALWAYS reaches at least the upcoming distribution Wednesday
    (inclusive), no matter which weekday the app is opened — otherwise, on the
    day-before / day-of distribution (Tue/Wed) every regular whose next
    distribution is that Wednesday would be filtered out and the list would look
    empty. `days_ahead` can still widen the window beyond that for other callers.
    """
    today = date.today()
    base_wed = today if today.weekday() == 2 else next_wednesday(today)
    cutoff = max(today + timedelta(days=days_ahead), base_wed + timedelta(days=1))
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE status='פעיל' "
            "AND frequency != 'חד-פעמי' AND frequency != '' ORDER BY full_name"
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
            r["_status"] = r.get("weekly_status", "") or ""
            r["days_left"] = (nd - today).days
            if nd <= cutoff:
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


def _annotate_need_scores(rows, weights: dict = None):
    """Thin wrapper over scoring.annotate_need_scores — fills in the
    user-configured weights from settings when none are given."""
    if weights is None:
        weights = get_need_weights()
    return scoring.annotate_need_scores(rows, weights)


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
        r["days_since"] = (date.today() - ld).days
        r["in_distribution"] = r.get("priority") in PRIORITY_TIERS
        result.append(r)

    in_dist = [r for r in result if r["in_distribution"]]
    others = [r for r in result if not r["in_distribution"]]
    _annotate_need_scores(in_dist)
    for r in others:
        r["need_score"] = None
    # tier always dominates (3 before 2), then need-score desc
    in_dist.sort(key=lambda x: (-(x.get("priority") or 0), -(x.get("need_score") or 0)))
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
            "AND frequency != 'חד-פעמי' AND frequency != '' ORDER BY full_name"
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
        r["days_since"] = (date.today() - ld).days
        r["_scored_regular"] = True
        result.append(r)
    _annotate_need_scores(result)
    # highest need first; tie-break by longest-waiting then largest family
    result.sort(key=lambda x: (-(x.get("need_score") or 0),
                               -x["days_since"], -(x.get("souls") or 0)))
    return result


def get_regulars_mode() -> str:
    """Distribution mode for regulars: 'schedule' (default, auto by timetable),
    'none' (regulars excluded) or 'scored' (regulars ranked by need-score)."""
    mode = get_setting("dist_regulars_mode") or "schedule"
    return mode if mode in ("schedule", "none", "scored") else "schedule"


def compute_suggested_n(total_products: int) -> tuple[int, int]:
    """Returns (n_for_one_time, regular_count). Regulars (frequency != חד-פעמי,
    e.g. code-4 קבוע) are served first; the rest of the products go to the
    one-time priority list. In 'none'/'scored' modes regulars are no longer
    auto-served first, so regular_count is 0 and all products feed the list."""
    if get_regulars_mode() != "schedule":
        return max(0, total_products), 0
    with get_connection() as conn:
        regular_count = conn.execute(
            "SELECT COUNT(*) as c FROM recipients WHERE status='פעיל' "
            "AND frequency != 'חד-פעמי' AND frequency != ''"
        ).fetchone()["c"]
    n = max(0, total_products - regular_count)
    return n, regular_count


# ─── Distributions (history) ─────────────────────────────────────────────────

def bulk_add_distributions(records: list[dict], dist_date: str, what_dist: str,
                           quantity, distributor: str,
                           dist_name: str = "", general_note: str = ""):
    """Add many distributions at once and update recipients' last/next distribution.

    Also records ONE batch row (the distribution event) that the "חלוקות" tab
    lists — capturing the shared header, the multi-product breakdown (carried in
    `what_dist`), and a single general note for the whole distribution. Each
    per-recipient row links back to the batch via batch_id. Returns the batch id."""
    souls_total = 0
    for rec in records:
        try:
            souls_total += int(rec.get("souls", 0) or 0)
        except (ValueError, TypeError):
            pass
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO dist_batches "
            "(dist_name, dist_date, products, quantity, distributor, general_note, "
            " recipient_count, souls_total) VALUES (?,?,?,?,?,?,?,?)",
            (dist_name or "", dist_date, what_dist, quantity or 0, distributor or "",
             general_note or "", len(records), souls_total)
        )
        batch_id = cur.lastrowid
        for rec in records:
            conn.execute(
                "INSERT INTO distributions "
                "(recipient_id, recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes, batch_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rec.get("id"), rec.get("full_name", ""), dist_date,
                 rec.get("area", ""), rec.get("souls", 0),
                 what_dist, quantity, distributor,
                 rec.get("notes", ""), batch_id)
            )
            freq = rec.get("frequency", "")
            nw = "" if freq == "חד-פעמי" else calculate_next_dist(dist_date, freq).isoformat()
            # Reset the weekly checkmark — it belongs to the cycle that just ended,
            # so it must not bleed into the next week's distribution list.
            conn.execute(
                "UPDATE recipients SET last_distribution=?, next_distribution=?, weekly_status='' WHERE id=?",
                (dist_date, nw, rec.get("id"))
            )
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


def get_batch_recipients(batch_id: int):
    """The per-recipient rows recorded under one batch (who received)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM distributions WHERE batch_id=? ORDER BY recipient_name COLLATE NOCASE",
            (batch_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_batch(batch_id: int):
    """Delete a distribution batch AND its per-recipient history rows. Does NOT
    roll back recipients' last/next distribution dates (kept as recorded)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions WHERE batch_id=?", (batch_id,))
        conn.execute("DELETE FROM dist_batches WHERE id=?", (batch_id,))


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
        dists_month = conn.execute(
            "SELECT COUNT(*) as c FROM distributions WHERE dist_date >= ?", (month_start,)
        ).fetchone()["c"]
        dists_total = conn.execute("SELECT COUNT(*) as c FROM distributions").fetchone()["c"]

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
    """Delete ALL recipients, distributions, and change_log. Settings are kept."""
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions")
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
