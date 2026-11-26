# -*- coding: utf-8 -*-
"""Stage 5 — backup and restore, from the settings screen. Plain functions (no web framework),
like web/service.py.

A backup is a full copy of the site's database, written beside it (config.backup_dir()) with
SQLite's own backup, which is safe while the site is running. The site takes one by itself
on every day it is used (`daily`, on the day's first request — so it holds the state before
anything of that day was done) and before every large step (a week that passed becomes
history, a card is deleted, two cards are merged, a restore); the manager can take one
whenever he wants. NOTHING HERE EVER DELETES A BACKUP.

Restoring puts the whole database back to what a backup holds: the cards, the history, the
settings, what was set by hand. It is the one action on the site that changes the past, so:
  * only a file of the site's own backup folder can be named (never a path);
  * the file is checked first — it opens, it is sound, it is a database of this site and not
    of a newer version of it;
  * the state of this very moment is backed up before anything is touched, so a restore can
    always be undone by restoring that backup. If that backup cannot be taken, nothing is done;
  * afterwards the site is checked to hold exactly what the backup held.

A backup holds everything, phones included — so it never leaves through the browser: the
screen is told where the files are, when each was taken and how much is in it (numbers).
Never its content.
"""
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import config, planner, service, store
from .service import Refused

# haluka-<day>-<time>-<why>[-<n>].db  (the names store.backup gives; n = taken in the same second)
NAME = re.compile(r"^haluka-(\d{8})-(\d{6})-([A-Za-z0-9_-]+?)(?:-(\d+))?\.db$")
MANUAL, DAILY, BEFORE_RESTORE = "manual", "daily", "before-restore"
# why a backup was taken, in the words of the screen (the key is the name the code gave it)
REASONS = {
    MANUAL: "גיבוי ביד",
    DAILY: "גיבוי יומי",
    BEFORE_RESTORE: "לפני שחזור",
    "before-closing-weeks": "לפני ששבוע שעבר נכנס להיסטוריה",
    "before-delete-card": "לפני מחיקת כרטיס",
    "before-merge-cards": "לפני מיזוג כרטיסים",
    "before-reimport": "לפני ייבוא מחדש מהתוכנה הישנה",
    "offsite": "עותק שיוצא מהשרת",              # web/offsite.py: lives in the outbox only until it left
}
DAY_KEY = "daily_backup_day"          # meta: the last day whose daily backup was taken
# what a file must hold to be a database of this site
REQUIRED_TABLES = ("meta", "settings", "recipients", "batches", "history", "weeks")
_BROKEN = "הגיבוי הזה פגום, ואי אפשר לשחזר ממנו"
_NOT_OURS = "הקובץ הזה אינו גיבוי של האתר"
_NOT_FOUND = "הגיבוי הזה לא נמצא בתיקיית הגיבויים"
_BUSY = "האתר עסוק כרגע, ולכן לא שחזרתי כלום. אפשר לנסות שוב בעוד רגע."


# ── the list ──────────────────────────────────────────────────────────────────
def _entry(folder: str, name: str):
    """What the list shows of one backup file, from its name and its size alone."""
    m = NAME.match(name)
    if not m:
        return None
    day, clock, reason, again = m.groups()
    try:
        taken = datetime.strptime(day + clock, "%Y%m%d%H%M%S")
        info = os.stat(os.path.join(folder, name))
    except (ValueError, OSError):
        return None
    return {"name": name, "taken_at": taken.strftime("%Y-%m-%d %H:%M"), "reason": reason,
            "reason_text": REASONS.get(reason, reason), "size_kb": max(1, round(info.st_size / 1024)),
            # by the time in the name; files of the same second, in the order they were written
            "_order": (taken, info.st_mtime_ns, int(again or 1), name)}


def _all(folder: str) -> list:
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = [e for e in (_entry(folder, n) for n in names) if e]
    found.sort(key=lambda e: e.pop("_order"), reverse=True)
    return found


def listing(conn, now: datetime, db_path: str = None) -> dict:
    """Every backup there is, the latest first — when, why and how big. No content."""
    folder = config.backup_dir()
    backups = _all(folder)
    return {"folder": folder, "backups": backups, "total": len(backups),
            "total_kb": sum(b["size_kb"] for b in backups),
            # False = today's automatic backup could not be taken (the screen says so)
            "auto_today": store.get_meta(conn, DAY_KEY) == now.date().isoformat()}


# ── taking a backup ───────────────────────────────────────────────────────────
def make(conn, now: datetime, db_path: str) -> dict:
    """A backup of this moment, because the manager asked for one."""
    try:
        made = store.backup(db_path, config.backup_dir(), MANUAL, now)
    except (OSError, sqlite3.Error):
        made = ""
    if not made or not os.path.exists(made):
        raise Refused("הגיבוי לא נוצר")
    return {"ok": True, "name": os.path.basename(made)}


def daily(conn, now: datetime, db_path: str) -> str:
    """One backup on every day the site is used, taken on the day's first request — before
    anything of that day is done. Returns the new file's name, or '' when today's was already
    taken. A backup that cannot be taken never stops the site: the day stays unmarked (so the
    next request tries again) and the settings screen says that today's backup is missing."""
    today = now.date().isoformat()
    try:
        if store.get_meta(conn, DAY_KEY) == today:
            return ""
        with store.tx(conn):
            if store.get_meta(conn, DAY_KEY) == today:      # another request got here first
                return ""
            made = store.backup(db_path, config.backup_dir(), DAILY, now)
            if not made:
                return ""
            store.set_meta(conn, DAY_KEY, today)
    except (OSError, sqlite3.Error):
        return ""
    return os.path.basename(made)


# ── what is inside a database, in numbers ─────────────────────────────────────
def _counts(conn) -> dict:
    """How much a database holds — numbers only: cards, history, where the history ends.
    Only what every version of the site's database has is asked for, so that an older
    backup is counted too."""
    def one(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    def columns(table):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    last = conn.execute("SELECT value FROM meta WHERE key='closed_through'").fetchone()
    ahead = 0
    if columns("events"):                                    # a backup from before stage 4 has no events
        alive = " AND deleted_at IS NULL" if "deleted_at" in columns("events") else ""
        ahead = one("SELECT COUNT(*) FROM events WHERE closed_at IS NULL" + alive)
    return {
        "cards": one("SELECT COUNT(*) FROM recipients"),
        "active": one("SELECT COUNT(*) FROM recipients WHERE status=?", planner.ACTIVE),
        "history_rows": one("SELECT COUNT(*) FROM history"),
        "rounds": one("SELECT COUNT(*) FROM batches"),
        "last_week": (last[0] if last else "") or "",
        "events_ahead": ahead,
    }


def _path(name: str) -> str:
    """The file of a backup that is named by the screen — a bare name of the backup folder,
    never a path (so nothing outside that folder can ever be read or restored)."""
    if not isinstance(name, str) or not NAME.match(name) or os.path.basename(name) != name:
        raise Refused(_NOT_FOUND)
    path = os.path.join(config.backup_dir(), name)
    if os.path.islink(path) or not os.path.isfile(path):
        raise Refused(_NOT_FOUND)
    return path


def _open_read_only(path: str):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def check(path: str) -> dict:
    """Is this file a sound database of this site? Returns how much it holds (numbers), or
    refuses in words. The file is opened for reading only."""
    try:
        c = _open_read_only(path)
    except sqlite3.Error:
        raise Refused(_BROKEN)
    try:
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Refused(_BROKEN)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(REQUIRED_TABLES) <= tables:
            raise Refused(_NOT_OURS)
        version = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        try:
            other = version is None or int(version[0]) > store.SCHEMA_VERSION
        except (TypeError, ValueError):
            other = True
        if other:
            raise Refused("הגיבוי הזה נוצר בגרסה אחרת של האתר, ואי אפשר לשחזר ממנו")
        return _counts(c)
    except sqlite3.Error:
        raise Refused(_BROKEN)
    finally:
        c.close()


def _weeks_between(earlier: str, later: str) -> int:
    """How many weeks the history of `later` reaches beyond the history of `earlier` (0 when
    it does not, or when one of them is not known)."""
    try:
        return max(0, (date.fromisoformat(later) - date.fromisoformat(earlier)).days // 7)
    except (TypeError, ValueError):
        return 0


# ── restoring ─────────────────────────────────────────────────────────────────
def inspect(conn, now: datetime, name: str, db_path: str = None) -> dict:
    """What a backup holds beside what the site holds now — so that the manager sees what
    a restore would bring back and what it would lose, before he decides."""
    path = _path(name)
    inside = check(path)
    service.roll_forward(conn, now, db_path)                 # "now" = after what has passed is history
    current = _counts(conn)
    entry = _entry(config.backup_dir(), name)
    return {"name": name, "taken_at": entry["taken_at"], "reason_text": entry["reason_text"],
            "backup": inside, "now": current,
            # weeks that are history today and were still ahead when the backup was taken:
            # after a restore the site writes them again, computed from what the backup holds
            "weeks_to_redo": _weeks_between(inside["last_week"], current["last_week"])}


def restore(conn, now: datetime, name: str, db_path: str) -> dict:
    """Put the whole database back to what the backup `name` holds. The state of this moment
    is backed up first ('before-restore'); restoring that file undoes the restore."""
    path = _path(name)
    if os.path.exists(db_path) and os.path.samefile(path, db_path):
        raise Refused(_NOT_FOUND)                  # the site's own database is not a backup of itself
    inside = check(path)
    try:
        safety = store.backup(db_path, config.backup_dir(), BEFORE_RESTORE, now)
    except (OSError, sqlite3.Error):
        safety = ""
    if not safety or not os.path.exists(safety):
        raise Refused("לא הצלחתי לשמור גיבוי של המצב הנוכחי, ולכן לא שחזרתי כלום")
    try:
        check(safety)                              # never go on without a sound way back
    except Refused:
        raise Refused("הגיבוי של המצב הנוכחי לא יצא תקין, ולכן לא שחזרתי כלום")
    kept = os.path.basename(safety)
    src = _open_read_only(path)
    dst = sqlite3.connect(db_path, timeout=1)
    try:
        day_mark = store.get_meta(conn, DAY_KEY)
        store.copy_database(src, dst)              # the whole file in one step: all of it or none of it
    except sqlite3.OperationalError:
        raise Refused(_BUSY)
    finally:
        dst.close()
        src.close()
    if check(db_path) != inside:
        raise Refused(f"השחזור לא הושלם כמו שצריך. המצב שהיה לפניו שמור בגיבוי {kept}")
    # a backup from before a later table / column existed gets them now (additive only)
    store._ensured.discard(db_path)
    store.ensure_schema(db_path)
    if day_mark:
        # today's automatic backup was already taken (it holds the state before the restore):
        # the restored state is not backed up again as if it were this morning's
        with store.tx(conn):
            store.set_meta(conn, DAY_KEY, day_mark)
    return {"ok": True, "restored": name, "safety": kept, "backup": inside}
