# -*- coding: utf-8 -*-
"""The server kit: the backup that leaves the server, and the "is the server ready" check.

Run:  <python 3.12> web/tests/test_server.py      (invented people only)
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

from _util import Checker, W0, person

TMP = tempfile.mkdtemp(prefix="haluka_server_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")       # BEFORE the app is imported
for key in ("HALUKA_WEB_HOSTS", "HALUKA_WEB_LOGIN", "HALUKA_OFFSITE_DIR", "HALUKA_OFFSITE_CMD"):
    os.environ.pop(key, None)

from fastapi.testclient import TestClient  # noqa: E402

from web import app as webapp, auth, config, offsite, server_check, store  # noqa: E402

t = Checker("web server kit")
NOW = datetime(W0.year, W0.month, W0.day, 3, 10)
config.now = lambda: NOW
client = TestClient(webapp.app, base_url="http://127.0.0.1")
AWAY = os.path.join(TMP, "away")                 # stands for a drive that is not the server's
os.makedirs(AWAY)
SECRET_PHONE = "0501234567"


def levels():
    return {text: level for level, text in server_check.checks()}


def level_of(word):
    return [lv for text, lv in levels().items() if word in text]


# ── S1: this computer, nothing set ────────────────────────────────────────────
r = client.get("/api/offsite")
t.ok("S1 local, nothing set: the screen is told to show nothing", r.status_code == 200 and r.json()["show"] is False
     and r.json()["on"] is False and r.json()["late"] is False)
res = offsite.run(NOW)
t.ok("S1 with no destination nothing leaves, and it is a failure, not a silent success",
     res["failed"] and res["last_ok"] == "" and os.listdir(AWAY) == [])

# ── a small invented database ─────────────────────────────────────────────────
path = config.db_path()
store.create(path)
conn = store.connect(path)
with store.tx(conn):
    for n in range(1, 8):
        rec = person(n, "שבועי", phone1=SECRET_PHONE)
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in rec]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [rec[c] for c in cols])
conn.close()

# ── S2: to a folder ───────────────────────────────────────────────────────────
os.environ["HALUKA_OFFSITE_DIR"] = AWAY
res = offsite.run(NOW)
files = os.listdir(AWAY)
t.ok("S2 one whole copy arrived, with the day in its name", len(files) == 1 and files[0].startswith("haluka-20261125-0310")
     and files[0].endswith(".db") and not res["failed"] and res["days"] == 0 and not res["late"], str(files) + str(res))
c = sqlite3.connect(os.path.join(AWAY, files[0]))
t.ok("S2 the copy that left is a real database with all the cards",
     c.execute("SELECT COUNT(*) FROM recipients").fetchone()[0] == 7)
c.close()
t.ok("S2 nothing is left behind in the outbox, and no backup was added on the server",
     os.listdir(os.path.join(config.data_dir(), "outbox")) == [] and not os.path.exists(config.backup_dir()))
r = client.get("/api/offsite").json()
t.ok("S2 the screen is told: on, left today, not late", r == {"on": True, "show": True, "last_ok": "2026-11-25 03:10",
                                                           "days": 0, "late": False, "failed": False}, str(r))
t.ok("S2 the answer to the screen holds no path and no command", AWAY not in client.get("/api/offsite").text)
NOW = NOW + timedelta(days=1)
t.ok("S2 a day later: still fine", client.get("/api/offsite").json()["late"] is False)
NOW = NOW + timedelta(days=1)
t.ok("S2 two days with no copy: the screen is told it is late", client.get("/api/offsite").json()["late"] is True)
offsite.run(NOW)
t.ok("S2 the next copy is added beside the first (nothing is deleted there)", len(os.listdir(AWAY)) == 2
     and client.get("/api/offsite").json()["late"] is False)

# ── S3: when it cannot leave ──────────────────────────────────────────────────
os.environ["HALUKA_OFFSITE_DIR"] = os.path.join(TMP, "not-connected")
NOW = NOW + timedelta(days=1)
res = offsite.run(NOW)
t.ok("S3 the drive is not there: a failure, the last good day is kept, and no folder is invented",
     res["failed"] and res["last_ok"] == "2026-11-27 03:10" and not os.path.exists(os.path.join(TMP, "not-connected")))
os.environ["HALUKA_OFFSITE_DIR"] = os.path.join(config.data_dir(), "backups-away")
os.makedirs(os.environ["HALUKA_OFFSITE_DIR"])
res = offsite.run(NOW)
t.ok("S3 a 'destination' inside the site's own data folder is refused (it is not off the server)",
     res["failed"] and os.listdir(os.environ["HALUKA_OFFSITE_DIR"]) == [])
os.environ["HALUKA_OFFSITE_DIR"] = AWAY
import shutil  # noqa: E402
real_copy = shutil.copyfile


def damaged_copy(src, dst):
    real_copy(src, dst)
    with open(dst, "r+b") as f:
        f.seek(200)
        f.write(b"\x00damaged on the way\x00")


shutil.copyfile = damaged_copy
res = offsite.run(NOW)
shutil.copyfile = real_copy
t.ok("S3 a copy that arrived different from what was sent is a failure, and no half file stays there",
     res["failed"] and len(os.listdir(AWAY)) == 2, str(os.listdir(AWAY)))
real_backup = store.backup


def broken_backup(path, folder, reason, now=None):
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, "haluka-20261128-031000-offsite.db")
    with open(dest, "wb") as f:
        f.write(b"this is not a database")
    return dest


store.backup = broken_backup
res = offsite.run(NOW)
store.backup = real_backup
t.ok("S3 a copy that could not be restored is never sent", res["failed"] and len(os.listdir(AWAY)) == 2,
     str(os.listdir(AWAY)))

# ── S4: with a command ────────────────────────────────────────────────────────
os.environ.pop("HALUKA_OFFSITE_DIR")
BOX = os.path.join(TMP, "box with space")
os.makedirs(BOX)
mover = os.path.join(TMP, "mover.py")
with open(mover, "w", encoding="utf-8") as f:
    f.write("import shutil, sys\nif sys.argv[2] == 'fail':\n    sys.exit(3)\nshutil.copy(sys.argv[1], sys.argv[2])\n")
os.environ["HALUKA_OFFSITE_CMD"] = f'"{sys.executable}" "{mover}" {{file}} "{BOX}"'
res = offsite.run(NOW)
t.ok("S4 the command got the file and took it away", not res["failed"] and len(os.listdir(BOX)) == 1 and res["days"] == 0)
os.environ["HALUKA_OFFSITE_CMD"] = f'"{sys.executable}" "{mover}" {{file}} fail'
NOW = NOW + timedelta(days=1)
res = offsite.run(NOW)
t.ok("S4 a command that fails is a failure (the last good day stays)", res["failed"] and res["days"] == 1)
os.environ["HALUKA_OFFSITE_CMD"] = f'"{sys.executable}" "{mover}"'
t.ok("S4 a command that does not say where the file goes is refused", offsite.run(NOW)["failed"])
os.environ["HALUKA_OFFSITE_CMD"] = f'"{sys.executable}" "{mover}" {{file}} "{BOX}"; touch "{TMP}/shell-ran"'
offsite.run(NOW)
t.ok("S4 the command never goes through a shell", not os.path.exists(os.path.join(TMP, "shell-ran")))
t.ok("S4 the status file holds no phone", SECRET_PHONE not in open(offsite.status_path(), encoding="utf-8").read())
os.environ.pop("HALUKA_OFFSITE_CMD")

# ── S5: is the server ready ───────────────────────────────────────────────────
found = levels()
t.ok("S5 this computer as it is: 'the login is OFF' and 'nobody can enter' stop the opening",
     level_of("login is OFF") == ["FAIL"] and level_of("nobody can enter") == ["FAIL"], str(found))
os.environ["HALUKA_WEB_HOSTS"] = "haluka.example"
auth.set_user("בודק", "סיסמה-מומצאת-17")
os.chmod(config.data_dir(), 0o700)
found = levels()
t.ok("S5 a name for the site + a user + a closed folder: nothing stops the opening",
     "FAIL" not in found.values() and level_of("login is on") == ["OK"] and level_of("1 user(s)") == ["OK"], str(found))
t.ok("S5 ...but it warns that no backup leaves the server", level_of("no backup leaves") == ["WARN"])
os.chmod(config.data_dir(), 0o755)
t.ok("S5 a data folder that others on the server can read stops the opening", level_of("can read the data folder") == ["FAIL"])
os.chmod(config.data_dir(), 0o700)
os.chmod(auth.users_path(), 0o644)
t.ok("S5 a users file that others can read stops the opening", level_of("can read the users file") == ["FAIL"])
os.chmod(auth.users_path(), 0o600)
os.environ["HALUKA_OFFSITE_DIR"] = AWAY
NOW = NOW + timedelta(days=3)
t.ok("S5 a backup that did not leave on time is a warning", level_of("did not leave the server") == ["WARN"], str(levels()))
offsite.run(NOW)
t.ok("S5 after a copy left: all of it is OK", set(levels().values()) == {"OK"}, str(levels()))
text = " ".join(levels())
t.ok("S5 the check prints no name, no address and no folder", "בודק" not in text and "haluka.example" not in text
     and TMP not in text)
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "nowhere")
t.ok("S5 no data folder: stops the opening", level_of("missing or cannot be written") == ["FAIL"])

# ── S6: on the server the screen always speaks of it ──────────────────────────
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")
os.environ.pop("HALUKA_OFFSITE_DIR")
t.ok("S6 on the server with no destination: the screen is told to say so", offsite.status(NOW)["show"] is True
     and offsite.status(NOW)["on"] is False)
t.ok("S6 ...and a stranger gets nothing of it", TestClient(webapp.app, base_url="https://haluka.example")
     .get("/api/offsite").status_code in (400, 401))

t.done()
