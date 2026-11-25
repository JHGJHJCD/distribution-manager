# -*- coding: utf-8 -*-
"""The website's routes — through the real FastAPI app, on a throw-away database.

Run:  <python 3.12> web/tests/test_api.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

from _util import Checker, W0, person, wk

TMP = tempfile.mkdtemp(prefix="haluka_api_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")       # BEFORE the app is imported
os.environ.pop("HALUKA_WEB_HOSTS", None)

from fastapi.testclient import TestClient  # noqa: E402

from web import app as webapp, config, store  # noqa: E402

t = Checker("web api")
config.now = lambda: datetime(W0.year, W0.month, W0.day, 20, 30)          # Wednesday evening
client = TestClient(webapp.app, base_url="http://127.0.0.1")

# ── A1: before any data exists ────────────────────────────────────────────────
r = client.get("/api/plan")
t.ok("A1 no database yet: a clear message, not a crash", r.status_code == 503 and "ייבא" in r.json()["message"])
r = client.get("/")
t.ok("A1 the page itself is served", r.status_code == 200 and "מנהל חלוקה" in r.text and 'dir="rtl"' in r.text)

# ── a small invented database ─────────────────────────────────────────────────
SECRET_PHONE, SECRET_ID, SECRET_NOTE = "0501234567", "123456782", "הערה-פרטית-מאוד"
recs = ([person(n, f, phone1=SECRET_PHONE, id_number=SECRET_ID, notes=SECRET_NOTE, address="רחוב סודי 7")
         for n, f in enumerate(["שבועי", "שבועי", "דו-שבועי", "חודשי"], 1)]
        + [person(n, "חד-פעמי", 3 if n % 2 else 2, phone1=SECRET_PHONE) for n in range(21, 31)]
        + [person(40, "", 1), person(41, "שבועי", status="מושהה")])
path = config.db_path()
store.create(path)
conn = store.connect(path)
with store.tx(conn):
    for rec in recs:
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in rec]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [rec[c] for c in cols])
    conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES ('h1','g0003',?, 'test')",
                 (wk(-1).isoformat(),))
    store.set_setting(conn, "default_portions", 6)
    store.set_setting(conn, "default_reserve", 2)
    store.set_meta(conn, "closed_through", wk(-1).isoformat())
conn.close()

# ── A2: the three answers ─────────────────────────────────────────────────────
r = client.get("/api/plan?weeks=3")
plan = r.json()
t.ok("A2 /api/plan: the coming weeks from the current Wednesday",
     r.status_code == 200 and plan["current_week"] == W0.isoformat() and len(plan["weeks"]) == 3
     and [w["date"] for w in plan["weeks"]] == [wk(i).isoformat() for i in range(3)])
w0 = plan["weeks"][0]
t.ok("A2 week one: 3 regulars in turn (the bi-weekly of last week waits) + 3 one-timers = 6 portions, 2 in reserve",
     w0["regulars_due"] == 3 and w0["main_regulars"] == 3 and w0["main_one_timers"] == 3
     and len(w0["main"]) == 6 and len(w0["reserve_list"]) == 2, str(w0))
r = client.get("/api/week", params={"date": W0.isoformat()})
detail = r.json()
t.ok("A2 /api/week: the same people, each with a reason",
     r.status_code == 200 and [e["guid"] for e in detail["main"]] == w0["main"]
     and all(e["why"] for e in detail["main"] + detail["reserve_list"] + detail["out"]))
t.ok("A2 the bi-weekly who received last week is in 'not this week' with his next turn",
     any(e["guid"] == "g0003" and e["group"] == "reg_wait" and wk(1).strftime("%d/%m") in e["why"] for e in detail["out"]))
r = client.get("/api/week", params={"date": wk(2).isoformat()})
t.ok("A2 a later week agrees with the overview", r.status_code == 200
     and [e["guid"] for e in r.json()["main"]] == plan["weeks"][2]["main"])
ppl = client.get("/api/people").json()
t.ok("A2 /api/people: 14 take part, 2 do not (no frequency / paused)",
     len(ppl["participants"]) == 14 and {p["guid"] for p in ppl["others"]} == {"g0040", "g0041"})

# ── A3: wrong questions get a clean refusal ───────────────────────────────────
t.ok("A3 weeks=0 / a huge number / not a number are refused",
     [client.get(f"/api/plan?weeks={v}").status_code for v in ("0", str(config.MAX_WEEKS + 1), "abc")] == [422, 422, 422])
t.ok("A3 the largest allowed request works", client.get(f"/api/plan?weeks=120").status_code == 200)
t.ok("A3 a date that is not a date", client.get("/api/week?date=2026-13-45").status_code in (400, 422)
     and client.get("/api/week?date=' OR 1=1").status_code == 422 and client.get("/api/week").status_code == 422)
t.ok("A3 a date that is not a Wednesday", client.get("/api/week", params={"date": (W0 + timedelta(days=1)).isoformat()}).status_code == 400)
t.ok("A3 a week that has passed", client.get("/api/week", params={"date": wk(-1).isoformat()}).status_code == 404)
t.ok("A3 the site only answers questions (no writing routes)",
     client.post("/api/plan").status_code == 403 and client.delete("/api/people").status_code == 403
     and client.post("/api/plan", headers={"x-haluka": "1"}).status_code == 405)

# ── A4: nothing private leaves, nothing foreign gets in ───────────────────────
blob = client.get("/api/plan?weeks=8").text + client.get("/api/week", params={"date": W0.isoformat()}).text + client.get("/api/people").text
t.ok("A4 phones, id numbers, addresses and notes never leave the server",
     not any(s in blob for s in (SECRET_PHONE, SECRET_ID, SECRET_NOTE, "רחוב סודי")))
allowed = {"guid", "name", "kind", "freq", "role", "why", "group", "manual"}
t.ok("A4 about a person the screen gets the name, the kind and the reason — no score, priority code or dates",
     all(set(e) <= allowed for e in detail["main"] + detail["reserve_list"] + detail["out"])
     and all(set(p) <= {"guid", "name", "kind", "freq", "why", "active"} for p in ppl["participants"] + ppl["others"])
     and '"score"' not in blob and '"priority"' not in blob and '"days_since"' not in blob)
h = client.get("/api/plan").headers
t.ok("A4 answers are never cached, and the browser is told to trust only this site",
     h.get("cache-control") == "no-store" and "default-src 'self'" in h.get("content-security-policy", "")
     and h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "DENY")
t.ok("A4 a request under another site's name is refused (only this computer is served)",
     client.get("/api/plan", headers={"host": "evil.example.com"}).status_code == 400)
t.ok("A4 the static folder serves its own files only",
     client.get("/static/app.js").status_code == 200 and client.get("/static/style.css").status_code == 200
     and client.get("/static/../store.py").status_code == 404 and client.get("/static/%2e%2e/config.py").status_code == 404
     and client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404)
page = client.get("/").text + client.get("/static/app.js").text
t.ok("A4 the page loads nothing from other sites (works offline, nothing leaks out)",
     "http://" not in page and "https://" not in page and "innerHTML" not in page)
t.ok("A4 the desktop program's data layer is never loaded by the site", "database" not in sys.modules)

# ── A5: the clock decides what is "now" ───────────────────────────────────────
config.now = lambda: datetime(2026, 11, 26, 7, 0)                           # Thursday morning
plan2 = client.get("/api/plan?weeks=2").json()
t.ok("A5 on Thursday morning last night's week has closed and the next one is first",
     plan2["closed_now"] == [W0.isoformat()] and plan2["current_week"] == wk(1).isoformat()
     and plan2["weeks"][0]["main"] == plan["weeks"][1]["main"])
t.ok("A5 ...once only", client.get("/api/plan?weeks=2").json()["closed_now"] == [])

client.close()
shutil.rmtree(TMP, ignore_errors=True)
t.done()
