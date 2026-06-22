# -*- coding: utf-8 -*-
"""Verify data-safety: legacy-DB migration + default automatic backups."""
import os, sys, tempfile, sqlite3, shutil
os.environ["PYTHONUTF8"] = "1"
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
check("a backup file was written to the default dir", len(backups) == 1 and backups[0].endswith(".db"))

print("\nRESULT:", "ALL PASS ✓" if ok else "FAILURES ✗")
sys.exit(0 if ok else 1)
