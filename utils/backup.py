import os
import shutil
import sqlite3
import threading
from datetime import datetime


def restore_from_backup(backup_path: str) -> bool:
    """Restore data.db from a backup .db file using SQLite Online Backup API.
    Refuses (returns False) if the file is not a valid app database — so picking
    a wrong/corrupt file never overwrites the real data. Returns True on success."""
    try:
        import database as db
        src_conn = sqlite3.connect(backup_path)
        try:
            # Only restore from something that actually looks like our DB.
            valid = src_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recipients'"
            ).fetchone()
            if not valid:
                return False
            dst_conn = sqlite3.connect(db.DB_PATH)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()
        return True
    except Exception:
        return False


def auto_backup_async():
    """Non-blocking fire-and-forget backup — does not return a result."""
    threading.Thread(target=auto_backup, daemon=True).start()


# How many of each backup kind to keep. THREE independent buckets so that
# frequent routine backups can never evict the durable daily snapshots or the
# pre-destructive safety points (bug C1: a single 30-slot ring meant an
# accidental reset's safety backup was churned out within ~30 ordinary saves,
# leaving nothing to recover from once the mistake was noticed weeks later).
_KEEP_ROUTINE = 20   # 'backup_*'  — every launch/save
_KEEP_DAILY = 30     # 'daily_*'   — one per calendar day (≈ a month of history)
_KEEP_SAFETY = 10    # 'safety_*'  — taken before reset/restore
# Total bounded at ~60 files — durable in TIME, never unbounded in volume.


def _prune_backups(folder, prefix, keep):
    """Keep only the newest `keep` files named '<prefix>*.db' in `folder`.
    Filenames embed a sortable timestamp, so a lexicographic sort is chronological
    and the oldest ones sort first."""
    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.startswith(prefix) and f.endswith(".db"))
    except OSError:
        return
    for old in files[:-keep]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass


def auto_backup(kind: str = "routine"):
    """Backup data.db using SQLite's Online Backup API (WAL-safe).
    Returns True on success, False on failure, None if no writable folder exists.

    Retention uses three independent buckets so recovery stays durable in TIME
    without unbounded growth in volume (bug C1):
      • routine ('backup_*') — every launch/save; newest _KEEP_ROUTINE kept.
      • daily   ('daily_*')  — one snapshot per calendar day; _KEEP_DAILY days.
      • safety  ('safety_*') — before a destructive action (reset/restore); its
                               OWN bucket, so routine churn can never evict it.
    `kind='safety'` writes into the safety bucket; anything else is routine and
    also refreshes today's daily snapshot. The public signature/return values are
    unchanged, so existing callers (auto_backup()) keep working."""
    try:
        import database as db
        backup_folder = db.get_setting("backup_folder")
        if not backup_folder or not os.path.isdir(backup_folder):
            # Default location — always available, survives EXE upgrades.
            backup_folder = db.BACKUP_DIR
            try:
                os.makedirs(backup_folder, exist_ok=True)
            except Exception:
                return None

        if not os.path.exists(db.DB_PATH):
            return False

        now = datetime.now()
        # Microsecond resolution + a uniquifying loop so two backups in the same
        # instant never overwrite each other (the old second-resolution name
        # silently collided, quietly losing a recovery point).
        ts = now.strftime("%Y%m%d_%H%M%S_%f")
        prefix = "safety_" if kind == "safety" else "backup_"
        dest = os.path.join(backup_folder, f"{prefix}{ts}.db")
        _n = 1
        while os.path.exists(dest):
            dest = os.path.join(backup_folder, f"{prefix}{ts}_{_n}.db")
            _n += 1

        # Use SQLite Online Backup API — handles WAL mode correctly.
        # This is the only safe way to copy a WAL-mode database.
        src_conn = sqlite3.connect(db.DB_PATH)
        dst_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Routine backups also refresh TODAY's durable daily snapshot (once/day).
        # The routine backup file is already self-contained (checkpointed by the
        # Online Backup API), so a plain copy is safe here.
        if kind != "safety":
            daily = os.path.join(backup_folder, f"daily_{now.strftime('%Y%m%d')}.db")
            if not os.path.exists(daily):
                try:
                    shutil.copy2(dest, daily)
                except OSError:
                    pass

        # Prune each bucket independently — one bucket's churn never touches another.
        _prune_backups(backup_folder, "backup_", _KEEP_ROUTINE)
        _prune_backups(backup_folder, "daily_", _KEEP_DAILY)
        _prune_backups(backup_folder, "safety_", _KEEP_SAFETY)

        try:
            db.set_setting("last_backup_at", now.isoformat(timespec="seconds"))
        except Exception:
            pass

        return True

    except Exception:
        return False
