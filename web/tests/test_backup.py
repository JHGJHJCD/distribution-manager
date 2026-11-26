# -*- coding: utf-8 -*-
"""Backup and restore (stage 5) — on a throw-away database with invented people.

What is proved here: a backup is a full and sound copy; nothing is ever deleted from the
backup folder; a restore brings back exactly what the backup held, always leaves a way
back, and refuses anything that is not a sound backup of this site inside its own folder.

Run:  <python 3.12> web/tests/test_backup.py
"""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta

from _util import Checker, W0, person, wk

from web import backup_service as bk, config, event_service, service, settings_service, store
from web.service import Refused

t = Checker("web backup")
TMP = tempfile.mkdtemp(prefix="haluka_backup_")
# a folder with Hebrew letters and a space in its name, as on the fund's own computer
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "נתוני האתר")
NOW = datetime(W0.year, W0.month, W0.day, 10, 0)            # Wednesday morning
SECRET_PHONE = "0501234567"


def at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def refusal(fn) -> str:
    try:
        fn()
    except Refused as e:
        return str(e)
    return ""


def files() -> set:
    try:
        return set(os.listdir(config.backup_dir()))
    except OSError:
        return set()


def one(sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def state() -> dict:
    """Everything a restore must bring back, as plain values."""
    return {
        "cards": [tuple(r) for r in conn.execute("SELECT guid, full_name, phone1, status FROM recipients ORDER BY guid")],
        "history": [tuple(r) for r in conn.execute("SELECT guid, recipient_guid, dist_date FROM history ORDER BY guid")],
        "settings": sorted(store.get_settings(conn).items()),
        "by_hand": [tuple(r) for r in conn.execute("SELECT week_wed, recipient_guid, action FROM week_manual ORDER BY 1, 2")],
        "events": [tuple(r) for r in conn.execute("SELECT guid, event_date, portions FROM events ORDER BY guid")],
        "closed_through": store.get_meta(conn, "closed_through"),
    }


recs = ([person(n, "שבועי", phone1=SECRET_PHONE, holiday_support=1, holidays="חנוכה") for n in range(1, 5)]
        + [person(n, "חד-פעמי", 3, phone1=SECRET_PHONE) for n in range(21, 27)])
path = config.db_path()
store.create(path)
conn = store.connect(path)
with store.tx(conn):
    for r in recs:
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in r]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [r[c] for c in cols])
    for i, g in enumerate(("g0001", "g0002", "g0003", "g0004")):
        conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES (?,?,?, 'test')",
                     (f"h{i}", g, wk(-1).isoformat()))
    store.set_setting(conn, "default_portions", 6)
    store.set_meta(conn, "closed_through", wk(-1).isoformat())
N = len(recs)
seen = set()                # every backup file that ever existed during this run

# ── B1: before any backup exists ──────────────────────────────────────────────
ls = bk.listing(conn, NOW, path)
t.ok("B1 no backups yet: an empty list, the folder's place, and today's automatic backup is not there",
     ls["backups"] == [] and ls["total"] == 0 and ls["total_kb"] == 0 and ls["auto_today"] is False
     and ls["folder"] == config.backup_dir())

# ── B2: a backup the manager asked for ────────────────────────────────────────
made = bk.make(conn, at(1), path)
first = made["name"]
t.ok("B2 'back up now' writes one file into the backup folder, named by its time and its reason",
     made["ok"] is True and files() == {first} and first == f"haluka-{at(1).strftime('%Y%m%d-%H%M%S')}-manual.db")
t.ok("B2 the copy is sound and full: it holds exactly what the site holds",
     bk.check(os.path.join(config.backup_dir(), first)) == bk._counts(conn)
     and bk._counts(conn)["cards"] == N and bk._counts(conn)["active"] == N and bk._counts(conn)["history_rows"] == 4
     and bk._counts(conn)["last_week"] == wk(-1).isoformat())
second = bk.make(conn, at(1), path)["name"]
t.ok("B2 a second backup in the same second is a second file — the first is not written over",
     second != first and files() == {first, second})
ls = bk.listing(conn, at(2), path)
t.ok("B2 the list says when each was taken, why (in words), and how big — the later one first",
     [b["name"] for b in ls["backups"]] == [second, first] and ls["total"] == 2
     and all(b["reason_text"] == "גיבוי ביד" and b["taken_at"] == at(1).strftime("%Y-%m-%d %H:%M") and b["size_kb"] >= 1
             for b in ls["backups"])
     and ls["total_kb"] == sum(b["size_kb"] for b in ls["backups"]))
t.ok("B2 with no database there is nothing to back up, and that is said (not a crash, not an empty file)",
     "לא נוצר" in refusal(lambda: bk.make(conn, at(1), os.path.join(TMP, "none", "haluka.db"))) and files() == {first, second})
seen |= files()

# ── B3: what the list shows, and what it leaves out ───────────────────────────
for stray in ("notes.txt", "haluka-bad.db", "haluka-20260101-000000-manual.db.tmp", "haluka-20261301-000000-manual.db"):
    with open(os.path.join(config.backup_dir(), stray), "w") as f:
        f.write("x")
os.mkdir(os.path.join(config.backup_dir(), "old"))
older = os.path.basename(store.backup(path, config.backup_dir(), "before-closing-weeks", NOW - timedelta(days=400)))
newer = os.path.basename(store.backup(path, config.backup_dir(), "something-else", at(3)))
ls = bk.listing(conn, at(4), path)
t.ok("B3 only the site's own backups are listed (other files in the folder are left alone), by time, latest first",
     [b["name"] for b in ls["backups"]] == [newer, second, first, older] and "notes.txt" in files())
t.ok("B3 each reason is shown in words; a reason the screen does not know is shown as it is",
     [b["reason_text"] for b in ls["backups"]] == ["something-else", "גיבוי ביד", "גיבוי ביד", "לפני ששבוע שעבר נכנס להיסטוריה"])
seen |= {older, newer}

# ── B4: looking at a backup before restoring it ───────────────────────────────
with store.tx(conn):
    extra = person(50, "שבועי", phone1=SECRET_PHONE)
    cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in extra]
    conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [extra[c] for c in cols])
    conn.execute("UPDATE recipients SET status='מושהה' WHERE guid='g0026'")
    conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES ('h9','g0050',?, 'test')", (wk(-1).isoformat(),))
look = bk.inspect(conn, at(5), first, path)
t.ok("B4 the backup beside the site as it is now: one card fewer, one row of history fewer, one more active",
     look["backup"]["cards"] == N and look["now"]["cards"] == N + 1
     and look["backup"]["active"] == N and look["now"]["active"] == N        # one added, one paused
     and look["backup"]["history_rows"] == 4 and look["now"]["history_rows"] == 5
     and look["weeks_to_redo"] == 0 and look["taken_at"] == at(1).strftime("%Y-%m-%d %H:%M")
     and look["reason_text"] == "גיבוי ביד", str(look))
t.ok("B4 looking changes nothing: no file is added and the site holds what it held",
     files() >= seen and len(files() - seen) == 6 - 1 and one("SELECT COUNT(*) FROM recipients") == N + 1)
with store.tx(conn):
    conn.execute("DELETE FROM recipients WHERE guid='g0050'")
    conn.execute("DELETE FROM history WHERE guid='h9'")
    conn.execute("UPDATE recipients SET status='פעיל' WHERE guid='g0026'")

# ── B5: a restore brings back exactly what the backup held ────────────────────
service.set_manual(conn, at(6), W0, "g0026", "add", path)
ev = event_service.save(conn, at(6), {"date": wk(2).isoformat(), "holiday": "חנוכה", "portions": 3, "reserve": 1}, path)["guid"]
A = state()
name_a = bk.make(conn, at(7), path)["name"]
seen.add(name_a)
with store.tx(conn):
    extra = person(51, "שבועי", phone1=SECRET_PHONE)
    cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in extra]
    conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [extra[c] for c in cols])
    conn.execute("UPDATE recipients SET phone1='0509999999', status='מושהה' WHERE guid='g0001'")
    conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES ('h8','g0051',?, 'test')", (wk(-1).isoformat(),))
    conn.execute("DELETE FROM history WHERE guid='h0'")
settings_service.save_numbers(conn, at(8), {"portions": 9, "reserve": 3, "cooldown_weeks": 2}, path)
service.set_manual(conn, at(8), W0, "g0026", "clear", path)
event_service.save(conn, at(8), {"guid": ev, "date": wk(2).isoformat(), "holiday": "חנוכה", "portions": 8, "reserve": 0}, path)
B = state()
before = files()
done = bk.restore(conn, at(9), name_a, path)
t.ok("B5 after a restore the site holds exactly what the backup held: cards, history, settings, by hand, events",
     state() == A and A != B, str({k: (A[k], state()[k]) for k in A if A[k] != state()[k]}))
t.ok("B5 the answer says what was restored and where the state from before it was kept",
     done["ok"] is True and done["restored"] == name_a and done["backup"]["cards"] == N
     and done["safety"] == f"haluka-{at(9).strftime('%Y%m%d-%H%M%S')}-before-restore.db")
t.ok("B5 the state from before the restore was backed up first: one new file, and nothing was taken away",
     files() - before == {done["safety"]} and before <= files())
kept = bk.check(os.path.join(config.backup_dir(), done["safety"]))
t.ok("B5 ...and that file holds what the site held a moment before (the added card, the changed history)",
     kept["cards"] == N + 1 and kept["active"] == N and kept["history_rows"] == 4)
t.ok("B5 the lists of the coming weeks are computed from what came back",
     service.plan_overview(conn, at(9), 1, path)["defaults"]["portions"] == 6
     and "g0026" in service.plan_overview(conn, at(9), 1, path)["weeks"][0]["main"])
seen |= files()
undone = bk.restore(conn, at(10), done["safety"], path)
t.ok("B5 restoring that file takes the restore back: the site is again as it was before it",
     state() == B and undone["restored"] == done["safety"] and undone["safety"] != done["safety"])
seen |= files()
bk.restore(conn, at(11), name_a, path)
seen |= files()

# ── B6: what a restore refuses — and that a refusal touches nothing ───────────
folder = config.backup_dir()
real = os.path.join(folder, name_a)
outside = os.path.join(TMP, "haluka-20261125-100000-manual.db")
shutil.copy(real, outside)
os.makedirs(os.path.join(folder, "sub"), exist_ok=True)
shutil.copy(real, os.path.join(folder, "sub", "haluka-20261125-100000-manual.db"))
os.mkdir(os.path.join(folder, "haluka-20261125-100001-manual.db"))                  # a folder with a backup's name
base = files()
start = state()
wrong_names = ["haluka-20200101-000000-manual.db", "../haluka.db", "..", "", "haluka.db", outside,
               os.path.join("sub", "haluka-20261125-100000-manual.db"), "sub/haluka-20261125-100000-manual.db",
               "sub\\haluka-20261125-100000-manual.db", os.path.join("..", "..", "haluka-20261125-100000-manual.db"),
               name_a + "\x00", name_a + "/", " " + name_a, name_a.upper(), "haluka-20261125-100001-manual.db",
               None, 5, ["x"], "notes.txt"]
t.ok("B6 a name that is not a backup inside the backup folder is refused — a path, another folder, a made-up name",
     all("לא נמצא" in refusal(lambda n=n: bk.restore(conn, at(12), n, path)) for n in wrong_names)
     and all("לא נמצא" in refusal(lambda n=n: bk.inspect(conn, at(12), n, path)) for n in wrong_names),
     str([n for n in wrong_names if "לא נמצא" not in refusal(lambda n=n: bk.restore(conn, at(12), n, path))]))


def planted(name: str, build) -> str:
    """A file with a backup's name that `build` fills in."""
    dest = os.path.join(folder, name)
    build(dest)
    return name


def garbage(dest):
    with open(dest, "wb") as f:
        f.write(os.urandom(4096))


def cut_short(dest):
    with open(real, "rb") as src, open(dest, "wb") as f:
        f.write(src.read()[:5000])


def other_database(dest):
    c = sqlite3.connect(dest)
    c.execute("CREATE TABLE recipients (id INTEGER PRIMARY KEY, full_name TEXT)")
    c.execute("INSERT INTO recipients (full_name) VALUES ('בדיקה 9999')")
    c.commit()
    c.close()


def with_version(value):
    def build(dest):
        shutil.copy(real, dest)
        c = sqlite3.connect(dest)
        if value is None:
            c.execute("DELETE FROM meta WHERE key='schema_version'")
        else:
            c.execute("UPDATE meta SET value=? WHERE key='schema_version'", (value,))
        c.commit()
        c.close()
    return build


bad = {
    planted("haluka-20261125-110000-manual.db", garbage): "פגום",
    planted("haluka-20261125-110001-manual.db", cut_short): "פגום",
    planted("haluka-20261125-110002-manual.db", lambda d: open(d, "wb").close()): "אינו גיבוי של האתר",
    planted("haluka-20261125-110003-manual.db", other_database): "אינו גיבוי של האתר",
    planted("haluka-20261125-110004-manual.db", with_version(str(store.SCHEMA_VERSION + 1))): "גרסה אחרת",
    planted("haluka-20261125-110005-manual.db", with_version(None)): "גרסה אחרת",
    planted("haluka-20261125-110006-manual.db", with_version("abc")): "גרסה אחרת",
}
base = files()
answers = {n: refusal(lambda n=n: bk.restore(conn, at(13), n, path)) for n in bad}
t.ok("B6 a file that is damaged, cut short, empty, another database or of a newer version is refused, each in words",
     all(word in answers[n] for n, word in bad.items()), str(answers))
t.ok("B6 ...and looking at such a file is refused the same way",
     all(word in refusal(lambda n=n: bk.inspect(conn, at(13), n, path)) for n, word in bad.items()))
t.ok("B6 a refusal touches nothing: the site holds what it held, and not one file was added (no backup 'before restore')",
     state() == start and files() == base)
try:
    os.symlink(outside, os.path.join(folder, "haluka-20261125-120000-manual.db"))
    linked = refusal(lambda: bk.restore(conn, at(13), "haluka-20261125-120000-manual.db", path))
    os.remove(os.path.join(folder, "haluka-20261125-120000-manual.db"))
except (OSError, NotImplementedError):                       # no links on this computer: nothing to check
    linked = "לא נמצא"
t.ok("B6 a link that sits in the backup folder and points out of it is refused", "לא נמצא" in linked and state() == start)

_backup = store.backup
store.backup = lambda *a, **k: ""
t.ok("B6 when the state of this moment cannot be backed up, nothing is restored",
     "לא שחזרתי" in refusal(lambda: bk.restore(conn, at(14), name_a, path)) and state() == start)


def _broken_copy(db, folder_, reason, now=None):
    dest = os.path.join(folder_, f"haluka-{now.strftime('%Y%m%d-%H%M%S')}-{reason}.db")
    garbage(dest)
    return dest


store.backup = _broken_copy
t.ok("B6 ...and neither when that backup did not come out sound",
     "לא שחזרתי" in refusal(lambda: bk.restore(conn, at(15), name_a, path)) and state() == start)
store.backup = _backup
seen |= {n for n in files() if bk.NAME.match(n) and os.path.isfile(os.path.join(folder, n))}

# ── B7: a backup from before a later table / column existed ───────────────────
def as_older_version(dest):
    """The same backup, as an earlier version of the site would have written it: the
    events table without its two later columns, and no table of weeks 'by score'."""
    shutil.copy(real, dest)
    c = sqlite3.connect(dest)
    c.executescript("""
        CREATE TABLE e2 (guid TEXT PRIMARY KEY, event_date TEXT NOT NULL, holiday TEXT NOT NULL,
            portions INTEGER NOT NULL, reserve INTEGER NOT NULL DEFAULT 0, criteria TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT, main_count INTEGER, batch_guid TEXT);
        INSERT INTO e2 SELECT guid, event_date, holiday, portions, reserve, criteria, created_at, updated_at,
            closed_at, main_count, batch_guid FROM events;
        DROP TABLE events;
        ALTER TABLE e2 RENAME TO events;
        DROP TABLE week_modes;
    """)
    c.commit()
    c.close()


def before_stage_4(dest):
    as_older_version(dest)
    c = sqlite3.connect(dest)
    c.executescript("DROP TABLE events; DROP TABLE event_manual; DROP TABLE event_prints;")
    c.commit()
    c.close()


old_name = planted("haluka-20261125-130000-manual.db", as_older_version)
oldest_name = planted("haluka-20261125-130001-manual.db", before_stage_4)
look = bk.inspect(conn, at(16), old_name, path)
t.ok("B7 an older backup is counted too (its events table has fewer columns; a still older one has none)",
     look["backup"]["cards"] == N and look["backup"]["events_ahead"] == 1
     and bk.inspect(conn, at(16), oldest_name, path)["backup"]["events_ahead"] == 0, str(look["backup"]))
bk.restore(conn, at(17), old_name, path)
cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
t.ok("B7 after restoring it the site has every table and column it needs, and its screens work",
     {"deleted_at", "balance"} <= cols and one("SELECT COUNT(*) FROM week_modes") == 0
     and len(event_service.overview(conn, at(17), path)["open"]) == 1
     and len(service.plan_overview(conn, at(17), 2, path)["weeks"]) == 2 and state()["cards"] == A["cards"])
bk.restore(conn, at(18), oldest_name, path)
t.ok("B7 ...also from a backup that had no holiday events at all",
     event_service.overview(conn, at(18), path)["open"] == [] and state()["cards"] == A["cards"]
     and event_service.save(conn, at(18), {"date": wk(2).isoformat(), "holiday": "חנוכה", "portions": 3}, path)["ok"])
bk.restore(conn, at(19), name_a, path)
seen |= {n for n in files() if bk.NAME.match(n) and os.path.isfile(os.path.join(folder, n))}

# ── B8: the backup the site takes by itself, once on each day it is used ──────
day1 = at(600)                      # the evening: later than every file planted above
before = files()
got = bk.daily(conn, day1, path)
t.ok("B8 the first request of a day takes one backup, marked 'daily'",
     got == f"haluka-{day1.strftime('%Y%m%d-%H%M%S')}-daily.db" and files() - before == {got}
     and bk.listing(conn, day1, path)["auto_today"] is True
     and bk.listing(conn, day1, path)["backups"][0]["reason_text"] == "גיבוי יומי")
other = store.connect(path)
t.ok("B8 every later request of that day takes none — from this connection or from another",
     bk.daily(conn, at(601), path) == "" and bk.daily(other, at(700), path) == "" and files() - before == {got})
other.close()
day2 = day1 + timedelta(days=1)
got2 = bk.daily(conn, day2, path)
t.ok("B8 the next day's first request takes the next one; the earlier one stays",
     got2.endswith("-daily.db") and got2 != got and files() - before == {got, got2}
     and bk.listing(conn, day1 + timedelta(days=2), path)["auto_today"] is False)
seen |= {got, got2}
_dir = config.backup_dir
blocker = os.path.join(TMP, "a-file")
open(blocker, "w").close()
config.backup_dir = lambda: os.path.join(blocker, "backups")          # a place no folder can be made in
day3 = day1 + timedelta(days=2)
failed = bk.daily(conn, day3, path)
ls = bk.listing(conn, day3, path)
t.ok("B8 a backup that cannot be written does not stop the site: no error, the day stays unmarked, the screen is told",
     failed == "" and ls["auto_today"] is False and ls["backups"] == [])
with store.tx(conn):                                                   # the write lock was let go
    store.set_meta(conn, "probe", "1")
config.backup_dir = _dir
t.ok("B8 ...and the next request tries again (and succeeds once the folder is back)",
     bk.daily(conn, day3 + timedelta(minutes=1), path).endswith("-daily.db") and bk.listing(conn, day3, path)["auto_today"] is True)
seen |= files() - {"notes.txt"}
mark = store.get_meta(conn, bk.DAY_KEY)
name_b = bk.make(conn, day3 + timedelta(minutes=2), path)["name"]
bk.restore(conn, day3 + timedelta(minutes=3), name_a, path)           # name_a was taken days before day3
before = files()
t.ok("B8 after a restore the day is still marked: the restored state is not backed up again as 'this morning's'",
     store.get_meta(conn, bk.DAY_KEY) == mark and bk.daily(conn, day3 + timedelta(minutes=4), path) == "" and files() == before)
seen |= files() - {"notes.txt"}

# ── B9: an old backup, and the weeks that have passed since it was taken ──────
later = datetime(wk(3).year, wk(3).month, wk(3).day, 10, 0)            # three Wednesdays on
service.roll_forward(conn, later, path)
first_time = {tuple(r) for r in conn.execute("SELECT recipient_guid, dist_date FROM history WHERE dist_date >= ?", (W0.isoformat(),))}
look = bk.inspect(conn, later, name_a, path)
t.ok("B9 before restoring an old backup the screen is told how many weeks became history since it was taken",
     store.get_meta(conn, "closed_through") == wk(2).isoformat() and len(first_time) > 0
     and look["backup"]["last_week"] == wk(-1).isoformat() and look["now"]["last_week"] == wk(2).isoformat()
     and look["weeks_to_redo"] == 3, str(look))
bk.restore(conn, later, name_a, path)
t.ok("B9 the restore itself goes back to the backup's own history (those weeks are not in it)",
     store.get_meta(conn, "closed_through") == wk(-1).isoformat()
     and one("SELECT COUNT(*) FROM history WHERE dist_date >= ?", W0.isoformat()) == 0)
service.plan_overview(conn, later, 1, path)
again = {tuple(r) for r in conn.execute("SELECT recipient_guid, dist_date FROM history WHERE dist_date >= ?", (W0.isoformat(),))}
t.ok("B9 the next screen writes them again, computed from what the backup holds — the same lists as the first time",
     store.get_meta(conn, "closed_through") == wk(2).isoformat() and again == first_time)
t.ok("B9 a backup that is ahead of the site (its history reaches further) has no weeks to write again",
     bk.inspect(conn, later, name_a, path)["weeks_to_redo"] == 3
     and bk._weeks_between("2026-12-09", "2026-11-25") == 0 and bk._weeks_between("", "2026-11-25") == 0
     and bk._weeks_between("2026-11-25", "not a date") == 0)
seen |= {n for n in files() if bk.NAME.match(n) and os.path.isfile(os.path.join(folder, n))}

# ── B10: a database that is busy — the copy waits a little and then gives up, cleanly ──
store.COPY_SECONDS = 0.6
seen |= {n for n in files() if bk.NAME.match(n) and os.path.isfile(os.path.join(folder, n))}
other = store.connect(path)
reading = other.execute("SELECT guid FROM recipients")       # a read that is not finished: nobody can write the file
reading.fetchone()
start, base = state(), files()
t0 = time.monotonic()
said = refusal(lambda: bk.restore(conn, later + timedelta(minutes=2), name_a, path))
took = time.monotonic() - t0
t.ok("B10 while somebody else is in the middle of reading the site's database a restore gives up after a short wait, in words",
     "עסוק" in said and took < 8, f"{said!r} after {took:.1f}s")
t.ok("B10 ...and the site holds exactly what it held (the copy is all or nothing); the backup taken first stays",
     state() == start and base <= files() and all("before-restore" in n for n in files() - base))
reading.close()
other.close()
t.ok("B10 once the other reader is done the same restore goes through",
     start != A and bk.restore(conn, later + timedelta(minutes=3), name_a, path)["ok"] is True and state() == A)
other = store.connect(path)
other.execute("BEGIN EXCLUSIVE")                             # somebody else is in the middle of writing
base = files()
t0 = time.monotonic()
try:
    store.backup(path, folder, "manual", later + timedelta(minutes=4))
    raised = False
except sqlite3.OperationalError:
    raised = True
took = time.monotonic() - t0
t.ok("B10 a backup of a database that is locked gives up too — and leaves no half-written file behind",
     raised and took < 8 and files() == base, f"raised={raised} after {took:.1f}s, new files {sorted(files() - base)}")
t.ok("B10 ...'back up now' says that no backup was made, and a restore says that nothing was restored",
     "לא נוצר" in refusal(lambda: bk.make(conn, later + timedelta(minutes=4), path))
     and "לא שחזרתי" in refusal(lambda: bk.restore(conn, later + timedelta(minutes=4), name_a, path)) and files() == base)
other.execute("ROLLBACK")
other.close()
t.ok("B10 the site's own database, named as if it were a backup of itself, is refused (it would wait for itself)",
     "לא נמצא" in refusal(lambda: bk.restore(conn, later, "../haluka.db", path)) and state() == A)
store.COPY_SECONDS = 20

# ── B11: nothing private leaves, nothing is ever deleted, every reason has words ──
answers = json.dumps([bk.listing(conn, later, path), bk.inspect(conn, later, name_a, path),
                      bk.restore(conn, later + timedelta(minutes=1), name_a, path)], ensure_ascii=False)
t.ok("B11 the answers carry file names, times and numbers only — no name of a person and no phone",
     SECRET_PHONE not in answers and "בדיקה" not in answers)
seen |= {n for n in files() if bk.NAME.match(n) and os.path.isfile(os.path.join(folder, n))}
t.ok("B11 not one backup was ever deleted or written over: every file that existed during the run still exists",
     seen <= files() and len(seen) >= 15, str(sorted(seen - files())))
web_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
used = set()
for fname in os.listdir(web_dir):
    if fname.endswith(".py"):
        with open(os.path.join(web_dir, fname), encoding="utf-8") as f:
            # the reason is the last thing a call names before the time: backup(path, folder, "reason", now)
            used |= set(re.findall(r"""\.backup\([^\n]*["']([a-z][a-z-]+)["'],\s*now\)""", f.read()))
used |= {bk.MANUAL, bk.DAILY, bk.BEFORE_RESTORE}
t.ok("B11 every reason the site backs up for has words on the screen, and its file is one the list shows",
     len(used) >= 7 and used <= set(bk.REASONS) and all(bk.NAME.match(f"haluka-20261125-100000-{r}.db") for r in used)
     and all(bk.NAME.match(f"haluka-20261125-100000-{r}-2.db").group(3) == r for r in used), str(sorted(used - set(bk.REASONS))))

conn.close()
shutil.rmtree(TMP, ignore_errors=True)
t.done()
