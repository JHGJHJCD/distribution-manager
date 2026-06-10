import os
import sqlite3
import threading
from datetime import datetime


def restore_from_backup(backup_path: str) -> bool:
    """Restore data.db from a backup .db file using SQLite Online Backup API.
    Returns True on success, False on failure."""
    try:
        import database as db
        src_conn = sqlite3.connect(backup_path)
        dst_conn = sqlite3.connect(db.DB_PATH)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        return True
    except Exception:
        return False


def auto_backup_async():
    """Non-blocking fire-and-forget backup — does not return a result."""
    threading.Thread(target=auto_backup, daemon=True).start()


def auto_backup():
    """Backup data.db using SQLite's Online Backup API (WAL-safe).
    Returns True on success, None if no folder configured, False on failure."""
    try:
        import database as db
        backup_folder = db.get_setting("backup_folder")
        if not backup_folder or not os.path.isdir(backup_folder):
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
