# -*- coding: utf-8 -*-
"""The login of the server stage — through the real FastAPI app, on a throw-away folder.

Run:  <python 3.12> web/tests/test_auth.py
Every name and password here is invented.
"""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from _util import Checker, W0

TMP = tempfile.mkdtemp(prefix="haluka_auth_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")       # BEFORE the app is imported
os.environ.pop("HALUKA_WEB_HOSTS", None)
os.environ.pop("HALUKA_WEB_LOGIN", None)
for _k in ("HALUKA_WEB_URL", "HALUKA_GOOGLE_CLIENT_ID", "HALUKA_GOOGLE_CLIENT_SECRET"):
    os.environ.pop(_k, None)

from fastapi.testclient import TestClient  # noqa: E402

from web import app as webapp, auth, config, google_login  # noqa: E402

t = Checker("web login")
CLOCK = [datetime(W0.year, W0.month, W0.day, 20, 30)]
config.now = lambda: CLOCK[0]
H = {"X-Haluka": "1"}
STATIC = sorted(os.listdir(webapp.STATIC_DIR))


def browser():
    return TestClient(webapp.app, base_url="https://127.0.0.1", follow_redirects=False)


def enter(c, name, password):
    return c.post("/api/login", json={"name": name, "password": password}, headers=H)


# ── L1: when is the login on ──────────────────────────────────────────────────
t.ok("L1 this computer only: no login", not config.login_required())
os.environ["HALUKA_WEB_HOSTS"] = "127.0.0.1,haluka.example"
t.ok("L1 a site that answers to an outside name ALWAYS asks for a login", config.login_required())
os.environ["HALUKA_WEB_LOGIN"] = "0"
t.ok("L1 ...and no setting can switch that off", config.login_required())
os.environ.pop("HALUKA_WEB_HOSTS")
os.environ.pop("HALUKA_WEB_LOGIN")

# ── L2: this computer stays exactly as it was ─────────────────────────────────
c = browser()
t.ok("L2 local: the page opens with no login", c.get("/").status_code == 200)
t.ok("L2 local: the routes answer with no login (503 = no data yet, not 401)", c.get("/api/plan").status_code == 503)
t.ok("L2 local: /api/me says there is no login", c.get("/api/me").json() == {"login": False, "name": ""})
r = c.get("/login")
t.ok("L2 local: there is no login page (it leads to the site)", r.status_code == 303 and r.headers["location"] == "/")
t.ok("L2 local: no cookie is ever set", enter(c, "x", "y").json() == {"ok": True, "login": False}
     and "set-cookie" not in enter(c, "x", "y").headers)
t.ok("L2 local: nothing was written for the login", not os.path.exists(auth.auth_db_path()))

# ── L3: passwords are kept only as a hash ─────────────────────────────────────
PW_Y, PW_R = "סיסמה-מומצאת-17", "another-Invented-9"
auth.set_user("בודק א", PW_Y)
auth.set_user("Bodek B", PW_R)
raw = open(auth.users_path(), encoding="utf-8").read()
t.ok("L3 the users file holds no password", PW_Y not in raw and PW_R not in raw and "scrypt$" in raw)
h1, h2 = auth.hash_password(PW_Y), auth.hash_password(PW_Y)
t.ok("L3 the same password twice gives two different hashes (salt)", h1 != h2)
t.ok("L3 the right password fits its hash, a near one does not",
     auth.verify_password(PW_Y, h1) and not auth.verify_password(PW_Y + " ", h1) and not auth.verify_password("", h1))
t.ok("L3 a damaged hash fits nothing", not auth.verify_password(PW_Y, "scrypt$x") and not auth.verify_password(PW_Y, ""))
for bad in ("short", "x" * 300):
    try:
        auth.set_user("מישהו", bad)
        refused = False
    except ValueError:
        refused = True
    t.ok(f"L3 a password of {len(bad)} characters is refused", refused and "מישהו" not in auth.users())

# ── L4: with the login on, nothing answers to a stranger ─────────────────────
os.environ["HALUKA_WEB_LOGIN"] = "1"
c = browser()
routes = sorted({(m, r.path) for r in webapp.app.routes if getattr(r, "methods", None) for m in r.methods
                 if m in ("GET", "POST")})
t.ok("L4 the test sees the whole site (routes of every stage)", len(routes) >= 50, str(len(routes)))
leaks = []
for method, path in routes:
    if path in webapp.OPEN_PATHS:
        continue
    r = c.get(path) if method == "GET" else c.post(path, json={}, headers=H)
    wanted = (401,) if path.startswith("/api/") or method == "POST" else (303,)
    if r.status_code not in wanted or (r.status_code == 303 and r.headers["location"] != "/login"):
        leaks.append((method, path, r.status_code))
t.ok("L4 every route and every page refuses a stranger (routes: 401, pages: to the login page)", not leaks, str(leaks))
leaks = [name for name in STATIC if "/static/" + name not in webapp.OPEN_PATHS
         and c.get("/static/" + name).status_code != 401]
t.ok("L4 every static file but the login page's own two refuses a stranger", not leaks and len(STATIC) > 10, str(leaks))
t.ok("L4 what is open: the login page, its script and style, and the alive check — and nothing else",
     webapp.OPEN_PATHS == {"/login", "/api/login", "/healthz", "/static/style.css", "/static/login.js",
                           "/auth/google", "/auth/google/callback", "/auth/drive/callback"}
     and all(c.get(p).status_code == 200 for p in webapp.OPEN_PATHS if p != "/api/login" and "/auth/" not in p))
t.ok("L4 with no Google settings the Google way in does not exist, and the page offers the password only",
     c.get("/auth/google").status_code == 404 and 'data-ways="password"' in c.get("/login").text)
r = c.get("/login")
t.ok("L4 the login page asks for a name and a password and loads only its own script",
     'id="loginName"' in r.text and 'type="password"' in r.text and "/static/login.js" in r.text
     and "common.js" not in r.text and 'dir="rtl"' in r.text)
t.ok("L4 the alive check says nothing but 'alive'", c.get("/healthz").json() == {"ok": True})
t.ok("L4 a made-up cookie opens nothing",
     TestClient(webapp.app, base_url="https://127.0.0.1", cookies={auth.COOKIE: "A" * 43}).get("/api/me").status_code == 401)
t.ok("L4 answers on the server tell the browser to use https only",
     "max-age" in c.get("/healthz").headers.get("strict-transport-security", ""))

# ── L5: entering ──────────────────────────────────────────────────────────────
r = c.post("/api/login", json={"name": "בודק א", "password": PW_Y})
t.ok("L5 a login that does not come from the site's own page is refused (X-Haluka)", r.status_code == 403)
r1, r2 = enter(c, "בודק א", "לא-הסיסמה"), enter(c, "אין כזה", "לא-הסיסמה")
t.ok("L5 a wrong password and an unknown name get the same answer",
     r1.status_code == r2.status_code == 401 and r1.json() == r2.json() and "set-cookie" not in r1.headers)
t.ok("L5 the other user's password does not open this one", enter(c, "בודק א", PW_R).status_code == 401)
r = enter(c, "  בודק   א ", PW_Y)
cookie = r.headers.get("set-cookie", "")
token = c.cookies.get(auth.COOKIE)
t.ok("L5 the right password enters (spaces around the name do not matter)",
     r.status_code == 200 and r.json()["name"] == "בודק א" and bool(token))
low = cookie.lower()
t.ok("L5 the cookie: https only, hidden from scripts, never sent from another site, this host only",
     cookie.startswith("__Host-haluka=") and "secure" in low and "httponly" in low and "samesite=strict" in low
     and "path=/" in low and "domain" not in low, cookie)
t.ok("L5 inside: pages, routes and files answer", c.get("/").status_code == 200 and c.get("/api/plan").status_code == 503
     and c.get("/static/common.js").status_code == 200 and c.get("/api/me").json() == {"login": True, "name": "בודק א"})
t.ok("L5 inside: the login page leads to the site", c.get("/login").status_code == 303)
t.ok("L5 inside: a write without the site's header is still refused", c.post("/api/backup/make", json={}).status_code == 403)
blob = open(auth.auth_db_path(), "rb").read()
t.ok("L5 the server keeps only a hash of the session, never the session itself",
     token.encode() not in blob and auth._token_hash(token).encode() in blob)
t.ok("L5 the name is not case- or space-sensitive", enter(browser(), "bodek  b", PW_R).status_code == 200)

# ── L6: leaving ───────────────────────────────────────────────────────────────
r = c.post("/api/logout", json={}, headers=H)
t.ok("L6 leaving clears the cookie", r.status_code == 200 and "__Host-haluka=" in r.headers.get("set-cookie", "")
     and c.get("/api/me").status_code == 401)
thief = TestClient(webapp.app, base_url="https://127.0.0.1", cookies={auth.COOKIE: token})
t.ok("L6 ...and the session is dead on the server too (a copied cookie no longer works)",
     thief.get("/api/me").status_code == 401)

# ── L7: a session ends 30 days after it was last used ─────────────────────────
c = browser()
enter(c, "בודק א", PW_Y)
start = CLOCK[0]
CLOCK[0] = start + timedelta(days=20)
t.ok("L7 20 days later: still inside", c.get("/api/me").status_code == 200)
CLOCK[0] = start + timedelta(days=45)
t.ok("L7 used on day 20, so on day 45 it is still alive (25 days since last use)", c.get("/api/me").status_code == 200)
CLOCK[0] = start + timedelta(days=45 + 30, minutes=1)
t.ok("L7 30 days with no use: the session is over", c.get("/api/me").status_code == 401)
t.ok("L7 ...and stays over when the clock goes back", (CLOCK.__setitem__(0, start) or c.get("/api/me").status_code) == 401)

# ── L8: a new password, a removed user ────────────────────────────────────────
c = browser()
enter(c, "בודק א", PW_Y)
auth.set_user("בודק א", "סיסמה-חדשה-לגמרי")
t.ok("L8 a new password ends the sessions of the old one", c.get("/api/me").status_code == 401)
t.ok("L8 the old password no longer enters, the new one does",
     enter(c, "בודק א", PW_Y).status_code == 401 and enter(c, "בודק א", "סיסמה-חדשה-לגמרי").status_code == 200)
c2 = browser()
enter(c2, "Bodek B", PW_R)
conn = sqlite3.connect(auth.auth_db_path())
alive = conn.execute("SELECT COUNT(*) FROM sessions WHERE user = 'bodek b'").fetchone()[0]
conn.close()
found = auth.users()
found.pop("bodek b")
auth._write_users(found)                       # the user disappears from the file; his session row is still there
t.ok("L8 a user who was taken out of the file is out at once, even with a live session",
     alive >= 1 and c2.get("/api/me").status_code == 401)
auth.set_user("Bodek B", PW_R)
t.ok("L8 remove_user: gone, and cannot enter", auth.remove_user("bodek b") and "bodek b" not in auth.users()
     and enter(browser(), "Bodek B", PW_R).status_code == 401 and not auth.remove_user("bodek b"))
auth.set_user("Bodek B", PW_R)

# ── L9: too many wrong passwords ──────────────────────────────────────────────
CLOCK[0] = start + timedelta(days=100)
c = browser()
codes = [enter(c, "Bodek B", "wrong-%d" % i).status_code for i in range(auth.MAX_FAILS)]
t.ok("L9 the first wrong tries are simply wrong", codes == [401] * auth.MAX_FAILS, str(codes))
r = enter(c, "Bodek B", PW_R)
t.ok("L9 after them the name is locked, even for the right password, and the answer says for how long",
     r.status_code == 429 and str(auth.LOCK_MINUTES) in r.json()["message"] and "set-cookie" not in r.headers, r.text)
t.ok("L9 the other user is not locked", enter(browser(), "בודק א", "סיסמה-חדשה-לגמרי").status_code == 200)
CLOCK[0] += timedelta(minutes=auth.LOCK_MINUTES - 1)
t.ok("L9 a minute before the end: still locked", enter(c, "Bodek B", PW_R).status_code == 429)
CLOCK[0] += timedelta(minutes=2)
t.ok("L9 after the lock: the right password enters", enter(c, "Bodek B", PW_R).status_code == 200)
codes = [enter(browser(), "Bodek B", "wrong")
         .status_code for _ in range(auth.MAX_FAILS - 1)] + [enter(browser(), "Bodek B", PW_R).status_code]
t.ok("L9 entering wipes the earlier wrong tries (4 wrong, 1 right, then 4 wrong again is not a lock)",
     codes[-1] == 200 and [enter(browser(), "Bodek B", "wrong").status_code for _ in range(auth.MAX_FAILS - 1)]
     == [401] * (auth.MAX_FAILS - 1) and enter(browser(), "Bodek B", PW_R).status_code == 200)
codes = [enter(c, "שם שלא קיים", "x").status_code for _ in range(auth.MAX_FAILS + 1)]
t.ok("L9 a name that does not exist is locked the same way (it tells a guesser nothing)", codes[-1] == 429 and codes[0] == 401)

# ── G: entering with a Google account ─────────────────────────────────────────
import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

auth.set_user("בודק א", "סיסמה-חדשה-לגמרי")
os.environ["HALUKA_GOOGLE_CLIENT_ID"] = "client-invented.apps.example"
os.environ["HALUKA_GOOGLE_CLIENT_SECRET"] = "secret-invented"
os.environ["HALUKA_WEB_URL"] = "http://haluka.example"
t.ok("G1 an address that is not https switches the Google way off", not google_login.enabled()
     and browser().get("/auth/google").status_code == 404)
os.environ["HALUKA_WEB_URL"] = "https://haluka.example/"
auth.allow_google("Bodek.G@Example.com", "בודק גוגל")
raw = open(auth.users_path(), encoding="utf-8").read()
t.ok("G1 allowing a Google account keeps the password users, and stores the address in lower case",
     "bodek.g@example.com" in raw and "בודק א" in auth.users()["בודק א"]["name"] and len(auth.google_allowed()) == 1)
t.ok("G1 the login page now offers both ways", 'data-ways="google password"' in browser().get("/login").text)
SENT = {}


def fake_google(claims):
    def fetch(code, cfg):
        SENT.update(code=code, redirect=cfg["redirect"])
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return {"id_token": "h." + body + ".s"}
    google_login.fetch_token = fetch


def visit(email="bodek.g@example.com", change=None, state=None, keep_cookie=True):
    """A whole visit: to Google and back. Returns (browser, the answer of the way back)."""
    b = browser()
    r = b.get("/auth/google")
    q = parse_qs(urlparse(r.headers["location"]).query)
    claims = {"iss": "https://accounts.google.com", "aud": "client-invented.apps.example", "email": email,
              "email_verified": True, "nonce": q["nonce"][0], "exp": time.time() + 300}
    claims.update(change or {})
    fake_google(claims)
    if not keep_cookie:
        b.cookies.clear()
    return b, b.get("/auth/google/callback", params={"code": "code-1", "state": state or q["state"][0]}), r, q


real_fetch = google_login.fetch_token
b, back, went, q = visit()
loc = urlparse(went.headers["location"])
low = went.headers["set-cookie"].lower()
t.ok("G2 the way to Google: Google's own address, asking only who it is, with the site's own return address",
     went.status_code == 303 and loc.netloc == "accounts.google.com" and q["scope"] == ["openid email"]
     and q["redirect_uri"] == ["https://haluka.example/auth/google/callback"] and q["response_type"] == ["code"]
     and "secret-invented" not in went.headers["location"], went.headers["location"])
t.ok("G2 the state waits in a cookie that scripts cannot read, https only, for ten minutes",
     "__host-haluka-g=" in low and "httponly" in low and "secure" in low and "max-age=600" in low)
t.ok("G2 an allowed account enters: a session cookie (strict), and a page that moves into the site",
     back.status_code == 200 and 'url=/"' in back.text and "samesite=strict" in back.headers["set-cookie"].lower()
     and b.get("/api/me").json() == {"login": True, "name": "בודק גוגל"} and SENT["code"] == "code-1"
     and SENT["redirect"] == "https://haluka.example/auth/google/callback", back.text)
t.ok("G2 the capital letters of the address at Google do not matter", visit("Bodek.G@EXAMPLE.com")[0].get("/api/me").status_code == 200)


def refused(why, **kw):
    b2, back2, _, _ = visit(**kw)
    return (back2.status_code == 303 and back2.headers["location"] == "/login#" + why
            and b2.get("/api/me").status_code == 401 and "__Host-haluka=" not in back2.headers.get("set-cookie", ""))


t.ok("G3 an account that was not allowed does not enter", refused("not_allowed", email="stranger@example.com"))
t.ok("G3 an address Google did not verify does not enter", refused("not_allowed", change={"email_verified": False}))
t.ok("G3 a way back with a different state is refused (it is not the visit this browser started)",
     refused("again", state="made-up-state"))
t.ok("G3 a way back to a browser that never left for Google is refused", refused("again", keep_cookie=False))
t.ok("G3 an answer meant for another site is refused", refused("again", change={"aud": "someone-else.apps.example"}))
t.ok("G3 an answer that is not from Google is refused", refused("again", change={"iss": "https://evil.example"}))
t.ok("G3 an answer to another visit (nonce) is refused", refused("again", change={"nonce": "other"}))
t.ok("G3 an answer that expired is refused", refused("again", change={"exp": time.time() - 5}))
google_login.fetch_token = lambda code, cfg: (_ for _ in ()).throw(OSError("google is down"))
b3 = browser()
q3 = parse_qs(urlparse(b3.get("/auth/google").headers["location"]).query)
r3 = b3.get("/auth/google/callback", params={"code": "c", "state": q3["state"][0]})
t.ok("G3 Google does not answer: back to the login page, nobody enters", r3.headers.get("location") == "/login#again")
auth.allow_google("second@example.com", "בודק שני")
b5 = visit("second@example.com")[0]
inside = b5.get("/api/me").status_code
auth._write_users(auth.users(), {k: v for k, v in auth.google_allowed().items() if k != "second@example.com"})
t.ok("G4 an account that disappears from the file is out at once, even with a live session",
     inside == 200 and b5.get("/api/me").status_code == 401)
t.ok("G4 taking the account off the list signs it out at once, and it cannot come back",
     auth.disallow_google("BODEK.G@example.com") and b.get("/api/me").status_code == 401
     and refused("not_allowed") and not auth.disallow_google("bodek.g@example.com"))
for bad in (("not-an-address", "שם"), ("a@b.c", "")):
    try:
        auth.allow_google(*bad)
        ok = False
    except ValueError:
        ok = True
    t.ok(f"G4 allowing {bad!r} is refused", ok and not auth.google_allowed())
google_login.fetch_token = real_fetch
for _k in ("HALUKA_WEB_URL", "HALUKA_GOOGLE_CLIENT_ID", "HALUKA_GOOGLE_CLIENT_SECRET"):
    os.environ.pop(_k)

# ── L10: nobody was set up yet ────────────────────────────────────────────────
os.remove(auth.users_path())
t.ok("L10 with no users at all nobody enters (the site is closed, not open)",
     enter(browser(), "בודק א", "סיסמה-חדשה-לגמרי").status_code == 401 and browser().get("/api/plan").status_code == 401)

t.done()
