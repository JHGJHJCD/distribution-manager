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
for key in ("HALUKA_WEB_HOSTS", "HALUKA_WEB_LOGIN", "HALUKA_OFFSITE_DIR", "HALUKA_OFFSITE_CMD", "HALUKA_WEB_URL",
            "HALUKA_GOOGLE_CLIENT_ID", "HALUKA_GOOGLE_CLIENT_SECRET"):
    os.environ.pop(key, None)

from fastapi.testclient import TestClient  # noqa: E402

from web import app as webapp, auth, config, drive, google_login, offsite, server_check, store  # noqa: E402

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

# ── D: Google Drive, encrypted ────────────────────────────────────────────────
import hashlib  # noqa: E402
import json  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

os.environ.pop("HALUKA_OFFSITE_DIR")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")
os.environ.pop("HALUKA_WEB_HOSTS")
os.environ["HALUKA_WEB_LOGIN"] = "1"
H = {"X-Haluka": "1"}
site = TestClient(webapp.app, base_url="https://127.0.0.1", follow_redirects=False)
site.post("/api/login", json={"name": "בודק", "password": "סיסמה-מומצאת-17"}, headers=H)
t.ok("D1 with no Google settings the screen is told there is no Drive to connect",
     site.get("/api/drive").json() == {"available": False, "connected": False, "since": "", "key": ""}
     and site.get("/auth/drive").status_code == 404)
os.environ.update(HALUKA_WEB_URL="https://haluka.example", HALUKA_GOOGLE_CLIENT_ID="client-invented",
                  HALUKA_GOOGLE_CLIENT_SECRET="secret-invented")
stranger = TestClient(webapp.app, base_url="https://127.0.0.1", follow_redirects=False)
t.ok("D1 a stranger cannot start a connection, nor see or change anything of it",
     stranger.get("/auth/drive").status_code == 303 and stranger.get("/auth/drive").headers["location"] == "/login"
     and stranger.get("/api/drive").status_code == 401
     and stranger.post("/api/drive/disconnect", json={}, headers=H).status_code == 401)
went = site.get("/auth/drive")
q = parse_qs(urlparse(went.headers["location"]).query)
t.ok("D1 the way to Google asks for the narrowest permission (only files the site itself puts there), for the long run",
     q["scope"] == ["https://www.googleapis.com/auth/drive.file"] and q["access_type"] == ["offline"]
     and q["redirect_uri"] == ["https://haluka.example/auth/drive/callback"])


class FakeGoogle:
    """Google's token service and Drive, as much of them as the site uses."""
    def __init__(self):
        self.files, self.folders, self.calls, self.grant, self.damage = {}, {}, [], dict(
            refresh_token="refresh-invented", scope="https://www.googleapis.com/auth/drive.file"), False

    def token(self, code, cfg):
        self.calls.append(("code", code, cfg["redirect"]))
        return dict(self.grant)

    def http(self, method, url, headers, body=None):
        self.calls.append((method, url.split("?")[0]))
        if url == google_login.TOKEN_URL:
            ok = b"refresh_token=refresh-invented" in body and b"client_secret=secret-invented" in body
            return (200, b'{"access_token": "access-1"}') if ok else (400, b"{}")
        if headers.get("Authorization") != "Bearer access-1":
            return 401, b"{}"
        if url.startswith(drive.API):
            meta = json.loads(body.decode("utf-8"))
            self.folders["folder-%d" % (len(self.folders) + 1)] = meta
            return 200, json.dumps({"id": "folder-%d" % len(self.folders)}).encode()
        edge = headers["Content-Type"].split("boundary=")[1].encode()
        parts = body.split(b"--" + edge)
        meta = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].decode("utf-8"))
        content = parts[2].split(b"\r\n\r\n", 1)[1][:-2]
        if self.damage:
            content = content[:-9]
        self.files[meta["name"]] = (meta, content)
        return 200, json.dumps({"id": "f", "size": str(len(content)), "md5Checksum": hashlib.md5(content).hexdigest()}).encode()


g = FakeGoogle()
google_login.fetch_token, drive._http = g.token, g.http
r = stranger.get("/auth/drive/callback", params={"code": "c", "state": q["state"][0]})
t.ok("D2 the way back without the cookie of the visit connects nothing", "drive-again" in r.text and not drive.connected())
r = site.get("/auth/drive/callback", params={"code": "c", "state": "made-up"})
t.ok("D2 the way back with another state connects nothing", "drive-again" in r.text and not drive.connected())
g.grant["scope"] = "openid"
went = site.get("/auth/drive")
q = parse_qs(urlparse(went.headers["location"]).query)
r = site.get("/auth/drive/callback", params={"code": "c", "state": q["state"][0]})
t.ok("D2 Google without the permission to save files: not connected, and the screen is told why",
     "drive-no_permission" in r.text and not drive.connected())
g.grant["scope"] = "https://www.googleapis.com/auth/drive.file"
q = parse_qs(urlparse(site.get("/auth/drive").headers["location"]).query)
r = site.get("/auth/drive/callback", params={"code": "code-7", "state": q["state"][0]})
v = site.get("/api/drive").json()
KEY = v["key"]
t.ok("D2 connected: back to the settings screen, and the recovery key is shown",
     "url=/settings#drive-ok" in r.text and v["connected"] and v["available"] and len(KEY) == 44
     and ("code", "code-7", "https://haluka.example/auth/drive/callback") in g.calls, str(v))
t.ok("D2 the answers about the Drive hold no token and no secret",
     "refresh-invented" not in site.get("/api/drive").text and "secret-invented" not in site.get("/api/drive").text)
t.ok("D2 now the daily copy goes to the Drive (nothing else was set)", offsite.target() == ("drive", ""))

res = offsite.run(NOW)
name, (meta, sealed) = next(iter(g.files.items()))
t.ok("D3 the copy arrived, in the site's own folder, under its day's name", not res["failed"] and res["days"] == 0
     and len(g.files) == 1 and name.startswith("haluka-") and name.endswith(".db.enc")
     and meta["parents"] == ["folder-1"] and g.folders["folder-1"]["name"] == drive.FOLDER_NAME, str(res))
t.ok("D3 what is on the Drive is unreadable: no database header, no phone",
     b"SQLite format" not in sealed and SECRET_PHONE.encode() not in sealed)
plain = drive.decrypt(sealed, KEY)
out = os.path.join(TMP, "opened.db")
with open(out, "wb") as f:
    f.write(plain)
c = sqlite3.connect(out)
t.ok("D3 with the key it opens to the whole database", plain.startswith(b"SQLite format 3")
     and c.execute("SELECT COUNT(*) FROM recipients").fetchone()[0] == 7)
c.close()
try:
    drive.decrypt(sealed, "A" * 43 + "=")
    opened = True
except Exception:
    opened = False
t.ok("D3 with another key it does not open", not opened)
offsite.run(NOW)
t.ok("D3 the next copy goes to the same folder (one folder, nothing replaced)", len(g.folders) == 1 and len(g.files) >= 1)
g.damage = True
before = len(g.files)
NOW = NOW + timedelta(days=1)
res = offsite.run(NOW)
g.damage = False
t.ok("D3 a copy that arrived damaged at the Drive is a failure, not a success", res["failed"] and res["days"] == 1)

t.ok("D4 the key is shown until the owner says he kept it, and never again",
     site.get("/api/drive").json()["key"] == KEY
     and site.post("/api/drive/key-kept", json={}, headers=H).json()["key"] == ""
     and site.get("/api/drive").json()["key"] == "" and site.get("/api/drive").json()["connected"])
r = site.post("/api/drive/disconnect", json={}, headers=H).json()
t.ok("D4 disconnecting stops the sending, and keeps the key for the copies already there",
     r["connected"] is False and offsite.target() == ("", "") and drive._read().get("key") == KEY and offsite.run(NOW)["failed"])
q = parse_qs(urlparse(site.get("/auth/drive").headers["location"]).query)
site.get("/auth/drive/callback", params={"code": "c2", "state": q["state"][0]})
t.ok("D4 connecting again keeps the same key (the old copies stay openable) and does not show it again",
     drive.connected() and drive._read().get("key") == KEY and site.get("/api/drive").json()["key"] == "")
g.grant["refresh_token"] = "revoked"
q = parse_qs(urlparse(site.get("/auth/drive").headers["location"]).query)
site.get("/auth/drive/callback", params={"code": "c3", "state": q["state"][0]})
res = offsite.run(NOW)
t.ok("D4 a connection that Google no longer accepts is a failure the screen will show", res["failed"])
os.environ["HALUKA_OFFSITE_DIR"] = AWAY
t.ok("D4 a destination set on the server itself comes before the Drive", offsite.target()[0] == "dir")
os.environ.pop("HALUKA_OFFSITE_DIR")
for key in ("HALUKA_WEB_URL", "HALUKA_GOOGLE_CLIENT_ID", "HALUKA_GOOGLE_CLIENT_SECRET", "HALUKA_WEB_LOGIN"):
    os.environ.pop(key)
os.remove(drive.state_path())
os.environ["HALUKA_WEB_HOSTS"] = "haluka.example"

# ── S6: on the server the screen always speaks of it ──────────────────────────
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")
os.environ.pop("HALUKA_OFFSITE_DIR", None)
t.ok("S6 on the server with no destination: the screen is told to say so", offsite.status(NOW)["show"] is True
     and offsite.status(NOW)["on"] is False)
t.ok("S6 ...and a stranger gets nothing of it", TestClient(webapp.app, base_url="https://haluka.example")
     .get("/api/offsite").status_code in (400, 401))

t.done()
