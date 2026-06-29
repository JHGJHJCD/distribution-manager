import os
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


def auto_backup():
    """Backup data.db using SQLite's Online Backup API (WAL-safe).
    Returns True on success, False on failure. Falls back to a default backups
    folder in the stable data dir, so backups happen even if the user never
    configured a folder."""
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

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_folder, f"backup_{ts}.db")

        # Use SQLite Online Backup API — handles WAL mode correctly.
        # This is the only safe way to copy a WAL-mode database.
        src_conn = sqlite3.connect(db.DB_PATH)
        dst_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Keep only last 30 backups
        backups = sorted(
            [f for f in os.listdir(backup_folder)
             if f.startswith("backup_") and f.endswith(".db")]
        )
        for old in backups[:-30]:
            try:
                os.remove(os.path.join(backup_folder, old))
            except Exception:
                pass

        try:
            db.set_setting("last_backup_at", datetime.now().isoformat(timespec="seconds"))
        except Exception:
            pass

        return True

    except Exception:
        return False
