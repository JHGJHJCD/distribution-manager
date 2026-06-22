import sqlite3
import sys
import os
import hashlib
import secrets
from datetime import date, datetime, timedelta


def _app_dir() -> str:
    """Return the directory where persistent data files should be stored.
    Works correctly both in development and as a PyInstaller frozen EXE."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_app_dir(), "data.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    return conn


def init_db():
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
            representative  TEXT DEFAULT ''
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
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (recipient_id) REFERENCES recipients(id) ON DELETE SET NULL
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
        ]
        for col, definition in _migrations:
            if col not in columns:
                conn.execute(f"ALTER TABLE recipients ADD COLUMN {col} {definition}")

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
]

_INT_FIELDS = {"souls", "children_home", "children_married", "children_total"}


def _coerce(field: str, val):
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

def get_weekly_list(days_ahead: int = 30, area_filter: str = "הכל"):
    """Returns active non-one-time recipients sorted alphabetically."""
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipients WHERE status='פעיל' AND frequency != 'חד-פעמי' ORDER BY full_name"
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

def get_one_time_list(area_filter: str = "הכל"):
    """One-time recipients sorted: oldest last_distribution first, tie-break: souls DESC."""
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
        days_since = (date.today() - ld).days
        r["days_since"] = days_since
        result.append(r)
    return sorted(result, key=lambda x: (x["last_dist_date"], -(x.get("souls") or 0)))


def compute_suggested_n(total_products: int) -> tuple[int, int]:
    """Returns (n_for_one_time, regular_count)."""
    with get_connection() as conn:
        regular_count = conn.execute(
            "SELECT COUNT(*) as c FROM recipients WHERE status='פעיל' AND frequency != 'חד-פעמי'"
        ).fetchone()["c"]
    n = max(0, total_products - regular_count)
    return n, regular_count


# ─── Distributions (history) ─────────────────────────────────────────────────

def bulk_add_distributions(records: list[dict], dist_date: str, what_dist: str,
                           quantity, distributor: str):
    """Add many distributions at once and update recipients' last/next distribution."""
    with get_connection() as conn:
        for rec in records:
            conn.execute(
                "INSERT INTO distributions "
                "(recipient_id, recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (rec.get("id"), rec["full_name"], dist_date,
                 rec.get("area", ""), rec.get("souls", 0),
                 what_dist, quantity, distributor,
                 rec.get("notes", ""))
            )
            freq = rec.get("frequency", "")
            nw = "" if freq == "חד-פעמי" else calculate_next_dist(dist_date, freq).isoformat()
            # Reset the weekly checkmark — it belongs to the cycle that just ended,
            # so it must not bleed into the next week's distribution list.
            conn.execute(
                "UPDATE recipients SET last_distribution=?, next_distribution=?, weekly_status='' WHERE id=?",
                (dist_date, nw, rec["id"])
            )


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
            "WHERE status='פעיל' AND frequency != 'חד-פעמי' "
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
                 "work_scope", "parent_type", "occupation", "representative"]
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
                        updates[field] = int(new_val) if field == "souls" else new_val
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
