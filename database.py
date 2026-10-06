import re
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
APP_BG_PATH = os.path.join(_data_dir(), "app_bg")     # v3.65: user's app-wide wallpaper (any image ext)


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
    the DB. Stages, safest first:
      1. REINDEX in place — index-only damage is fixed with nothing lost.
      1b. A stale/mismatched WAL+SHM sidecar can make an otherwise-fine DB read as
         malformed. Move the sidecars aside (*.stale, never deleted) and re-check.
      2. If the DB itself is corrupt, set it aside as data.db.corrupt.db and
         restore the newest usable backup. If it can't be set aside, stop —
         never overwrite the only copy.
    Never raises — a failure here just falls through to normal init."""
    try:
        if not os.path.exists(DB_PATH):
            return
        if _db_integrity_ok(DB_PATH):
            return

        # Stage 1: damage limited to indexes is repaired in place by REINDEX —
        # FIRST, with the WAL still attached (it may hold committed rows)
        # (the tables are intact — nothing lost). Restoring a backup here used to
        # silently roll away everything since the last backup.
        try:
            c = sqlite3.connect(DB_PATH)
            try:
                c.execute("REINDEX")
                c.commit()
            finally:
                c.close()
        except Exception:
            pass
        if _db_integrity_ok(DB_PATH):
            return

        # Stage 1b: move stale sidecars ASIDE (never delete — a WAL can still hold
        # committed rows, e.g. when the check failed only because the file was
        # briefly locked), retry.
        for ext in ("-wal", "-shm"):
            side = DB_PATH + ext
            try:
                if os.path.exists(side):
                    os.replace(side, side + ".stale")
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
        # Search the local backup folder AND, when Drive-sync is configured, the
        # off-site daily folder — so a DB that was deleted/corrupted can still be
        # recovered from the cloud copy even if the local backups are gone too.
        search_dirs = [BACKUP_DIR]
        try:
            import utils.sync as _sync
            if _sync.folder_available():
                cloud = os.path.join(_sync.get_folder(), "גיבויים-יומי")
                if os.path.isdir(cloud):
                    search_dirs.append(cloud)
        except Exception:
            pass

        best, best_mtime = None, -1.0
        for folder in search_dirs:
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if not name.lower().endswith(".db"):
                    continue
                p = os.path.join(folder, name)
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
            # Could not even set it aside (file in use) — then we must NOT copy a
            # backup over it either: that would destroy the only copy of the
            # newer data. Leave it for init_db / a manual restore.
            return

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

        CREATE TABLE IF NOT EXISTS sync_deleted (
            guid    TEXT PRIMARY KEY,
            ts      TEXT
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

        -- הודעות למפתח (#ce6a0): every feedback message is also kept here so the
        -- operator can review it INSIDE the app (copy / mark handled), instead of
        -- chasing GitHub. Synced between the computers like the team chat.
        CREATE TABLE IF NOT EXISTS feedback (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            guid          TEXT DEFAULT '',
            author_name   TEXT DEFAULT '',
            host          TEXT DEFAULT '',
            version       TEXT DEFAULT '',
            body          TEXT NOT NULL,
            created_at    TEXT DEFAULT '',
            status        TEXT DEFAULT 'open',
            status_ts     TEXT DEFAULT ''
        );

        -- Voice-notification ("tzintuk") campaigns sent through Yemot HaMashiach
        -- (v2.81). One row per send; synced by guid so both computers see the
        -- history — and so the double-send guard works across machines.
        CREATE TABLE IF NOT EXISTS tzintuk_campaigns (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            guid         TEXT DEFAULT '',
            name         TEXT DEFAULT '',
            sent_at      TEXT DEFAULT '',
            dist_date    TEXT DEFAULT '',
            template_id  TEXT DEFAULT '',
            campaign_id  TEXT DEFAULT '',
            device       TEXT DEFAULT '',
            total        INTEGER DEFAULT 0,
            delivered    INTEGER DEFAULT 0,
            failed       INTEGER DEFAULT 0,
            status       TEXT DEFAULT 'sending',
            status_ts    TEXT DEFAULT '',
            report_json  TEXT DEFAULT ''
        );

        -- v3.39: מיילים למקבלים — היסטוריית שליחות (שורה לכל שליחה, מסונכרנת
        -- לפי guid) ותבניות הודעה משותפות לשני המחשבים.
        CREATE TABLE IF NOT EXISTS mail_campaigns (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            guid         TEXT DEFAULT '',
            sent_at      TEXT DEFAULT '',
            subject      TEXT DEFAULT '',
            body         TEXT DEFAULT '',
            audience     TEXT DEFAULT '',
            sender       TEXT DEFAULT '',
            device       TEXT DEFAULT '',
            total        INTEGER DEFAULT 0,
            sent         INTEGER DEFAULT 0,
            failed       INTEGER DEFAULT 0,
            status       TEXT DEFAULT 'sending',
            status_ts    TEXT DEFAULT '',
            report_json  TEXT DEFAULT '',
            attachment   TEXT DEFAULT '',
            with_header  INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS mail_templates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            guid         TEXT DEFAULT '',
            name         TEXT DEFAULT '',
            subject      TEXT DEFAULT '',
            body         TEXT DEFAULT '',
            updated_at   TEXT DEFAULT '',
            deleted      INTEGER DEFAULT 0
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
            # v3.52: נתמך חגים — general mark + optional per-holiday subset
            # (see holidays.py). Synced like every other recipient field.
            ("holiday_support",    "INTEGER DEFAULT 0"),
            ("holidays",           "TEXT DEFAULT ''"),
            # v3.60: "חלוקה אחרונה" שהגיעה מחוץ להיסטוריה (אקסל / הוקלדה) — הבסיס
            # שאליו חוזרים כשאין היסטוריה. last/next בכרטיס תמיד *נגזרים* ממנו +
            # מטבלת distributions (ראה _recompute_recipient_dates).
            ("last_dist_base",     "TEXT DEFAULT ''"),
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
        # v3.75 (הכרעות יהודה 27/9/2026): חלוקת חג נזכרת ככזו — '' = חלוקה רגילה,
        # '*' = חלוקת חג כללית, 'פסח' = חג מסוים. חלוקת חג היא חלוקה *נוספת*: לא
        # מזיזה את התור הקבוע (ראה _history_last), ומוצגת בהיסטוריה של המשפחה.
        if "holiday" not in dist_cols:
            conn.execute("ALTER TABLE distributions ADD COLUMN holiday TEXT DEFAULT ''")
        # v3.60 back-fill (once): a card date that no history row explains came
        # from the Excel import / was typed — remember it as the base.
        # Every start re-derives last/next for everyone (cheap; ~500 rows): a card
        # left stale by an older version (a peer's edit rolled the date back) heals
        # itself instead of waiting for the next write to that recipient.
        for r in conn.execute("SELECT id FROM recipients").fetchall():
            _adopt_last_base(conn, r["id"])
            _recompute_recipient_dates(conn, r["id"])
        batch_cols = {row["name"] for row in conn.execute("PRAGMA table_info(dist_batches)")}
        if "guid" not in batch_cols:
            conn.execute("ALTER TABLE dist_batches ADD COLUMN guid TEXT DEFAULT ''")
        if "holiday" not in batch_cols:
            conn.execute("ALTER TABLE dist_batches ADD COLUMN holiday TEXT DEFAULT ''")
        # v3.75 (הכרעת יהודה 27/9/2026): מקבל שנמחק נרשם — מי/מתי/מאיזה מחשב, עם
        # צילום הכרטיס כדי שאפשר יהיה לשחזר. מקומי (מגיע מהמחשב השני דרך op rec_delete).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deleted_recipients (
                guid        TEXT PRIMARY KEY,
                full_name   TEXT DEFAULT '',
                phone       TEXT DEFAULT '',
                deleted_at  TEXT DEFAULT '',
                device      TEXT DEFAULT '',
                source      TEXT DEFAULT '',
                card_json   TEXT DEFAULT ''
            )""")
        # משימה 7 (v3.78): כרטיס שמוזג לכרטיס אחר → לאן. מאפשר לחלוקה/היסטוריה שמגיעות
        # מהמחשב השני עם ה-guid הישן להגיע לכרטיס שנשאר. מקומי, נבנה גם מה-op rec_merge.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merged_guids (
                drop_guid  TEXT PRIMARY KEY,
                keep_guid  TEXT DEFAULT '',
                ts         TEXT DEFAULT ''
            )""")
        # v3.75: קובצי-מראה (לוגו / תמונת רקע) נשמרים גם בתוך ה-DB כדי שגיבוי
        # ושחזור במחשב חדש יחזירו אותם לבד (הכרעת יהודה 27/9/2026). לא מסונכרן.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                key       TEXT PRIMARY KEY,
                name      TEXT DEFAULT '',
                data      BLOB,
                saved_at  TEXT DEFAULT ''
            )""")
        # v3.47: שליחת-מיילים זוכרת את הקובץ המצורף ואת מצב הכותרת — "שלח שוב לנכשלים"
        # שולח את *המקור*, לא את מה שבטיוטה. נתיב מקומי; במחשב השני = שם בלבד (אזהרה).
        mail_cols = {row["name"] for row in conn.execute("PRAGMA table_info(mail_campaigns)")}
        if "attachment" not in mail_cols:
            conn.execute("ALTER TABLE mail_campaigns ADD COLUMN attachment TEXT DEFAULT ''")
        if "with_header" not in mail_cols:
            conn.execute("ALTER TABLE mail_campaigns ADD COLUMN with_header INTEGER DEFAULT 1")
        # v3.63 — היסטוריית שינויים בכרטיס (בקשת רון 22/9/2026): change_log הפך
        # מ"סטטוס בלבד, מקומי" ליומן של כל שדה בכרטיס שמסונכרן בין המחשבים.
        # field = מפתח השדה (field_changed נשאר התווית העברית — תאימות), guid =
        # זהות השורה לסנכרון, rec_guid = המקבל (id מקומי = אדם אחר במחשב השני),
        # device/source = מי ואיך (edit/import/undo/auto).
        cl_cols = {row["name"] for row in conn.execute("PRAGMA table_info(change_log)")}
        for col, decl in (("field", "TEXT DEFAULT ''"), ("guid", "TEXT DEFAULT ''"),
                          ("rec_guid", "TEXT DEFAULT ''"), ("device", "TEXT DEFAULT ''"),
                          ("source", "TEXT DEFAULT ''")):
            if col not in cl_cols:
                conn.execute(f"ALTER TABLE change_log ADD COLUMN {col} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_change_log_rec_guid "
                     "ON change_log(rec_guid)")

        # Back-fill stable guids (v2.61, cross-computer sync): every row gets a
        # random identity ONCE; new rows get theirs at insert time.
        for table in ("recipients", "distributions", "dist_batches"):
            missing = [r["id"] for r in conn.execute(
                f"SELECT id FROM {table} WHERE guid IS NULL OR guid=''")]
            for rid in missing:
                conn.execute(f"UPDATE {table} SET guid=? WHERE id=?",
                             (uuid.uuid4().hex, rid))
        # v3.63 back-fill (once): old status-only change_log rows get a guid, the
        # field key and the recipient's guid so they display (and sync) like new rows.
        for r in conn.execute("SELECT id, recipient_id, field_changed FROM change_log "
                              "WHERE COALESCE(guid,'')=''").fetchall():
            rg = conn.execute("SELECT guid FROM recipients WHERE id=?",
                              (r["recipient_id"],)).fetchone()
            conn.execute(
                "UPDATE change_log SET guid=?, rec_guid=?, field=?, source='edit' WHERE id=?",
                (uuid.uuid4().hex, (rg["guid"] if rg else "") or "",
                 "status" if r["field_changed"] == "סטטוס" else "", r["id"]))

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

    _migrate_legacy_dist_dates()
    _migrate_ended_status()
    try:
        restore_assets_to_disk()
    except Exception:            # noqa: BLE001 — a cosmetic file must never block startup
        pass


_LEGACY_DATE_RE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\s*$")


def _legacy_date_to_iso(s) -> str:
    """'16/09/2026' / '1.9.2026' (day-first, Israeli) → '2026-09-16'; '' if not one."""
    m = _LEGACY_DATE_RE.match(s or "")
    if not m:
        return ""
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return ""


def _migrate_legacy_dist_dates():
    """History dates saved by very old versions as DD/MM/YYYY are ignored by the
    turn logic (only ISO counts), so a monthly recipient could come back too soon.
    Convert them in place (user decision 25/9/2026) — after a safety backup. Each
    computer runs the same deterministic conversion, so nothing needs syncing."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, recipient_id, dist_date FROM distributions WHERE dist_date NOT GLOB "
            "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'").fetchall()
        todo = [(iso, r["id"], r["recipient_id"]) for r in rows
                if (iso := _legacy_date_to_iso(r["dist_date"]))]
    if not todo:
        return
    try:
        from utils.backup import auto_backup
        auto_backup("safety")
    except Exception:
        pass
    with get_connection() as conn:
        conn.executemany("UPDATE distributions SET dist_date=? WHERE id=?",
                         [(iso, did) for iso, did, _ in todo])
        for rid in {rid for _, _, rid in todo if rid}:
            _recompute_recipient_dates(conn, rid)


def _migrate_ended_status():
    """v3.78 (task 6, Yehuda 5/10/2026): the 'הסתיים' recipient status is gone —
    whoever was marked so becomes 'מושהה' (same effect: not in any list, card and
    history kept). One-time, after a safety backup. Deliberately NOT stamped with a
    new updated_at and not journaled: every computer runs the same deterministic
    conversion on its own start, and a value that still arrives from an older
    computer is mapped in sync._apply_rec_upsert. Column name unchanged."""
    with get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM recipients WHERE status=?",
                         (_LEGACY_STATUS_ENDED,)).fetchone()["n"]
    if not n:
        return
    try:
        from utils.backup import auto_backup
        auto_backup("safety")
    except Exception:
        pass
    with get_connection() as conn:
        conn.execute("UPDATE recipients SET status=? WHERE status=?",
                     (STATUS_SUSPENDED, _LEGACY_STATUS_ENDED))


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
            _adopt_last_base(conn, cur.lastrowid)
            _recompute_recipient_dates(conn, cur.lastrowid)
            new_ids.append(cur.lastrowid)
            count += 1
    for rid in new_ids:
        _sync_log("rec_upsert", _rec_sync_payload(rid))
    return count


_RECIPIENT_FIELDS = [
    "full_name", "first_name", "last_name", "phone1", "phone2", "phone3", "address", "area",
    "souls", "frequency", "start_date", "last_distribution", "next_distribution",
    "last_dist_base", "status", "notes",
    "external_id", "source", "birth_date", "spouse_birth_date",
    "id_number", "spouse_id_number",
    "children_home", "children_married", "children_total",
    "marital_status", "email", "synagogue",
    "housing_expenses", "medical_expenses", "income", "per_soul",
    "work_scope", "parent_type", "occupation", "representative",
    "priority", "priority_raw",
    "holiday_support", "holidays",
]

_INT_FIELDS = {"souls", "children_home", "children_married", "children_total",
               "holiday_support"}
# Nullable integer fields — '' / None stays NULL instead of being coerced to 0.
_NULLABLE_INT_FIELDS = {"priority"}


# Recipient status (v3.78, task 6): only 'פעיל' (gets the list by its own priority/
# frequency setup) or 'מושהה' (a temporary pause). 'הסתיים' was dropped — a legacy
# value that arrives from an old card / Excel / the other computer maps to 'מושהה'.
# Every WHO-IS-A-RECIPIENT query compares against STATUS_ACTIVE only.
STATUS_ACTIVE = "פעיל"
STATUS_SUSPENDED = "מושהה"
_LEGACY_STATUS_ENDED = "הסתיים"


def normalize_status(val) -> str:
    """The one place that decides what a recipient status value means: empty →
    active, the legacy 'הסתיים' → suspended, anything else is kept as it is."""
    s = str(val or "").strip()
    if not s or s == "None":
        return STATUS_ACTIVE
    if s == _LEGACY_STATUS_ENDED:
        return STATUS_SUSPENDED
    return s


def _coerce(field: str, val):
    if field == "status":
        return normalize_status(val)
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


# ─── היסטוריית שינויים בכרטיס (v3.63, בקשת רון 22/9/2026) ────────────────────
# תוויות עברית לכל שדה בכרטיס — משמשות גם את יומן-המנהל של הסנכרון (sync._diff_summary).
FIELD_LABELS_HE = {
    "full_name": "שם", "first_name": "שם פרטי", "last_name": "שם משפחה",
    "phone1": "טלפון", "phone2": "טלפון 2", "phone3": "טלפון 3",
    "address": "כתובת", "area": "אזור", "souls": "נפשות", "frequency": "תדירות",
    "start_date": "תאריך התחלה", "status": "סטטוס", "notes": "הערות",
    "external_id": "מס' מזהה", "source": "מקור", "birth_date": "תאריך לידה",
    "spouse_birth_date": "תאריך לידה בת-זוג", "id_number": "ת.ז. בעל",
    "spouse_id_number": "ת.ז. אשה", "children_home": "ילדים בבית",
    "children_married": "ילדים נשואים", "children_total": "מספר ילדים",
    "marital_status": "מצב אישי", "email": "אימייל", "synagogue": "בית כנסת",
    "housing_expenses": "הוצאות דיור", "medical_expenses": "הוצאות רפואיות",
    "income": "הכנסות", "per_soul": "לנפש", "work_scope": "היקף עבודה",
    "parent_type": "סוג הורות", "occupation": "עיסוק", "representative": "נציג",
    "priority": "עדיפות", "priority_raw": "עדיפות (מקור)",
    "holiday_support": "נתמך חגים", "holidays": "חגים",
    "last_distribution": "חלוקה אחרונה", "next_distribution": "חלוקה הבאה",
    "merge": "מיזוג כרטיסים",     # שורת-היסטוריה מיוחדת (משימה 7), לא שדה בכרטיס
}
# מה נרשם בהיסטוריה: כל שדה בכרטיס חוץ מהנגזרים (תאריכי החלוקה — יש להם היסטוריה
# משלהם ב-distributions; last_dist_base הוא קלט טכני שלהם).
_UNTRACKED_FIELDS = {"last_distribution", "next_distribution", "last_dist_base",
                     # priority_raw is the same choice as priority (the dialog writes
                     # both) — one "עדיפות" row per change, not two (see
                     # _priority_hist_value; "חובת בירור" lives only in the raw).
                     "priority_raw"}
_TRACKED_FIELDS = [f for f in _RECIPIENT_FIELDS if f not in _UNTRACKED_FIELDS]
# כמה זמן אחורה נזרעת ההיסטוריה למחשב שמצטרף (snapshot) — ראו sync._snapshot_body.
CHANGE_LOG_SEED_MONTHS = 24
# מקור השינוי (עמודת source) → תווית עברית (חלון ההיסטוריה, אקסל).
CHANGE_SOURCE_HE = {"edit": "עריכה", "import": "ייבוא מאקסל", "undo": "ביטול (מנהל)",
                    "auto": "שיוך אוטומטי", "merge": "מיזוג"}


def change_source_label(source: str) -> str:
    return CHANGE_SOURCE_HE.get(source or "", source or "עריכה")


# ערכים מקודדים בכרטיס → מה המשתמש רואה בהיסטוריה (סקירת בשלות 26/9/2026: החלון
# הציג "4 ← 3" לעדיפות ו-"0 ← 1" לנתמך-חגים — קודים של האקסל המקורי שאף מסך אחר
# לא מציג). ה-DB שומר את הקוד; רק התצוגה (חלון/שורת-סיכום/אקסל) מתורגמת.
_CHANGE_VALUE_HE = {
    "priority": {"4": "קבוע", "3": "עדיפות ראשונה", "2": "עדיפות שנייה",
                 "1": "לא בחלוקה (1)", "0": "לא בחלוקה (0)", "בירור": "חובת בירור",
                 "": "ללא"},
    "holiday_support": {"1": "כן", "0": "לא"},
}


def change_value_label(field: str, value) -> str:
    """The user-facing text of one old/new value in the change history.
    Coded fields (priority / holiday_support) get their Hebrew label, everything
    else is the stored text; empty → '—'."""
    v = _hist_norm(value)
    table = _CHANGE_VALUE_HE.get(field or "")
    if table is not None and v in table:
        return table[v]
    return v or "—"


def _hist_norm(v) -> str:
    return "" if v is None else str(v).strip()


def _priority_hist_value(row: dict, fallback: dict | None = None) -> str:
    """The one value the history keeps for the priority pair: the code (4/3/2)
    when there is one, 'בירור' when only the raw says so, '' = none. A partial
    update (only one of the two keys) falls back to the stored row."""
    src = fallback or {}
    pr = row.get("priority") if "priority" in row else src.get("priority")
    raw = row.get("priority_raw") if "priority_raw" in row else src.get("priority_raw")
    pr = _hist_norm(pr)
    if pr:
        return pr
    return "בירור" if "בירור" in _hist_norm(raw) else ""


def _device() -> str:
    """Which computer made the change: the sync device name, else the hostname
    (sync not set up yet) — so the 'מחשב' column is never blank."""
    try:
        from utils import sync
        name = sync.device_name() or ""
    except Exception:
        name = ""
    if not name:
        try:
            import socket
            name = socket.gethostname()
        except Exception:
            name = ""
    return name


def _log_changes(conn, rec_id: int, old: dict, new: dict, source: str,
                 extra: list | None = None, when: str = "") -> dict | None:
    """Write one change_log row per tracked field whose value really changed
    (after normalisation: '' ≡ None, ints ≡ their str). Returns the `rec_change`
    sync payload (one op per recipient per action — not per field, so a 500-row
    import doesn't blow the journal past its compaction limit), or None when
    nothing changed. Runs inside the caller's connection; the caller sends the
    payload with _sync_log AFTER its `with` block."""
    if not old:
        return None
    changes = []
    for field in _TRACKED_FIELDS:
        if field == "priority":
            if "priority" not in new and "priority_raw" not in new:
                continue
            o, n = _priority_hist_value(old), _priority_hist_value(new, old)
        else:
            if field not in new:
                continue
            o, n = _hist_norm(old.get(field)), _hist_norm(new.get(field))
        if o == n:
            continue
        changes.append({"guid": uuid.uuid4().hex, "field": field,
                        "label": FIELD_LABELS_HE.get(field, field), "old": o, "new": n})
    changes.extend(extra or [])        # e.g. the "merged" line of a card merge
    if not changes:
        return None
    when = when or _utc_now()
    payload = {"guid": uuid.uuid4().hex, "rec_guid": old.get("guid") or "",
               "rec_name": old.get("full_name") or "", "changed_at": when,
               "device": _device(), "source": source, "changes": changes}
    _insert_changes(conn, rec_id, payload)
    return payload


def _insert_changes(conn, rec_id, payload: dict):
    """Insert the rows of one rec_change payload (local write AND remote apply).
    Idempotent by row guid — the sync head is replayed on peers that have it."""
    for ch in payload.get("changes") or []:
        g = ch.get("guid") or ""
        if not g or conn.execute("SELECT 1 FROM change_log WHERE guid=?", (g,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO change_log (recipient_id, recipient_name, field_changed, "
            "old_value, new_value, changed_at, field, guid, rec_guid, device, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (rec_id, payload.get("rec_name", ""), ch.get("label") or ch.get("field", ""),
             ch.get("old", ""), ch.get("new", ""), payload.get("changed_at") or _utc_now(),
             ch.get("field", ""), g, payload.get("rec_guid", ""),
             payload.get("device", ""), payload.get("source", "")))


def get_changes_for_recipient(rec_id: int, guid: str = "", limit: int = 0) -> list[dict]:
    """The change history of one recipient, newest first. Matched by guid (the
    only identity that means the same person on both computers); the local id is
    a fallback for rows that predate guids."""
    sql = ("SELECT * FROM change_log WHERE (rec_guid=? AND rec_guid<>'') "
           "OR (COALESCE(rec_guid,'')='' AND recipient_id=?) "
           "ORDER BY changed_at DESC, id DESC")
    args: list = [guid or "", rec_id]
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


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
        _adopt_last_base(conn, rec_id)
        _recompute_recipient_dates(conn, rec_id)
    _sync_log("rec_upsert", _rec_sync_payload(rec_id))
    return rec_id


def update_recipient(rec_id: int, data: dict, source: str = "edit"):
    """`source` tags the change-history rows: edit (card/UI), undo (manager
    revert), auto (inferred community), import (Excel merge)."""
    data = _apply_name_fields(data)
    old = get_recipient(rec_id)
    # last/next are DERIVED (history + base + frequency) — never written directly.
    # A deliberately changed "last distribution" (import / script) becomes the base.
    data.pop("next_distribution", None)
    if "status" in data:
        data["status"] = normalize_status(data["status"])    # no 'הסתיים' (v3.78)
    if "last_distribution" in data:
        new_last = (data.pop("last_distribution") or "").strip()
        if old is not None and new_last != (old.get("last_distribution") or "").strip():
            data["last_dist_base"] = new_last
    cols = [k for k in data if k != "id"]
    if not cols:
        return
    with get_connection() as conn:
        change = _log_changes(conn, rec_id, old, data, source)   # v3.63 history
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
        _recompute_recipient_dates(conn, rec_id)   # e.g. frequency changed → new turn
    _sync_log("rec_upsert", _rec_sync_payload(rec_id))
    if change:
        _sync_log("rec_change", change)


def _remember_delete(conn, rec):
    """v3.63 — remember a deleted guid (local table) so a peer's older copy of
    the card, arriving later through another journal, can't resurrect it."""
    if rec and rec.get("guid"):
        conn.execute("INSERT OR REPLACE INTO sync_deleted (guid, ts) VALUES (?,?)",
                     (rec["guid"], _utc_now()))


# ─── מקבלים שנמחקו (v3.75) ────────────────────────────────────────────────────
SOURCE_LABELS_DELETE = {"delete": "מחיקה", "force": "מחיקה כפויה (עם היסטוריה)",
                        "dup": "מחיקת כפילות", "merge": "מוזג לכרטיס אחר"}


def _deleted_card_payload(rec: dict, source: str) -> dict:
    """The extra fields the rec_delete op carries so the OTHER computer can log
    who was deleted, by which computer, and keep the card for a restore."""
    rec = rec or {}
    card = {k: rec.get(k, "") for k in _RECIPIENT_FIELDS}
    card["guid"] = rec.get("guid", "")
    return {"name": rec.get("full_name", ""), "device": _device(), "source": source,
            "card": card}


def _remember_deleted_card(conn, rec: dict, source: str, device: str = "", ts: str = ""):
    """Write one row to deleted_recipients (idempotent by guid)."""
    if not rec or not rec.get("guid"):
        return
    card = {k: rec.get(k, "") for k in _RECIPIENT_FIELDS}
    conn.execute(
        "INSERT OR REPLACE INTO deleted_recipients "
        "(guid, full_name, phone, deleted_at, device, source, card_json) VALUES (?,?,?,?,?,?,?)",
        (rec["guid"], rec.get("full_name", "") or "", rec.get("phone1", "") or "",
         ts or _utc_now(), device or _device(), source or "delete",
         json.dumps(card, ensure_ascii=False)))


def get_deleted_recipients(limit: int = 500) -> list[dict]:
    """Newest first. Each row: guid, full_name, phone, deleted_at, device, source, card_json."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM deleted_recipients ORDER BY deleted_at DESC LIMIT ?",
                            (limit,)).fetchall()
        return [dict(r) for r in rows]


def restore_deleted_recipient(guid: str) -> tuple:
    """Bring a deleted card back as a NEW recipient (new guid — the old one is a
    tombstone on both computers). Returns (new_id or None, message). If a card
    with the same name+phone already exists (restored on the other computer),
    nothing is added and the log row is dropped."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM deleted_recipients WHERE guid=?", (guid,)).fetchone()
    if not row:
        return None, "הרשומה לא נמצאה"
    try:
        card = json.loads(row["card_json"] or "{}")
    except ValueError:
        card = {}
    if not card.get("full_name"):
        card["full_name"] = row["full_name"] or ""
    name, phone = card.get("full_name", ""), (card.get("phone1") or "")
    with get_connection() as conn:
        dup = conn.execute("SELECT id FROM recipients WHERE full_name=? AND COALESCE(phone1,'')=?",
                           (name, phone)).fetchone()
    if dup:
        with get_connection() as conn:
            conn.execute("DELETE FROM deleted_recipients WHERE guid=?", (guid,))
        return None, f"{name} כבר קיים ברשימה (שוחזר במחשב אחר) — לא נוסף שוב."
    for k in ("guid", "id", "updated_at", "last_distribution", "next_distribution"):
        card.pop(k, None)
    new_id = add_recipient(card)
    with get_connection() as conn:
        conn.execute("DELETE FROM deleted_recipients WHERE guid=?", (guid,))
    note = ("\nשים לב: הכרטיס הזה מוזג בעבר — היסטוריית החלוקות שלו נשארה בכרטיס שאליו מוזג."
            if row["source"] == "merge" else "")
    return new_id, f"{name} שוחזר לרשימת המקבלים ✓{note}"


# ─── מיזוג מקבלים — אותו שם, טלפון שונה (v3.78, משימה 7) ───────────────────────
# כלל: מיזוג הוא תמיד הצעה עם אישור (ברירת מחדל "לא"), אחרי גיבוי safety. כרטיס אחד
# נשאר, השני נמחק (נשמר ב"מקבלים שנמחקו", מקור "merge"); שני המספרים נשמרים, ההיסטוריה
# מתאחדת. בין שני כרטיסים קיימים = op מסונכרן `rec_merge`; הוספת נתוני נכנס (ייבוא /
# הוספה ידנית) לכרטיס קיים = update_recipient רגיל (rec_upsert + rec_change).
_MERGE_FILL_SKIP = {"full_name", "first_name", "last_name", "phone1", "phone2", "phone3",
                    "notes", "status", "last_distribution", "next_distribution",
                    "last_dist_base", "priority", "priority_raw"}
_PHONE_SLOTS = ("phone1", "phone2", "phone3")


def phone_key(p) -> str:
    """Digits only (9-digit numbers get their leading 0) — equality of phones."""
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    return "0" + d if len(d) == 9 else d


def recipient_phones(rec: dict) -> list:
    """The card's phone numbers as typed, in slot order, no blanks, no repeats."""
    out, seen = [], set()
    for f in _PHONE_SLOTS:
        v = str((rec or {}).get(f) or "").strip()
        k = phone_key(v)
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def phones_conflict(existing_phones, incoming_phones) -> bool:
    """True when BOTH sides have numbers and none is shared — the 'same name,
    different phone' situation. A shared number (or a side with no number at all)
    is not a conflict: that is the ordinary same-person case."""
    a = {phone_key(p) for p in existing_phones if phone_key(p)}
    b = {phone_key(p) for p in incoming_phones if phone_key(p)}
    return bool(a) and bool(b) and not (a & b)


def same_name_conflicts(full_name: str, incoming_phones, exclude_id=None) -> list:
    """Existing cards with exactly this name whose phones do not overlap the
    incoming ones (newest data first by id). Empty when the incoming side has no
    phone — nothing to compare, so no merge is offered."""
    name = (full_name or "").strip()
    inc = [p for p in (incoming_phones or []) if phone_key(p)]
    if not name or not inc:
        return []
    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM recipients WHERE TRIM(full_name)=? ORDER BY id", (name,))]
    return [r for r in rows if r["id"] != exclude_id
            and phones_conflict(recipient_phones(r), inc)]


def _blank_val(v) -> bool:
    return str(v if v is not None else "").strip() in ("", "0", "None")


def _real_priority(v):
    try:
        n = int(float(v))
    except (ValueError, TypeError):
        return None
    return n if n in (2, 3, 4) else None


def merge_fill_updates(existing: dict, incoming: dict) -> dict:
    """What to write on `existing` so it also carries `incoming` (pure). Only EMPTY
    fields are filled — a value the kept card already has is never overwritten.
    Phones are appended into free slots (overflow → a line in the notes, so no
    number is ever dropped); the other card's notes are appended; the later
    'last distribution base' wins."""
    fields = {}
    for f in _RECIPIENT_FIELDS:
        if f in _MERGE_FILL_SKIP:
            continue
        if not _blank_val(incoming.get(f)) and _blank_val(existing.get(f)):
            fields[f] = _coerce(f, incoming.get(f))
    # priority + its raw text travel together
    in_pr = _real_priority(incoming.get("priority"))
    if _real_priority(existing.get("priority")) is None and in_pr is not None:
        fields["priority"] = in_pr
        fields["priority_raw"] = str(incoming.get("priority_raw") or in_pr)
    elif ("בירור" in str(incoming.get("priority_raw") or "")
          and not str(existing.get("priority_raw") or "").strip()):
        fields["priority_raw"] = str(incoming.get("priority_raw"))
    # the later "last distribution" base (ISO only)
    cand = _valid_iso(incoming.get("last_dist_base")) or _valid_iso(incoming.get("last_distribution"))
    if cand and cand > _valid_iso(existing.get("last_dist_base")):
        fields["last_dist_base"] = cand
    # phones: free slots first, the rest into the notes
    have = {phone_key(p) for p in recipient_phones(existing)}
    added = []
    for p in recipient_phones(incoming):
        if phone_key(p) not in have:
            have.add(phone_key(p))
            added.append(p)
    free = [f for f in _PHONE_SLOTS if not str(existing.get(f) or "").strip()]
    overflow = []
    for p in added:
        if free:
            fields[free.pop(0)] = p
        else:
            overflow.append(p)
    notes = str(existing.get("notes") or "").strip()
    for extra in (str(incoming.get("notes") or "").strip(),
                  ("מספרים נוספים: " + ", ".join(overflow)) if overflow else ""):
        if extra and extra not in notes:
            notes = (notes + "\n" + extra).strip()
    if notes != str(existing.get("notes") or "").strip():
        fields["notes"] = notes
    return fields


def merge_into_recipient(rec_id: int, incoming: dict, source: str = "merge") -> bool:
    """Add what an incoming card/row knows (a second phone, empty fields) to an
    EXISTING card — import "מזג" and manual add "מזג לכרטיס הקיים". Goes through
    update_recipient, so sync + change history see it. True when something changed."""
    existing = get_recipient(rec_id)
    if not existing:
        return False
    fields = merge_fill_updates(existing, incoming)
    if not fields:
        return False
    update_recipient(rec_id, fields, source=source)
    return True


def pick_merge_keep(a: dict, b: dict) -> tuple:
    """(keep, drop) for two cards of the same person: the one with more distribution
    history stays; a tie → the older card (created_at), then guid. Deterministic, so
    two computers merging the same pair pick the same card."""
    def hist(r):
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM distributions WHERE recipient_id=?",
                                (r["id"],)).fetchone()["c"]

    def key(r):
        return (-hist(r), str(r.get("created_at") or ""), str(r.get("guid") or ""))
    return (a, b) if key(a) <= key(b) else (b, a)


def merge_conflicts_summary(a: dict, b: dict) -> dict:
    """For the confirmation text: which fields hold DIFFERENT non-empty values in the
    two cards ('differs' = Hebrew labels; the kept card's value stays) and whether
    the ID numbers differ ('id_differs' — strong sign these are two people)."""
    differs = []
    for f in _TRACKED_FIELDS:
        if f in ("full_name", "first_name", "last_name", "phone1", "phone2", "phone3",
                 "notes", "status", "priority", "start_date"):
            continue
        va, vb = _hist_norm(a.get(f)), _hist_norm(b.get(f))
        if va not in ("", "0") and vb not in ("", "0") and va != vb:
            differs.append(FIELD_LABELS_HE.get(f, f))
    def _ids(r, f):
        return _only_digits(r.get(f))
    id_differs = any(_ids(a, f) and _ids(b, f) and _ids(a, f) != _ids(b, f)
                     for f in ("id_number", "spouse_id_number"))
    return {"differs": differs, "id_differs": id_differs}


def resolve_merged_guid(conn, guid: str) -> str:
    """Follow merged_guids (a card that was merged away → the card that stayed).
    Returns the guid itself when it was never merged. Cycle-safe."""
    seen, g = set(), guid or ""
    while g and g not in seen:
        seen.add(g)
        row = conn.execute("SELECT keep_guid FROM merged_guids WHERE drop_guid=?", (g,)).fetchone()
        if not row or not row["keep_guid"]:
            break
        g = row["keep_guid"]
    return g


def remember_merge(conn, drop_guid: str, keep_guid: str, ts: str):
    if drop_guid and keep_guid and drop_guid != keep_guid:
        conn.execute("INSERT OR REPLACE INTO merged_guids (drop_guid, keep_guid, ts) VALUES (?,?,?)",
                     (drop_guid, keep_guid, ts or _utc_now()))


def merge_recipients(keep_id: int, drop_id: int) -> dict:
    """Merge card `drop_id` INTO card `keep_id` (the caller asked for confirmation and
    made the safety backup). One transaction: the kept card gets the other's numbers
    and empty fields, all distribution rows and change history move to it, the dropped
    card goes to 'מקבלים שנמחקו' (source merge) and is gone. Then ONE synced op
    `rec_merge`. Returns {'moved': n, 'phones': [...]}. ValueError on bad input."""
    if keep_id == drop_id:
        raise ValueError("אי אפשר למזג כרטיס עם עצמו")
    stamp = _utc_now()
    with get_connection() as conn:
        k = conn.execute("SELECT * FROM recipients WHERE id=?", (keep_id,)).fetchone()
        d = conn.execute("SELECT * FROM recipients WHERE id=?", (drop_id,)).fetchone()
        if not k or not d:
            raise ValueError("אחד הכרטיסים כבר לא קיים")
        keep, drop = dict(k), dict(d)
        if not keep.get("guid") or not drop.get("guid"):
            raise ValueError("לכרטיס חסר מזהה סנכרון")
        fields = merge_fill_updates(keep, drop)
        merged_note = f"אוחד עם כרטיס נוסף ({', '.join(recipient_phones(drop)) or 'בלי טלפון'})"
        extra = [{"guid": uuid.uuid4().hex, "field": "merge",
                  "label": FIELD_LABELS_HE["merge"], "old": "", "new": merged_note}]
        change = _log_changes(conn, keep_id, keep, fields, "merge", extra=extra, when=stamp)
        if fields:
            sets = ", ".join(f"{c}=?" for c in fields)
            conn.execute(f"UPDATE recipients SET {sets} WHERE id=?",
                         list(fields.values()) + [keep_id])
        conn.execute("UPDATE recipients SET updated_at=? WHERE id=?", (stamp, keep_id))
        moved = conn.execute("UPDATE distributions SET recipient_id=? WHERE recipient_id=?",
                             (keep_id, drop_id)).rowcount
        conn.execute("UPDATE change_log SET recipient_id=?, rec_guid=? "
                     "WHERE recipient_id=? OR (rec_guid=? AND rec_guid<>'')",
                     (keep_id, keep["guid"], drop_id, drop["guid"]))
        _remember_deleted_card(conn, drop, "merge", ts=stamp)
        conn.execute("INSERT OR REPLACE INTO sync_deleted (guid, ts) VALUES (?,?)",
                     (drop["guid"], stamp))
        remember_merge(conn, drop["guid"], keep["guid"], stamp)
        conn.execute("DELETE FROM recipients WHERE id=?", (drop_id,))
        _recompute_recipient_dates(conn, keep_id)
    _sync_log("rec_merge", {"keep_guid": keep["guid"], "drop_guid": drop["guid"],
                            "keep": _rec_sync_payload(keep_id), "merged_at": stamp,
                            "drop": _deleted_card_payload(drop, "merge"), "change": change})
    return {"moved": moved, "phones": recipient_phones(get_recipient(keep_id))}


def changed_fields_summary(before: dict, after: dict) -> list:
    """Hebrew labels of the card fields that differ between two snapshots
    (v3.75 stale-edit guard). Derived/technical fields are ignored."""
    out = []
    for f in _TRACKED_FIELDS:
        if _hist_norm((before or {}).get(f)) != _hist_norm((after or {}).get(f)):
            out.append(FIELD_LABELS_HE.get(f, f))
    return out


# ─── קובצי-מראה בתוך ה-DB (v3.75) ────────────────────────────────────────────
ASSET_LOGO = "logo"
ASSET_BG = "app_bg"


def save_asset(key: str, path: str) -> bool:
    """Store a copy of the file (logo / wallpaper) inside the DB so a backup
    carries it. Returns False when the file can't be read."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return False
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO assets (key, name, data, saved_at) VALUES (?,?,?,?)",
                     (key, os.path.basename(path), data, _utc_now()))
    return True


def delete_asset(key: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM assets WHERE key=?", (key,))


def get_asset(key: str):
    """(name, bytes) or None."""
    with get_connection() as conn:
        row = conn.execute("SELECT name, data FROM assets WHERE key=?", (key,)).fetchone()
    return (row["name"], row["data"]) if row and row["data"] else None


def restore_assets_to_disk() -> list:
    """After a restore / on a new computer: write back the logo and wallpaper
    files that the DB holds but the disk lacks. Returns the keys written."""
    written = []
    logo = get_asset(ASSET_LOGO)
    if logo and not os.path.exists(USER_LOGO_PATH):
        try:
            os.makedirs(os.path.dirname(USER_LOGO_PATH), exist_ok=True)
            with open(USER_LOGO_PATH, "wb") as fh:
                fh.write(logo[1])
            written.append(ASSET_LOGO)
        except OSError:
            pass
    bg = get_asset(ASSET_BG)
    if bg:
        d, stem = os.path.dirname(APP_BG_PATH), os.path.basename(APP_BG_PATH)
        try:
            present = any(fn.startswith(stem + ".") for fn in os.listdir(d))
        except OSError:
            present = False
        if not present:
            ext = os.path.splitext(bg[0])[1] or ".png"
            try:
                os.makedirs(d, exist_ok=True)
                with open(APP_BG_PATH + ext, "wb") as fh:
                    fh.write(bg[1])
                written.append(ASSET_BG)
            except OSError:
                pass
    return written


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
                "לא ניתן למחוק — שנה סטטוס ל'מושהה' במקום."
            )
        conn.execute("DELETE FROM recipients WHERE id=?", (rec_id,))
        # The card's change history goes with it (as in the forced delete) —
        # otherwise orphan rows stay in change_log forever, invisible in any
        # screen yet re-seeded into every sync snapshot.
        conn.execute("DELETE FROM change_log WHERE recipient_id=? OR (rec_guid=? AND rec_guid<>'')",
                     (rec_id, (rec or {}).get("guid") or ""))
        _remember_delete(conn, rec)
        _remember_deleted_card(conn, rec, "delete")
    if rec and rec.get("guid"):
        _sync_log("rec_delete", {"guid": rec["guid"], "force": False,
                                 **_deleted_card_payload(rec, "delete")})


def force_delete_recipient(rec_id: int):
    """Delete a recipient AND all their distribution history. Use with caution."""
    rec = get_recipient(rec_id)
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions WHERE recipient_id=?", (rec_id,))
        conn.execute("DELETE FROM change_log WHERE recipient_id=? OR (rec_guid=? AND rec_guid<>'')",
                     (rec_id, (rec or {}).get("guid") or ""))
        conn.execute("DELETE FROM recipients WHERE id=?", (rec_id,))
        _remember_deleted_card(conn, rec, "force")
        _remember_delete(conn, rec)
    if rec and rec.get("guid"):
        _sync_log("rec_delete", {"guid": rec["guid"], "force": True, **_deleted_card_payload(rec, "force")})


# ─── Next Wednesday + frequency-aware next distribution ───────────────────────

# v3.76 (RULE 6, 28/9/2026): the Wednesday/interval arithmetic moved to the pure
# selection module so the frequency gate (selection.is_due) and the derived
# next_distribution use ONE table (selection.FREQUENCY_INTERVAL_DAYS). These
# names stay here because ~20 callers use db.next_wednesday()/calculate_next_dist.
import selection as _sel
next_wednesday = _sel.next_wednesday
cycle_wednesday = _sel.cycle_wednesday


def calculate_next_dist(last_date_str: str, frequency: str) -> date:
    """Return the correct next distribution date based on frequency.
    Never served → the UPCOMING Wednesday (bug #pv59q); Thu–Sat snaps back to
    its cycle Wednesday; weekly +7 / bi-weekly +14 / tri-weekly +21 / monthly
    +28 (user decision 17/9/2026). Delegates to selection.next_due."""
    return _sel.next_due(last_date_str, frequency)


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
            # Self-heal a turn that was stored LATER than the rule gives (monthly
            # used to be 5 weeks; a late-recorded bi-weekly was pushed a week) —
            # next_distribution is always derived, never typed by the operator.
            ld_heal = (r.get("last_distribution") or "").strip()
            if ld_heal and (r.get("frequency") or ""):
                try:
                    date.fromisoformat(ld_heal)
                    due = calculate_next_dist(ld_heal, r["frequency"])
                    if nd > due:
                        nd = due
                        r["next_distribution"] = nd.isoformat()
                        updates.append((r["next_distribution"], r["id"]))
                except ValueError:
                    pass
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
            # "Served for THIS cycle" = the distribution's cycle-Wednesday equals
            # the upcoming distribution Wednesday (base_wed). This keeps a regular
            # on the list the moment their distribution is recorded (the operator
            # normally dates it on the coming Wednesday, which pushes
            # next_distribution a week out — without this the person would vanish
            # from the list the instant it is saved). Using cycle equality instead
            # of a raw "last 6 days" window is what stops LAST week's distribution
            # — especially one recorded a day or two LATE (Thu-Sat), which is
            # normal — from dragging every bi-weekly/monthly recipient back onto
            # THIS week's list (they'd look like their frequency was ignored).
            # A date AFTER the upcoming Wednesday can't be a real (late-recorded)
            # distribution of this cycle yet — it's a future-dated typo. Without
            # the upper bound, on Thu–Sat a typo 1–6 days past next Wednesday
            # landed in base_wed's cycle and put the person on this week's list.
            served_recently = (ld2 is not None and ld2 <= max(today, base_wed)
                               and cycle_wednesday(ld2) == base_wed)
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
    base_wed = selection.upcoming_wednesday()
    cooldown = get_one_time_cooldown_weeks()
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
        # RULE 7 (v3.76): received within the cooldown → not a candidate this week
        # (listed after the candidates, like the other non-distribution rows).
        if r["in_distribution"] and not selection.is_due(r, base_wed, cooldown):
            r["in_distribution"] = False
            r["_cooldown"] = True
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
    base_wed = selection.upcoming_wednesday()
    for r in rows:
        r = dict(r)
        if area_filter != "הכל" and r.get("area", "") != area_filter:
            continue
        # RULE 6 (v3.76): a bi-weekly/tri-weekly/monthly regular whose turn has
        # not come is OUT — even when products are left over.
        if not selection.is_due(r, base_wed):
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
    base_wed = selection.upcoming_wednesday(today)
    cooldown = get_one_time_cooldown_weeks()
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
            if not selection.is_due(r, base_wed, cooldown):
                continue                      # RULE 7 (v3.76): rotating — cooldown
        elif freq != "" or r.get("priority") == 4:
            r["_scored_regular"] = True        # a regular
            if not selection.is_due(r, base_wed):
                continue                       # RULE 6 (v3.76): turn not come → out
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


def reset_regulars_mode() -> bool:
    """Task 5 (6/10/2026): every app launch opens the distribution mode on
    'schedule'; another mode is chosen only for the current round. The setting
    is per-machine (utils.sync.EXCLUDED_SETTINGS), so this reset is local and
    the other computer can't bring a stale mode back. Called once from
    MainWindow.__init__ — never mid-session. The saved filter criteria are kept.
    Returns True if a different mode had to be reset."""
    if (get_setting("dist_regulars_mode") or "schedule") == "schedule":
        return False
    set_setting("dist_regulars_mode", "schedule")
    return True


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
    # v3.52: a holiday distribution is a HARD gate — people not marked as
    # holiday-supported never enter, not even as a community top-up.
    rows = selection.holiday_filter(rows, criteria)
    # RULE 6 (v3.76): the frequency gate runs BEFORE the community balance, so a
    # not-yet-due bi-weekly/monthly regular is neither picked nor used as a
    # top-up, and the community quotas are computed over the people who CAN
    # receive this week (a quota a community can't fill moves to the others).
    # A holiday round is an extra distribution (v3.75) — the gate is skipped.
    # RULE 7 (v3.76): the same pass rotates the one-timers (cooldown weeks).
    rows = selection.due_filter(rows, selection.upcoming_wednesday(),
                                ignore=bool(selection.holiday_criterion(criteria)),
                                cooldown_weeks=get_one_time_cooldown_weeks())
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
        update_recipient(rid, {"representative": rep, "representative_auto": 1}, source="auto")
    return len(suggestions)


def compute_suggested_n(total_products: int, manual_regulars: int = 0) -> tuple[int, int]:
    """Returns (n_for_one_time, regular_count). Regulars are served first; the
    rest of the products go to the one-time priority list. In 'none'/'scored'
    modes regulars are no longer auto-served first, so regular_count is 0 and all
    products feed the list.

    regular_count counts ONLY the regulars actually due on THIS week's list (the
    same set get_weekly_list shows), NOT every active regular — a bi-weekly or
    monthly recipient who isn't due this week doesn't consume a portion now, so
    counting them would wrongly reserve products away from the one-time list.

    `manual_regulars` (task 13): regulars added by hand who are NOT due this week
    each take a product too, so they come off n (they are not in regular_count —
    that stays the due-this-week figure the warnings are measured against)."""
    if get_regulars_mode() != "schedule":
        return max(0, total_products), 0
    regular_count = len(get_weekly_list())
    n = selection.one_time_slots(total_products, regular_count, manual_regulars)
    return n, regular_count


# ─── Distributions (history) ─────────────────────────────────────────────────

def bulk_add_distributions(records: list[dict], dist_date: str, what_dist: str,
                           quantity, distributor: str,
                           dist_name: str = "", general_note: str = "",
                           not_received: list[dict] = None, holiday: str = ""):
    """Add many distributions at once and update recipients' last/next distribution.

    `holiday` (v3.75): '' = a regular round; '*' / a holiday name = a HOLIDAY
    distribution — remembered on the batch and on every row, shown in the
    family's history, and treated as an EXTRA round that never moves the
    regular Wednesday turn (user decision 27/9/2026).

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
    holiday = (holiday or "").strip()
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
            " recipient_count, souls_total, guid, holiday) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (dist_name or "", dist_date, what_dist, quantity or 0, distributor or "",
             general_note or "", len(records), souls_total, batch_guid, holiday)
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
                "(recipient_id, recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes, batch_id, received, guid, holiday) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)",
                (rec.get("id"), rec.get("full_name", ""), dist_date,
                 rec.get("area", ""), rec.get("souls", 0),
                 what_dist, quantity, distributor,
                 rec.get("notes", ""), batch_id, row_guid, holiday)
            )
            # last/next are re-derived from the history that now exists (single
            # source of truth — the same function the other computer runs), so an
            # OLDER distribution recorded after the fact never rolls "last" back.
            # The weekly checkmark belongs to the cycle that just ended.
            if rec.get("id") is not None:
                _recompute_recipient_dates(conn, rec.get("id"))
                conn.execute("UPDATE recipients SET weekly_status='' WHERE id=?",
                             (rec.get("id"),))
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
                "(recipient_id, recipient_name, dist_date, area, souls, what_dist, quantity, distributor, notes, batch_id, received, guid, holiday) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (rec.get("id"), rec.get("full_name", ""), dist_date,
                 rec.get("area", ""), rec.get("souls", 0),
                 what_dist, 0, distributor,
                 rec.get("notes", ""), batch_id, row_guid, holiday)
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
                  "recipient_count": len(records), "souls_total": souls_total,
                  "holiday": holiday},
        "rows": sync_rows,
    })
    return batch_id


def get_distribution_batches(limit: int = None):
    """Every distribution event (batch), newest first — one row per distribution
    for the 'חלוקות' tab. limit=None (the default) returns EVERYTHING — the old
    default of 500 silently hid history past ~10 years and truncated the full-
    history export (#o8l0v)."""
    q = "SELECT * FROM dist_batches ORDER BY dist_date DESC, id DESC"
    args = ()
    if limit:
        q += " LIMIT ?"
        args = (limit,)
    with get_connection() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_ui_font_percent() -> int:
    """The operator's UI text size as a percentage (v2.80, #x2yn5): 100 = the
    default look, clamped to 80–150. Falls back to the legacy small/normal/large
    keys so an existing choice survives the upgrade. Never raises — the theme is
    applied before init_db on first launch."""
    try:
        v = get_setting("ui_font_scale")
        if v:
            return min(150, max(80, int(v)))
        legacy = get_setting("ui_font_size") or ""
        return {"small": 90, "large": 120}.get(legacy, 100)
    except Exception:
        return 100


def get_one_time_cooldown_weeks() -> int:
    """RULE 7 (v3.76): weeks a one-timer (עדיפות ראשונה/שנייה, or anyone who is
    not a regular) stays out of the automatic list after receiving — so the
    one-timers rotate instead of the neediest one receiving every week.
    Synced setting `onetime_cooldown_weeks`; default 3 (יהודה 28/9/2026); 0 = off."""
    try:
        return max(0, int(get_setting("onetime_cooldown_weeks") or
                          selection.ONE_TIME_COOLDOWN_WEEKS_DEFAULT))
    except (TypeError, ValueError):
        return selection.ONE_TIME_COOLDOWN_WEEKS_DEFAULT


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


def _valid_iso(s) -> str:
    s = (s or "").strip()
    try:
        date.fromisoformat(s)
        return s if len(s) == 10 else ""
    except ValueError:
        return ""


def _history_last(conn, rec_id, regular_only: bool = False, max_date: str = "") -> str:
    # received=1 only: a recorded no-show must never become someone's
    # "last distribution" — they didn't actually receive anything.
    # Only real ISO dates compete: one junk legacy value ("26/08/2026") sorts above
    # every ISO string and would otherwise hide the whole history.
    # regular_only: skip Sun–Tue (strftime %w 0–2) — at this fund a distribution on
    # those days is an EXTRA round, not the Wednesday one (user decision 25/9/2026).
    # A holiday distribution (v3.75) is an extra round too — even on a Wednesday.
    # max_date: ignore rows dated after it (a far-future typo, see _recompute).
    extra = (" AND strftime('%w', dist_date) NOT IN ('0','1','2')"
             " AND COALESCE(holiday,'')=''") if regular_only else ""
    args = [rec_id]
    if max_date:
        extra += " AND dist_date <= ?"
        args.append(max_date)
    row = conn.execute("SELECT MAX(dist_date) AS m FROM distributions "
                       "WHERE recipient_id=? AND received=1 AND dist_date GLOB "
                       "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'" + extra,
                       args).fetchone()
    return _valid_iso(row["m"] if row else "")


def _adopt_last_base(conn, rec_id):
    """A card whose last_distribution is LATER than anything the history explains
    got that date from outside (Excel import / typed) — keep it as the base, so
    deleting history later falls back to it instead of wiping it."""
    row = conn.execute("SELECT last_distribution, last_dist_base FROM recipients WHERE id=?",
                       (rec_id,)).fetchone()
    if not row:
        return
    last = _valid_iso(row["last_distribution"])
    if last and last > max(_valid_iso(row["last_dist_base"]), _history_last(conn, rec_id)):
        conn.execute("UPDATE recipients SET last_dist_base=? WHERE id=?", (last, rec_id))


def _recompute_recipient_dates(conn, rec_id):
    """THE single place that writes recipients.last_distribution / next_distribution.

    Both are derived, never typed and never synced as values:
      last = the newest of (received history rows, last_dist_base)
      next = calculate_next_dist(last, frequency)   ('' for one-time / no frequency)
    Every write path (record / delete / sync apply / card edit / import) calls this,
    so the card can't drift from the history and both computers reach the same
    answer. A date AFTER the upcoming Wednesday (Excel typo / mistyped round) is
    ignored entirely — user decision 27/9/2026: the regular is then simply due,
    instead of vanishing from the weekly list until the typo date passes."""
    row = conn.execute("SELECT frequency, last_dist_base FROM recipients WHERE id=?",
                       (rec_id,)).fetchone()
    if not row:
        return
    freq = row["frequency"] or ""
    today = date.today()
    horizon = (today if today.weekday() == 2 else next_wednesday(today)).isoformat()
    hist = _history_last(conn, rec_id, max_date=horizon)
    base = _valid_iso(row["last_dist_base"])
    if base and base > horizon:
        base = ""
    last = max(hist, base)
    if freq and freq != "חד-פעמי":
        # never served → due at the upcoming Wednesday (same answer get_weekly_list gives)
        # The turn counts from the last REGULAR distribution: a Sun–Tue one and a
        # holiday distribution are extra rounds (user decisions 25/9 + 27/9/2026)
        # and don't push the turn.
        nxt = calculate_next_dist(
            max(_history_last(conn, rec_id, regular_only=True, max_date=horizon), base),
            freq).isoformat()
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


def get_distributions(recipient_name: str = None, limit: int = None):
    """History rows, newest first. limit=None (the default) returns EVERY row —
    a hard cap here would silently hide old history from view/export (#o8l0v)."""
    q = "SELECT * FROM distributions"
    args = []
    if recipient_name:
        q += " WHERE recipient_name=?"
        args.append(recipient_name)
    q += " ORDER BY dist_date DESC"
    if limit:
        q += " LIMIT ?"
        args.append(limit)
    with get_connection() as conn:
        rows = conn.execute(q, args).fetchall()
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
    """Return the most recent chat messages in chronological order (oldest first).

    The cap keeps the NEWEST rows (inner DESC query) — the old ASC+LIMIT form
    kept the OLDEST 400, so once the chat passed 400 messages new ones would
    never appear (#o8l0v)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM messages ORDER BY created_at DESC, id DESC "
            "LIMIT ?) ORDER BY created_at ASC, id ASC", (limit,)
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


# ─── הודעות למפתח בתוך התוכנה (#ce6a0) ───────────────────────────────────────

def add_feedback(body: str, author_name: str = "", host: str = "",
                 version: str = "", guid: str = "", created_at: str = "") -> int:
    """Keep one feedback message in the DB (viewable in-app) and journal it so
    the manager sees reports left on the other computer too. Idempotent by guid
    (a deterministic guid lets both machines import the same legacy JSONL line
    without duplicating it)."""
    body = (body or "").strip()
    if not body:
        return 0
    guid = (guid or "").strip() or uuid.uuid4().hex
    created_at = created_at or _utc_now()
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM feedback WHERE guid=?", (guid,)).fetchone():
            return 0
        cur = conn.execute(
            "INSERT INTO feedback (guid, author_name, host, version, body, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (guid, author_name or "", host or "", version or "", body, created_at))
        fid = cur.lastrowid
    _sync_log("fb_add", {"guid": guid, "author_name": author_name or "",
                         "host": host or "", "version": version or "",
                         "body": body, "created_at": created_at})
    return fid


def get_feedback():
    """Every feedback message, newest first, with its handled-status."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC, id DESC").fetchall()
        return [dict(r) for r in rows]


def set_feedback_status(guid: str, status: str) -> bool:
    """Mark a feedback message handled ('done') or reopen it ('open'), and sync
    the mark to the other computer (LWW by status_ts)."""
    guid = (guid or "").strip()
    status = "done" if status == "done" else "open"
    if not guid:
        return False
    ts = _utc_now()
    with get_connection() as conn:
        cur = conn.execute("UPDATE feedback SET status=?, status_ts=? WHERE guid=?",
                           (status, ts, guid))
        if cur.rowcount == 0:
            return False
    _sync_log("fb_status", {"guid": guid, "status": status, "ts": ts})
    return True


def open_feedback_count() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM feedback WHERE status='open'").fetchone()
        return int(row["n"] or 0)


# ─── Tzintuk campaigns — Yemot HaMashiach voice notifications (v2.81) ─────────

def add_tzintuk_campaign(name: str, dist_date: str, template_id: str,
                         campaign_id: str, total: int, guid: str = "",
                         sent_at: str = "", device: str = "",
                         status: str = "sending") -> str:
    """Record one voice-notification send. Idempotent by guid (also used when
    the record arrives from the other computer / seed). Returns the guid.
    status 'scheduled' (#xi85i) = server-side scheduled campaign: campaign_id
    holds the Yemot schedId and sent_at holds the planned run time."""
    guid = (guid or "").strip() or uuid.uuid4().hex
    now = _utc_now()
    sent_at = sent_at or now
    status = status or "sending"
    # status_ts = NOW, never sent_at: a scheduled record's sent_at is the
    # planned FUTURE time, and a future status_ts made the peer reject every
    # later update (cancel / sending / done) as "older" under LWW.
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM tzintuk_campaigns WHERE guid=?",
                        (guid,)).fetchone():
            return guid
        conn.execute(
            "INSERT INTO tzintuk_campaigns (guid, name, sent_at, dist_date, "
            "template_id, campaign_id, device, total, status, status_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (guid, name or "", sent_at, dist_date or "", str(template_id or ""),
             campaign_id or "", device or "", int(total or 0), status, now))
    _sync_log("tz_add", {"guid": guid, "name": name or "", "sent_at": sent_at,
                         "dist_date": dist_date or "",
                         "template_id": str(template_id or ""),
                         "campaign_id": campaign_id or "", "device": device or "",
                         "total": int(total or 0), "status": status,
                         "status_ts": now})
    return guid


def update_tzintuk_campaign(guid: str, delivered: int, failed: int,
                            status: str, report_json: str = "",
                            campaign_id: str | None = None,
                            sent_at: str | None = None) -> bool:
    """Progress/result update for a campaign (LWW by status_ts when syncing).
    campaign_id/sent_at update only when given — used when a scheduled campaign
    actually runs (schedId → the real campaignId, planned time → run time)."""
    guid = (guid or "").strip()
    if not guid:
        return False
    ts = _utc_now()
    sets = "delivered=?, failed=?, status=?, status_ts=?, report_json=?"
    args = [int(delivered or 0), int(failed or 0), status or "sending", ts,
            report_json or ""]
    if campaign_id is not None:
        sets += ", campaign_id=?"
        args.append(str(campaign_id))
    if sent_at is not None:
        sets += ", sent_at=?"
        args.append(sent_at)
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE tzintuk_campaigns SET {sets} WHERE guid=?", (*args, guid))
        if cur.rowcount == 0:
            return False
    payload = {"guid": guid, "delivered": int(delivered or 0),
               "failed": int(failed or 0),
               "status": status or "sending", "ts": ts,
               "report_json": report_json or ""}
    if campaign_id is not None:
        payload["campaign_id"] = str(campaign_id)
    if sent_at is not None:
        payload["sent_at"] = sent_at
    _sync_log("tz_update", payload)
    return True


def get_tzintuk_campaigns(limit: int | None = None, statuses=None):
    """Campaign history, newest first (both computers' sends). `statuses`
    (v3.27) filters in SQL — the callers that look for pending schedules /
    a running send must not be capped by a LIMIT that the (future-dated,
    first-sorted) scheduled records can fill up on their own."""
    q = "SELECT * FROM tzintuk_campaigns"
    args: tuple = ()
    if statuses:
        st = tuple(str(s) for s in statuses)
        q += " WHERE status IN (%s)" % ",".join("?" * len(st))
        args = st
    q += " ORDER BY sent_at DESC, id DESC"
    if limit:
        q += " LIMIT ?"
        args = (*args, int(limit))
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(q, args)]


def get_tzintuk_campaign(guid: str):
    """One campaign record by guid (None when unknown)."""
    if not guid:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tzintuk_campaigns WHERE guid=?",
                           (guid,)).fetchone()
        return dict(row) if row else None


def tzintuk_campaign_for_date(dist_date: str):
    """The newest campaign already sent for this distribution date — the
    double-send guard across both computers. None when nothing was sent."""
    if not dist_date:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tzintuk_campaigns WHERE dist_date=? "
            "AND status NOT IN ('canceled','sched_failed') "
            "ORDER BY sent_at DESC LIMIT 1", (dist_date,)).fetchone()
        return dict(row) if row else None


# ─── Mail campaigns + templates (v3.39) ───────────────────────────────────────

def add_mail_campaign(subject: str, body: str, audience: str, sender: str,
                      total: int, guid: str = "", device: str = "",
                      status: str = "sending", sent_at: str = "",
                      attachment: str = "", with_header: int = 1) -> str:
    """רישום שליחת-מיילים אחת. Idempotent לפי guid (משמש גם לרשומה שמגיעה
    מהמחשב השני). מחזיר guid. v3.47: `attachment` (נתיב הקובץ המצורף) +
    `with_header` נשמרים כדי ששליחה-חוזרת תשלח את המקור, לא את הטיוטה."""
    guid = (guid or "").strip() or uuid.uuid4().hex
    now = _utc_now()
    sent_at = sent_at or now
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM mail_campaigns WHERE guid=?", (guid,)).fetchone():
            return guid
        conn.execute(
            "INSERT INTO mail_campaigns (guid, sent_at, subject, body, audience, sender, "
            "device, total, status, status_ts, attachment, with_header) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (guid, sent_at, subject or "", body or "", audience or "", sender or "",
             device or "", int(total or 0), status or "sending", now,
             attachment or "", 1 if with_header else 0))
    _sync_log("mail_add", {"guid": guid, "sent_at": sent_at, "subject": subject or "",
                           "body": body or "", "audience": audience or "",
                           "sender": sender or "", "device": device or "",
                           "total": int(total or 0), "status": status or "sending",
                           "status_ts": now, "attachment": attachment or "",
                           "with_header": 1 if with_header else 0})
    return guid


def update_mail_campaign(guid: str, sent: int, failed: int, status: str,
                         report_json: str = "", sync: bool = True) -> bool:
    """עדכון התקדמות/תוצאה (LWW לפי status_ts = עכשיו). `sync=False` (v3.42) =
    כתיבה מקומית בלבד — התקדמות תוך כדי שליחה, כדי ששליחה שנקטעה (התוכנה
    נסגרה) תדע מי כבר קיבל, בלי להציף את יומן הסנכרון בכל נמען; הסיכום
    בסוף (או 'interrupted' בהפעלה הבאה) מסתנכרן כרגיל."""
    guid = (guid or "").strip()
    if not guid:
        return False
    ts = _utc_now()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE mail_campaigns SET sent=?, failed=?, status=?, status_ts=?, "
            "report_json=? WHERE guid=?",
            (int(sent or 0), int(failed or 0), status or "sending", ts,
             report_json or "", guid))
        if cur.rowcount == 0:
            return False
    if not sync:
        return True
    _sync_log("mail_update", {"guid": guid, "sent": int(sent or 0),
                              "failed": int(failed or 0), "status": status or "sending",
                              "ts": ts, "report_json": report_json or ""})
    return True


def get_mail_campaigns(limit: int | None = None) -> list[dict]:
    q = "SELECT * FROM mail_campaigns ORDER BY sent_at DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(q)]


def get_mail_campaign(guid: str):
    if not guid:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM mail_campaigns WHERE guid=?", (guid,)).fetchone()
        return dict(row) if row else None


def get_mails_for_recipient(rec_id: int, guid: str = "") -> list[dict]:
    """המיילים שנשלחו למקבל (לפי report_json) — לכרטיס בחיפוש מהיר.
    מחזיר [{sent_at, subject, status, email, error}] מהחדש לישן.
    v3.44: התאמה לפי **guid** (יציב בין המחשבים) כשהשורה נושאת אותו; `rec_id`
    הוא מזהה מקומי — במחשב השני אותו מספר = אדם אחר."""
    if not guid:
        rec = get_recipient(rec_id)
        guid = ((rec or {}).get("guid") or "").strip()
    out = []
    for c in get_mail_campaigns():
        try:
            rows = json.loads(c.get("report_json") or "[]")
        except Exception:
            rows = []
        for r in rows:
            rg = (r.get("guid") or "").strip()
            hit = (rg == guid) if rg else (r.get("rec_id") is not None
                                           and str(r.get("rec_id")) == str(rec_id))
            if hit:
                out.append({"sent_at": c.get("sent_at", ""), "subject": c.get("subject", ""),
                            "status": r.get("status", ""), "email": r.get("email", ""),
                            "error": r.get("error", "")})
    return out


def upsert_mail_template(name: str, subject: str, body: str, guid: str = "",
                         updated_at: str = "", deleted: int = 0) -> str:
    """שמירת תבנית (חדשה או עדכון לפי guid). LWW לפי updated_at."""
    guid = (guid or "").strip() or uuid.uuid4().hex
    ts = updated_at or _utc_now()
    with get_connection() as conn:
        row = conn.execute("SELECT updated_at FROM mail_templates WHERE guid=?",
                           (guid,)).fetchone()
        if row:
            if (row["updated_at"] or "") > ts:
                return guid
            conn.execute("UPDATE mail_templates SET name=?, subject=?, body=?, "
                         "updated_at=?, deleted=? WHERE guid=?",
                         (name or "", subject or "", body or "", ts, int(deleted), guid))
        else:
            conn.execute("INSERT INTO mail_templates (guid, name, subject, body, "
                         "updated_at, deleted) VALUES (?,?,?,?,?,?)",
                         (guid, name or "", subject or "", body or "", ts, int(deleted)))
    _sync_log("mtpl_upsert", {"guid": guid, "name": name or "", "subject": subject or "",
                              "body": body or "", "updated_at": ts,
                              "deleted": int(deleted)})
    return guid


def delete_mail_template(guid: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM mail_templates WHERE guid=?", (guid,)).fetchone()
        t = dict(row) if row else None
    if t:
        upsert_mail_template(t["name"], t["subject"], t["body"], guid=guid, deleted=1)


def get_mail_templates() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM mail_templates WHERE deleted=0 ORDER BY name COLLATE NOCASE")]


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


def _restored(before: dict) -> dict:
    """A card re-created by a manager undo is a NEW write: stamped now. With its
    old updated_at the other computer's resurrection guard (delete newer than the
    card) dropped it, so the undo never reached the computer that deleted."""
    data = {k: v for k, v in before.items() if k not in ("id", "updated_at")}
    data["updated_at"] = _utc_now()
    return data


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
                          if k not in ("id", "updated_at", "created_at",
                                       "last_distribution", "next_distribution")}
                if local:
                    update_recipient(local["id"], fields, source="undo")
                else:
                    add_recipient(_restored(before))   # vanished locally → recreate
        elif op == "rec_delete":
            if before is not None and not get_recipient_by_guid(guid):
                add_recipient(_restored(before))   # restore the deleted recipient
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
        "active": active, "suspended": suspended,
        "total_souls": total_souls, "dists_month": dists_month, "dists_total": dists_total,
        "overdue": overdue,
        "by_freq": [dict(r) for r in by_freq],
        "by_area": [dict(r) for r in by_area],
    }


# ─── Reset ───────────────────────────────────────────────────────────────────

def reset_all_data(tzintuk: bool = False):
    """Delete ALL recipients, distributions, distribution batches, and change_log.
    Settings are kept. dist_batches must be cleared too — otherwise a reset leaves
    orphaned batch rows behind, so the 'חלוקות' tab keeps showing phantom
    distributions whose per-recipient rows are already gone (bug H1).
    tzintuk=True (v3.27, the "אפס נתונים" button only) also wipes the
    voice-call history; a replace-import of recipients keeps it."""
    with get_connection() as conn:
        conn.execute("DELETE FROM distributions")
        conn.execute("DELETE FROM dist_batches")
        conn.execute("DELETE FROM change_log")
        conn.execute("DELETE FROM sync_deleted")
        conn.execute("DELETE FROM deleted_recipients")
        conn.execute("DELETE FROM merged_guids")
        conn.execute("DELETE FROM recipients")
        # v3.27 — the voice-call history goes too: it holds the phone numbers
        # of the recipients just deleted and drives the "already sent for
        # this date" guard (a reset used to keep test sends alive forever).
        # With sync on, restart_from_peer brings the real history back.
        if tzintuk:
            conn.execute("DELETE FROM tzintuk_campaigns")
            conn.execute("DELETE FROM mail_campaigns")


# ─── Import helpers ───────────────────────────────────────────────────────────

def import_recipients_from_list(rows: list[dict]) -> tuple[int, int, list[dict]]:
    """Bulk import - adds new records; for existing ones, fills only empty fields.
    Returns (added, updated, conflicts) counts."""
    # next_distribution is derived only (v3.60, _recompute_recipient_dates) — the
    # file's column is ignored; last_distribution becomes the base date.
    updatable = ["phone1", "phone2", "phone3", "address", "area", "souls",
                 "frequency", "start_date", "last_distribution",
                 "external_id", "source", "birth_date", "spouse_birth_date",
                 "id_number", "spouse_id_number",
                 "children_home", "children_married", "children_total",
                 "marital_status", "email", "synagogue",
                 "housing_expenses", "medical_expenses", "income", "per_soul",
                 "work_scope", "parent_type", "occupation", "representative",
                 "priority", "priority_raw", "holiday_support", "holidays"]
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
        touched = []      # ids to send to the other computer once committed
        change_ops = []   # v3.63: rec_change payloads (history of merged fields)
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
                    ch = _log_changes(conn, ex["id"], ex, updates, "import")  # v3.63
                    if ch:
                        change_ops.append(ch)
                    sets = ", ".join(f"{k}=?" for k in updates)
                    vals = list(updates.values()) + [ex["id"]]
                    conn.execute(f"UPDATE recipients SET {sets} WHERE id=?", vals)
                    conn.execute("UPDATE recipients SET updated_at=? WHERE id=?",
                                 (_utc_now(), ex["id"]))
                    touched.append(ex["id"])
                    ex.update(updates)
                    updated += 1
                    _adopt_last_base(conn, ex["id"])
                    _recompute_recipient_dates(conn, ex["id"])
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
                conn.execute("UPDATE recipients SET guid=?, updated_at=? WHERE id=?",
                             (uuid.uuid4().hex, _utc_now(), cur.lastrowid))
                touched.append(cur.lastrowid)
                _adopt_last_base(conn, cur.lastrowid)
                _recompute_recipient_dates(conn, cur.lastrowid)
                existing[name] = {"id": cur.lastrowid, "full_name": name,
                                  **{c: row.get(c, "") for c in insert_cols if c != "full_name"}}
                added += 1
    if touched:
        with get_connection() as conn:     # one read for all (500-row imports)
            marks = ",".join("?" * len(touched))
            recs = [dict(r) for r in conn.execute(
                f"SELECT * FROM recipients WHERE id IN ({marks})", touched)]
        for rec in recs:
            _sync_log("rec_upsert", {"guid": rec.get("guid") or "",
                                     "data": {k: v for k, v in rec.items() if k != "id"}})
    for ch in change_ops:
        _sync_log("rec_change", ch)
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
    "priority", "priority_raw", "holiday_support", "holidays",
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
    same_name = []    # משימה 7: אותו שם, טלפון שונה → הצעת מיזוג (לא "שינוי" שדורס)
    new_by_key = {}   # the same NEW person twice in one file → one card
    for row in rows:
        name = (row.get("full_name") or "").strip()
        if not name:
            continue
        blank = row.get("_blank_fields") or ()   # numeric cells empty in the file
        match = None
        by_ext_match = False
        ext = (row.get("external_id") or "").strip()
        if ext and len(by_ext.get(ext, [])) == 1:
            match = by_ext[ext][0]
            by_ext_match = True
        elif len(by_name.get(name, [])) == 1:
            match = by_name[name][0]
        elif len(by_name.get(name, [])) > 1:
            dupes += 1
            continue
        if match is None:
            key = ("ext", ext) if ext else ("name", name)
            first = new_by_key.get(key)
            if first is None:
                first = {k: v for k, v in row.items() if k != "_blank_fields"}
                new_by_key[key] = first
                new_rows.append(first)
            else:
                # later rows fill what the earlier one left empty
                for k, v in row.items():
                    if k != "_blank_fields" and k not in blank \
                            and _norm_val(k, v) and not _norm_val(k, first.get(k)):
                        first[k] = v
            continue
        changes = {}
        for field in _IMPORT_DIFF_FIELDS:
            if field not in row or field in blank:
                continue
            new_norm = _norm_val(field, row.get(field))
            old_norm = _norm_val(field, match.get(field))
            # Only a real, non-emptying change counts — never let a blank cell in
            # the file wipe existing data.
            if new_norm and new_norm != old_norm:
                changes[field] = {"old": match.get(field), "new": row.get(field)}
        inc_phones = [row.get(f) for f in _PHONE_SLOTS
                      if row.get(f) and f not in blank and phone_key(row.get(f))]
        if not by_ext_match and phones_conflict(recipient_phones(match), inc_phones):
            # Same name, different number: maybe the same person with a second phone,
            # maybe two people. Never decide silently — the operator chooses.
            same_name.append({"id": match["id"], "full_name": name,
                              "existing_phones": recipient_phones(match),
                              "incoming_phones": [str(p).strip() for p in inc_phones],
                              "row": {k: v for k, v in row.items() if k != "_blank_fields"}})
            for f in _PHONE_SLOTS:
                changes.pop(f, None)
        if changes:
            updates.append({"id": match["id"], "full_name": name, "changes": changes})
    return {"new": new_rows, "updates": updates, "unmatched_dupes": dupes,
            "same_name": same_name}


def apply_import_confirmed(new_rows: list[dict], updates: list[dict],
                           same_name: list | None = None) -> tuple[int, int]:
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
            update_recipient(u["id"], fields, source="import")
            updated += 1
    # משימה 7 — אותו שם, טלפון שונה: לפי בחירת המפעיל בלבד (merge / separate / skip)
    for d in same_name or []:
        choice = d.get("choice")
        if choice == "merge":
            if merge_into_recipient(d["id"], d.get("row") or {}, source="merge"):
                updated += 1
        elif choice == "separate":
            add_recipient(d.get("row") or {})
            added += 1
    return added, updated
