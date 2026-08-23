# -*- coding: utf-8 -*-
"""Verify data-safety: legacy-DB migration + default automatic backups."""
import os, sys, tempfile, sqlite3, shutil
os.environ["PYTHONUTF8"] = "1"
# Force UTF-8 console output so the ✓/✗ characters in the report never crash the
# test on a legacy Windows code page (cp1255). Setting PYTHONUTF8 above is too
# late — the interpreter reads it only at startup — so reconfigure the streams.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import database as db

WORK = os.path.join(tempfile.gettempdir(), "ms_safety")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)

ok = True
def check(label, cond):
    global ok; ok = ok and cond
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")

# ── 1. migration: an old DB next to the EXE is brought into the stable dir ──────
# Build a realistic legacy DB using the app itself.
legacy = os.path.join(WORK, "legacy_data.db")
db.DB_PATH = legacy
db.init_db()
db.add_recipient({"full_name": "משה ישראלי", "phone1": "0501234567", "status": "פעיל"})

db.DB_PATH = os.path.join(WORK, "stable", "data.db")
os.makedirs(os.path.dirname(db.DB_PATH), exist_ok=True)
for e in ("", "-wal", "-shm"):
    try: os.remove(db.DB_PATH + e)
    except OSError: pass

src = db.migrate_legacy_db_if_needed(candidates=[legacy], force=True)
check("migration copied the legacy DB", src == legacy and os.path.exists(db.DB_PATH))
c = sqlite3.connect(db.DB_PATH)
name = c.execute("SELECT full_name FROM recipients").fetchone()[0]
c.close()
check("migrated data is intact", name == "משה ישראלי")

# ── 2. migration is a no-op when the stable DB already exists ───────────────────
src2 = db.migrate_legacy_db_if_needed(candidates=[legacy], force=True)
check("no migration when data already present", src2 is None)

# ── 3. init_db works on the migrated DB (adds new columns, keeps data) ──────────
db.init_db()
recs = db.get_all_recipients()
check("init_db preserved migrated recipient", any(r["full_name"] == "משה ישראלי" for r in recs))

# ── 4. default automatic backup happens with NO configured folder ──────────────
db.BACKUP_DIR = os.path.join(WORK, "backups")
import importlib
import utils.backup as bk
importlib.reload(bk)
# ensure no backup_folder setting
db.set_setting("backup_folder", "")
result = bk.auto_backup()
backups = [f for f in os.listdir(db.BACKUP_DIR)] if os.path.isdir(db.BACKUP_DIR) else []
check("auto_backup returned True with no folder configured", result is True)
# A routine backup now writes TWO files: the routine snapshot + today's daily one.
check("a routine backup file was written to the default dir",
      any(f.startswith("backup_") and f.endswith(".db") for f in backups))
check("a daily snapshot was written to the default dir",
      any(f.startswith("daily_") and f.endswith(".db") for f in backups))

# ── 5. reset_all_data wipes distribution batches too (bug H1) ───────────────────
# A full reset must clear dist_batches as well — otherwise orphaned batch rows
# survive and the 'חלוקות' tab shows phantom distributions whose per-recipient
# rows are already gone.
rid = db.add_recipient({"full_name": "בדיקת איפוס", "status": "פעיל"})
db.bulk_add_distributions(
    [{"id": rid, "full_name": "בדיקת איפוס", "souls": 0, "frequency": "חד-פעמי"}],
    "2026-07-15", "", 0, "מחלק בדיקה", dist_name="חלוקת בדיקה")
check("a batch exists before reset", len(db.get_distribution_batches()) >= 1)
db.reset_all_data()
check("reset cleared dist_batches (no phantom batches)", db.get_distribution_batches() == [])
check("reset cleared recipients", db.get_all_recipients() == [])

# ── 6. self_heal_db restores the NEWEST valid non-empty backup, not the largest ──
# (bug H3) Three backups are created via the SAME Online Backup API auto_backup
# uses (self-contained, WAL-safe): an OLD+LARGE one (10), a NEW+SMALL one (2), and
# an EMPTY one whose mtime is newest of all. After the live DB is corrupted,
# self_heal must restore the SMALL one (newest valid & non-empty) — NOT the larger
# older one (would resurrect stale/deleted data) and NOT the empty one.
import time as _time
heal_dir = os.path.join(WORK, "heal")
db.DB_PATH = os.path.join(heal_dir, "data.db")
db.BACKUP_DIR = os.path.join(heal_dir, "backups")
os.makedirs(db.BACKUP_DIR, exist_ok=True)
for e in ("", "-wal", "-shm", ".corrupt.db"):
    try: os.remove(db.DB_PATH + e)
    except OSError: pass
# NOTE: we deliberately do NOT init_db() the live heal DB — we write raw garbage
# to it below to simulate real on-disk corruption. Opening it through the app
# first would leave a lingering WAL lock on Windows and prevent a clean corrupt.

def _seed(path, count):
    orig = db.DB_PATH
    db.DB_PATH = path
    for e in ("", "-wal", "-shm"):
        try: os.remove(path + e)
        except OSError: pass
    db.init_db()
    for i in range(count):
        db.add_recipient({"full_name": f"מקבל {i}", "status": "פעיל"})
    db.DB_PATH = orig

_src_big   = os.path.join(heal_dir, "src_big.db");   _seed(_src_big, 10)
_src_small = os.path.join(heal_dir, "src_small.db"); _seed(_src_small, 2)
_src_empty = os.path.join(heal_dir, "src_empty.db"); _seed(_src_empty, 0)

_bk_big   = os.path.join(db.BACKUP_DIR, "backup_big.db")
_bk_small = os.path.join(db.BACKUP_DIR, "backup_small.db")
_bk_empty = os.path.join(db.BACKUP_DIR, "backup_empty.db")
db._copy_db(_src_big, _bk_big)      # Online Backup API — self-contained, checkpointed
db._copy_db(_src_small, _bk_small)
db._copy_db(_src_empty, _bk_empty)

_base = _time.time()
os.utime(_bk_big,   (_base - 100000, _base - 100000))   # oldest, but LARGEST (10)
os.utime(_bk_small, (_base - 10,     _base - 10))        # newest VALID & non-empty (2)
os.utime(_bk_empty, (_base + 100000, _base + 100000))   # newest overall, but EMPTY

# Corrupt the live DB so self_heal must fall back to a backup.
for e in ("-wal", "-shm"):
    try: os.remove(db.DB_PATH + e)
    except OSError: pass
with open(db.DB_PATH, "wb") as f:
    f.write(os.urandom(20000))   # multi-page random blob → reliably "not a database"
check("corrupt live DB fails integrity", db._db_integrity_ok(db.DB_PATH) is False)

db.self_heal_db()
check("H3: self_heal restored NEWEST valid non-empty backup (small=2), not old-large/empty",
      db._db_recipient_count(db.DB_PATH) == 2)

# ── 7. C1 retention: routine churn never evicts the daily / safety points ───────
ret_dir = os.path.join(WORK, "retention")
db.DB_PATH = os.path.join(ret_dir, "data.db")
db.BACKUP_DIR = os.path.join(ret_dir, "backups")
os.makedirs(db.BACKUP_DIR, exist_ok=True)
for e in ("", "-wal", "-shm"):
    try: os.remove(db.DB_PATH + e)
    except OSError: pass
db.init_db()
db.add_recipient({"full_name": "ריטנשן", "status": "פעיל"})
bk.auto_backup(kind="safety")          # one pre-destructive safety point
for _ in range(40):                    # heavy routine churn (same calendar day)
    bk.auto_backup()
_files = os.listdir(db.BACKUP_DIR)
_n_routine = sum(1 for f in _files if f.startswith("backup_"))
_n_daily   = sum(1 for f in _files if f.startswith("daily_"))
_n_safety  = sum(1 for f in _files if f.startswith("safety_"))
check("C1: routine bucket capped (20)", _n_routine == 20)
check("C1: one daily snapshot per day kept", _n_daily == 1)
check("C1: safety point survived 40 routine backups", _n_safety == 1)
check("C1: total backup volume bounded (≤60)", len(_files) <= 60)

# ── 8. R1: corrupt DB + only-empty backups → no crash, corrupt kept, fresh start ─
# H3 skips empty (0-recipient) backups, so here there is NO usable backup to
# restore from. self_heal must still set the corrupt file aside (never delete it)
# so init_db recreates a fresh empty schema instead of crashing on it.
r1_dir = os.path.join(WORK, "r1")
db.DB_PATH = os.path.join(r1_dir, "data.db")
db.BACKUP_DIR = os.path.join(r1_dir, "backups")
os.makedirs(db.BACKUP_DIR, exist_ok=True)
for e in ("", "-wal", "-shm", ".corrupt.db"):
    try: os.remove(db.DB_PATH + e)
    except OSError: pass
_empty_src = os.path.join(r1_dir, "empty_src.db")
_seed(_empty_src, 0)                                   # a valid but EMPTY backup source
db._copy_db(_empty_src, os.path.join(db.BACKUP_DIR, "backup_empty.db"))
with open(db.DB_PATH, "wb") as f:                      # raw garbage → no WAL lock
    f.write(os.urandom(20000))
check("R1: live DB is corrupt before heal", db._db_integrity_ok(db.DB_PATH) is False)
_r1_crashed = False
try:
    db.self_heal_db()
    db.init_db()
except Exception:
    _r1_crashed = True
check("R1: self_heal + init_db did NOT crash (corrupt DB, only-empty backups)", not _r1_crashed)
check("R1: corrupt DB preserved as .corrupt.db (never deleted)",
      os.path.exists(db.DB_PATH + ".corrupt.db"))
check("R1: app continues on a fresh empty DB", db.get_all_recipients() == [])

# ── 9. R2: recipients-tab full-replace import backs up into the safety_ bucket ──
_recips_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tabs", "recipients.py")
with open(_recips_py, encoding="utf-8") as _f:
    _rsrc = _f.read()
check("R2: replace-import pre-wipe backup uses kind='safety'",
      'auto_backup(kind="safety")' in _rsrc)
check("R2: replace-import no longer uses a plain routine auto_backup() before reset",
      "auto_backup() is not True" not in _rsrc)

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.exit(0 if ok else 1)
