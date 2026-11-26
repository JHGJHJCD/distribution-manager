# -*- coding: utf-8 -*-
"""The website's routes — through the real FastAPI app, on a throw-away database.

Run:  <python 3.12> web/tests/test_api.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

import io

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
t.ok("A3 a route that only answers questions takes no writing",
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
     all(client.get(f"/static/{f}").status_code == 200 for f in ("app.js", "style.css", "print.js", "print.css"))
     and client.get("/static/../store.py").status_code == 404 and client.get("/static/%2e%2e/config.py").status_code == 404
     and client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404)
page = "".join(client.get(u).text for u in ("/", "/print", "/static/app.js", "/static/style.css",
                                             "/static/print.js", "/static/print.css"))
t.ok("A4 the page loads nothing from other sites (works offline, nothing leaks out)",
     "http://" not in page and "https://" not in page and "innerHTML" not in page
     and "url(" not in page and "@import" not in page and "eval(" not in page and "document.write" not in page)
t.ok("A4 the desktop program's data layer is never loaded by the site", "database" not in sys.modules)

# ── A5: the clock decides what is "now" ───────────────────────────────────────
config.now = lambda: datetime(2026, 11, 26, 7, 0)                           # Thursday morning
plan2 = client.get("/api/plan?weeks=2").json()
t.ok("A5 on Thursday morning last night's week has closed and the next one is first",
     plan2["closed_now"] == [W0.isoformat()] and plan2["current_week"] == wk(1).isoformat()
     and plan2["weeks"][0]["main"] == plan["weeks"][1]["main"])
t.ok("A5 ...once only", client.get("/api/plan?weeks=2").json()["closed_now"] == [])


# ══ stage 2: changes by hand, numbers for a week, print and Excel ══════════════
# It is Thursday morning: the first coming week is wk(1). In it the two weeklies and the
# bi-weekly are due, the monthly (received last night) is not, and three one-timers fill up.
CUR = wk(1).isoformat()
SITE = {"x-haluka": "1"}                                                    # what the site's own pages send


def plan_now(weeks=3):
    return client.get(f"/api/plan?weeks={weeks}").json()


def week_now(day=CUR):
    return client.get("/api/week", params={"date": day}).json()


def post(url, body, headers=SITE):
    return client.post(url, json=body, headers=headers)


start = plan_now()
t.ok("A6 the starting point: 3 regulars + 3 one-timers, the monthly waits, nothing set by hand",
     start["weeks"][0]["date"] == CUR and len(start["weeks"][0]["main"]) == 6 and "g0004" not in start["weeks"][0]["main"]
     and [w["manual_count"] for w in start["weeks"]] == [0, 0, 0])

# ── A6: writing needs the header that only the site's own pages send ──────────
bodies = [("/api/week/manual", {"date": CUR, "guid": "g0001", "action": "remove"}),
          ("/api/week/numbers", {"date": CUR, "portions": 2, "reserve": 0}),
          ("/api/printed", {"start": CUR, "weeks": 1, "how": "print"})]
t.ok("A6 a change that does not carry the site's own header is refused (403)",
     [post(u, b, headers={}).status_code for u, b in bodies] == [403, 403, 403]
     and [post(u, b, headers={"x-haluka": "0"}).status_code for u, b in bodies] == [403, 403, 403])
t.ok("A6 ...and it changed nothing", plan_now() == start)
t.ok("A6 the writing routes cannot be reached with GET", [client.get(u).status_code for u, _ in bodies] == [405, 405, 405])

# ── A7: by hand — remove, reserve, add, clear ─────────────────────────────────
r = post("/api/week/manual", {"date": CUR, "guid": "g0001", "action": "remove"})
d = week_now()
gone = next((e for e in d["out"] if e["guid"] == "g0001"), {})
t.ok("A7 remove: off this week's list, shown as taken off by hand",
     r.status_code == 200 and r.json() == {"ok": True} and gone.get("manual") == "remove" and gone.get("group") == "removed"
     and "g0001" not in [e["guid"] for e in d["main"] + d["reserve_list"]])
p = plan_now()
t.ok("A7 ...his portion went to the next in line, and next week he is on the list again",
     len(p["weeks"][0]["main"]) == 6 and p["weeks"][0]["manual_count"] == 1 and "g0001" in p["weeks"][1]["main"])
post("/api/week/manual", {"date": CUR, "guid": "g0001", "action": "reserve"})
d = week_now()
t.ok("A7 reserve: first on the reserve, and the reserve is not longer than set",
     d["reserve_list"][0]["guid"] == "g0001" and d["reserve_list"][0]["manual"] == "reserve" and len(d["reserve_list"]) == 2)
post("/api/week/manual", {"date": CUR, "guid": "g0001", "action": "clear"})
t.ok("A7 clear: everything is exactly as it was", plan_now() == start)
r = post("/api/week/manual", {"date": CUR, "guid": "g0004", "action": "add"})
d = week_now()
added = next((e for e in d["main"] if e["guid"] == "g0004"), {})
t.ok("A7 add: the monthly whose turn has not come is on the list, marked, and the list is still 6",
     r.status_code == 200 and added.get("manual") == "add" and "נוסף ביד" in added.get("why", "") and len(d["main"]) == 6)
r = post("/api/week/manual", {"date": CUR, "guid": "g0040", "action": "add"})
t.ok("A7 a card that takes no part in the lists can be added to a week by hand",
     r.status_code == 200 and "g0040" in plan_now()["weeks"][0]["main"] and "g0040" not in plan_now()["weeks"][1]["main"])
post("/api/week/manual", {"date": CUR, "guid": "g0040", "action": "clear"})
refused = {
    "a paused card": post("/api/week/manual", {"date": CUR, "guid": "g0041", "action": "add"}),
    "a card that does not exist": post("/api/week/manual", {"date": CUR, "guid": "g9999", "action": "add"}),
    "a week that has passed": post("/api/week/manual", {"date": W0.isoformat(), "guid": "g0001", "action": "remove"}),
    "a day that is not a Wednesday": post("/api/week/manual", {"date": "2026-12-03", "guid": "g0001", "action": "remove"}),
}
t.ok("A7 what cannot be done is refused with a sentence in Hebrew (409)",
     all(x.status_code == 409 and x.json().get("message") for x in refused.values())
     and "מושהה" in refused["a paused card"].json()["message"] and "עבר" in refused["a week that has passed"].json()["message"],
     str({k: (v.status_code, v.text) for k, v in refused.items()}))
t.ok("A7 a request that is not in the right shape is refused before it reaches the data (422)",
     [post("/api/week/manual", b).status_code for b in (
         {"date": CUR, "guid": "g0001", "action": "delete"}, {"date": CUR, "guid": "g0001"},
         {"date": "next week", "guid": "g0001", "action": "add"}, {"date": CUR, "guid": "", "action": "add"},
         {"date": CUR, "guid": "x" * 65, "action": "add"})] == [422] * 5)

# ── A8: the numbers of one week ───────────────────────────────────────────────
r = post("/api/week/numbers", {"date": CUR, "portions": 4, "reserve": 1})
p = plan_now()
t.ok("A8 4 portions and 1 in reserve for this week only",
     r.status_code == 200 and (p["weeks"][0]["portions"], p["weeks"][0]["reserve"], p["weeks"][0]["numbers_set"]) == (4, 1, True)
     and len(p["weeks"][0]["main"]) == 4 and len(p["weeks"][0]["reserve_list"]) == 1
     and (p["weeks"][1]["portions"], p["weeks"][1]["reserve"], p["weeks"][1]["numbers_set"]) == (6, 2, False))
t.ok("A8 numbers that make no sense are refused",
     [post("/api/week/numbers", {"date": CUR, "portions": v, "reserve": 1}).status_code for v in (-1, 2001, 2.5, "הרבה")] == [422] * 4
     and post("/api/week/numbers", {"date": W0.isoformat(), "portions": 4, "reserve": 1}).status_code == 409
     and plan_now()["weeks"][0]["portions"] == 4)
post("/api/week/numbers", {"date": CUR, "portions": None, "reserve": None})
p = plan_now()
t.ok("A8 back to the ordinary numbers", (p["weeks"][0]["portions"], p["weeks"][0]["reserve"], p["weeks"][0]["numbers_set"]) == (6, 2, False))

# ── A9: printed — and then changed ────────────────────────────────────────────
t.ok("A9 before printing there is no note", plan_now()["weeks"][0]["print"] is None and week_now()["print"] is None)
r = post("/api/printed", {"start": CUR, "weeks": 2, "how": "print"})
p = plan_now()
t.ok("A9 printing two weeks is remembered for exactly those two; nothing has changed yet",
     r.status_code == 200 and r.json() == {"ok": True, "weeks": 2}
     and [w["print"] and w["print"]["changed"] for w in p["weeks"]] == [False, False, None]
     and p["weeks"][0]["print"]["printed_at"] == "2026-11-26 07:00")
t.ok("A9 printing moved nothing", [w["main"] for w in p["weeks"]] == [w["main"] for w in plan_now()["weeks"]]
     and "g0004" in p["weeks"][0]["main"])
post("/api/week/manual", {"date": CUR, "guid": "g0004", "action": "clear"})        # the monthly is taken back off
note = week_now()["print"]
t.ok("A9 after a change the week says: changed since it was printed — who went out, who came in",
     note["changed"] is True and note["removed_names"] == ["בדיקה 0004"] and len(note["added_names"]) == 1
     and note["added_names"][0].startswith("בדיקה 00") and (note["added"], note["removed"]) == (1, 1), str(note))
strip = plan_now()["weeks"][0]["print"]
t.ok("A9 the strip of weeks gets the mark and the numbers, without names",
     strip["changed"] is True and "added_names" not in strip and "removed_names" not in strip)
r = post("/api/printed", {"start": CUR, "weeks": 1, "how": "excel"})
t.ok("A9 producing the list again starts the comparison afresh",
     r.status_code == 200 and week_now()["print"]["changed"] is False and week_now()["print"]["how"] == "excel")
t.ok("A9 a wrong request to remember a printing is refused",
     post("/api/printed", {"start": CUR, "weeks": 1, "how": "fax"}).status_code == 422
     and post("/api/printed", {"start": CUR, "weeks": 0, "how": "print"}).status_code == 422
     and post("/api/printed", {"start": W0.isoformat(), "weeks": 1, "how": "print"}).status_code == 409)

# ── A10: the paper gets the phones; the screen never does ─────────────────────
r = client.get("/api/print", params={"from": CUR, "weeks": 2})
paper = r.json().get("weeks", [])
shown = week_now()
t.ok("A10 /api/print: a list for each week of the range",
     r.status_code == 200 and [w["date"] for w in paper] == [CUR, wk(2).isoformat()])
t.ok("A10 on paper: by name, numbered, the same people as on the screen; the reserve in its own order",
     [x["name"] for x in paper[0]["main"]] == sorted(e["name"] for e in shown["main"])
     and [x["n"] for x in paper[0]["main"]] == list(range(1, 7))
     and [x["name"] for x in paper[0]["reserve_list"]] == [e["name"] for e in shown["reserve_list"]])
t.ok("A10 the phones are there — and nothing else that is private",
     all(x["phones"] == SECRET_PHONE for x in paper[0]["main"] + paper[0]["reserve_list"])
     and not any(s in r.text for s in (SECRET_ID, SECRET_NOTE, "רחוב סודי"))
     and all(set(x) == {"n", "name", "phones", "souls", "kind", "freq", "last", "manual"} for x in paper[0]["main"]))
blob = client.get("/api/plan?weeks=8").text + client.get("/api/week", params={"date": CUR}).text + client.get("/api/people").text
t.ok("A10 the screen's own answers still carry no phone, after everything that was done",
     not any(s in blob for s in (SECRET_PHONE, SECRET_ID, SECRET_NOTE, "רחוב סודי")))
t.ok("A10 a range that starts in a week that has passed, or not on a Wednesday, is refused",
     client.get("/api/print", params={"from": W0.isoformat(), "weeks": 1}).status_code == 409
     and client.get("/api/print", params={"from": "2026-12-03", "weeks": 1}).status_code == 409
     and client.get("/api/print", params={"from": CUR, "weeks": 0}).status_code == 422
     and client.get("/api/print").status_code == 422)
t.ok("A10 reading the paper list remembers nothing by itself (only the site's 'printed' does)",
     week_now(wk(2).isoformat())["print"]["how"] == "print" and plan_now(4)["weeks"][2]["print"] is None)

# ── A11: the Excel file ───────────────────────────────────────────────────────
import openpyxl  # noqa: E402

TRICK_NAME, TRICK_PHONE = "=1+1 בדיקה 0050", "+972501110050"
conn = store.connect(path)
with store.tx(conn):
    trick = person(50, "", None, full_name=TRICK_NAME, phone1=TRICK_PHONE, id_number=SECRET_ID)
    cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in trick]
    conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [trick[c] for c in cols])
conn.close()
post("/api/week/manual", {"date": CUR, "guid": "g0050", "action": "add"})
r = client.get("/api/export.xlsx", params={"from": CUR, "weeks": 2})
t.ok("A11 the Excel answer is a file to download, with a plain name",
     r.status_code == 200 and "spreadsheetml" in r.headers.get("content-type", "")
     and r.headers.get("content-disposition") == f'attachment; filename="haluka-{CUR}-2w.xlsx"')
wb = openpyxl.load_workbook(io.BytesIO(r.content))
ws = wb.worksheets[0]
cells = [c for sheet in wb.worksheets for row in sheet.iter_rows() for c in row if c.value is not None]
t.ok("A11 it opens: a sheet for each week, named by its date, right-to-left",
     wb.sheetnames == [wk(1).strftime("%d-%m-%Y"), wk(2).strftime("%d-%m-%Y")]
     and all(sheet.sheet_view.rightToLeft for sheet in wb.worksheets))
values = [c.value for c in ws["B"]]
t.ok("A11 the heading, the list and the reserve are on the sheet",
     "חלוקת רביעי " + wk(1).strftime("%d/%m/%Y") in str(ws["A1"].value)
     and all(e["name"] in values for e in week_now()["main"] + week_now()["reserve_list"])
     and any(c.value == SECRET_PHONE for c in ws["C"]))
name_cell = next((c for c in cells if c.value == TRICK_NAME), None)
phone_cell = next((c for c in cells if c.value == TRICK_PHONE), None)
t.ok("A11 a name that starts with '=' stays the text it is — it is never a formula",
     name_cell is not None and name_cell.data_type == "s" and phone_cell is not None and phone_cell.data_type == "s"
     and not any(c.data_type == "f" for c in cells))
t.ok("A11 nothing private beyond the phones is in the file",
     not any(str(c.value) in (SECRET_ID, SECRET_NOTE) or "רחוב סודי" in str(c.value) for c in cells))
t.ok("A11 an Excel range from a week that has passed is refused",
     client.get("/api/export.xlsx", params={"from": W0.isoformat(), "weeks": 1}).status_code == 409)
post("/api/week/manual", {"date": CUR, "guid": "g0050", "action": "clear"})

# ── A12: the print page ───────────────────────────────────────────────────────
r = client.get("/print", params={"from": CUR, "weeks": 2})
t.ok("A12 the print page is served, right-to-left, with its own script and style only",
     r.status_code == 200 and 'dir="rtl"' in r.text and "/static/print.js" in r.text and "/static/print.css" in r.text
     and "<script>" not in r.text and "style=" not in r.text and "onclick" not in r.text)
t.ok("A12 no name is written into the page itself (the lists come separately, and are not kept by the browser)",
     "בדיקה 00" not in r.text and r.headers.get("cache-control") == "no-store")


# ══ stage 4: holiday events ════════════════════════════════════════════════════
# It is still Thursday 26/11 07:00. Five cards get the holiday mark (one of them the card
# that takes no part in the weeks), with an income for the filter.
conn = store.connect(path)
with store.tx(conn):
    for g_, income in (("g0001", "3000"), ("g0003", "8000"), ("g0021", "2000"), ("g0022", ""), ("g0040", "1000")):
        conn.execute("UPDATE recipients SET holiday_support=1, income=? WHERE guid=?", (income, g_))
conn.close()
HDAY = (wk(1) - timedelta(days=3)).isoformat()                             # Sunday 29/11
EVENT = {"date": HDAY, "holiday": "*", "portions": 10, "reserve": 2, "criteria": {}}

# ── A13: the event routes write only with the site's own header ───────────────
writes = [("/api/event/save", EVENT), ("/api/event/delete", {"event": "x"}),
          ("/api/event/manual", {"event": "x", "guid": "g0001", "action": "add"})]
t.ok("A13 an event cannot be set up, changed or deleted without the site's own header (403)",
     [post(u, b, headers={}).status_code for u, b in writes] == [403, 403, 403]
     and client.get("/api/events").json()["open"] == [])
t.ok("A13 the writing routes of an event cannot be reached with GET", [client.get(u).status_code for u, _ in writes] == [405] * 3)

# ── A14: setting an event up, reading it ──────────────────────────────────────
r = post("/api/event/save", EVENT)
EV = r.json().get("guid", "")
t.ok("A14 a new event: an answer with its own id", r.status_code == 200 and r.json()["ok"] is True and len(EV) >= 8)
ovw = client.get("/api/events").json()
t.ok("A14 /api/events: the event that is ahead, in numbers; what an event can be for; the filter fields",
     [e["guid"] for e in ovw["open"]] == [EV] and ovw["open"][0]["main_count"] == 5 and ovw["open"][0]["marked"] == 5
     and ovw["holidays"][0] == {"code": "*", "label": "כל נתמכי החגים"} and len(ovw["holidays"]) == 7
     and [f["field"] for f in ovw["filter"]] == ["children_total", "income", "per_soul"] and ovw["first_day"] == "2026-11-26")
ed = client.get("/api/event", params={"guid": EV}).json()
t.ok("A14 /api/event: the five marked cards receive, each with a reason; nobody unmarked is listed",
     {e["guid"] for e in ed["main"]} == {"g0001", "g0003", "g0021", "g0022", "g0040"} and all(e["why"] for e in ed["main"])
     and ed["out"] == [] and ed["unmarked"] == 11 and ed["closed"] is False)
r = post("/api/event/save", dict(EVENT, guid=EV, criteria={"income": {"max": 5000}}))
ed = client.get("/api/event", params={"guid": EV}).json()
groups = {e["guid"]: e["group"] for e in ed["out"]}
t.ok("A14 a filter: who passes receives; missing data and outside-the-filter are set apart",
     r.status_code == 200 and {e["guid"] for e in ed["main"]} == {"g0001", "g0021", "g0040"}
     and groups == {"g0022": "ev_missing", "g0003": "ev_filter"} and ed["criteria"] == {"income": {"min": None, "max": 5000.0}})
plan3 = plan_now(3)
t.ok("A14 the weeks screen is told about the event, and the marked one-timer is paused in the weeks after it",
     [e["guid"] for e in plan3["events"]] == [EV] and "g0021" in plan3["events"][0]["main"]
     and "g0021" not in plan3["weeks"][0]["main"] and "g0021" not in plan3["weeks"][1]["main"])
bad_shape = [dict(EVENT, date="next week"), dict(EVENT, portions=-1), dict(EVENT, portions=2001), dict(EVENT, portions=2.5),
             dict(EVENT, portions="הרבה"), {k: v for k, v in EVENT.items() if k != "holiday"}, dict(EVENT, colour="red"),
             dict(EVENT, criteria={"income": {"max": "הרבה"}}), dict(EVENT, criteria={"income": {"most": 5}}),
             dict(EVENT, guid="x" * 65)]
t.ok("A14 an event that is not in the right shape is refused before it reaches the data (422)",
     [post("/api/event/save", b).status_code for b in bad_shape] == [422] * len(bad_shape))
refused = {
    "a day that has passed": post("/api/event/save", dict(EVENT, date=W0.isoformat())),
    "a holiday that does not exist": post("/api/event/save", dict(EVENT, holiday="יום העצמאות")),
    "'from' above 'up to'": post("/api/event/save", dict(EVENT, criteria={"income": {"min": 9, "max": 3}})),
    "a filter field that does not exist": post("/api/event/save", dict(EVENT, criteria={"souls": {"min": 3}})),
    "a change to an event that does not exist": post("/api/event/save", dict(EVENT, guid="nope")),
    "an event that does not exist": client.get("/api/event", params={"guid": "nope"}),
}
t.ok("A14 what cannot be done is refused with a sentence in Hebrew (409)",
     all(x.status_code == 409 and x.json().get("message") for x in refused.values())
     and "עבר" in refused["a day that has passed"].json()["message"],
     str({k: (v.status_code, v.text[:60]) for k, v in refused.items()}))
t.ok("A14 after all the refusals there is still exactly one event", len(client.get("/api/events").json()["open"]) == 1)

# ── A15: by hand for an event ─────────────────────────────────────────────────
r = post("/api/event/manual", {"event": EV, "guid": "g0002", "action": "add"})
ed = client.get("/api/event", params={"guid": EV}).json()
t.ok("A15 add: a card that is not marked is on the event's list, marked as set by hand",
     r.status_code == 200 and ed["main"][0]["guid"] == "g0002" and ed["main"][0]["manual"] == "add" and ed["manual_count"] == 1)
post("/api/event/manual", {"event": EV, "guid": "g0002", "action": "clear"})
t.ok("A15 clear: he is off it again", "g0002" not in [e["guid"] for e in client.get("/api/event", params={"guid": EV}).json()["main"]])
refused = [post("/api/event/manual", {"event": EV, "guid": "g0041", "action": "add"}),
           post("/api/event/manual", {"event": EV, "guid": "g9999", "action": "add"}),
           post("/api/event/manual", {"event": "nope", "guid": "g0001", "action": "add"})]
t.ok("A15 a paused card, a card or an event that does not exist: refused in words (409)",
     all(x.status_code == 409 and x.json().get("message") for x in refused) and "מושהה" in refused[0].json()["message"])
t.ok("A15 a request in the wrong shape is refused (422)",
     [post("/api/event/manual", b).status_code for b in ({"event": EV, "guid": "g0001", "action": "delete"},
                                                         {"event": EV, "guid": "g0001"}, {"guid": "g0001", "action": "add"})] == [422] * 3)

# ── A16: nothing private in the event's answers; the paper gets the phones ────
blob = client.get("/api/events").text + client.get("/api/event", params={"guid": EV}).text + client.get("/api/plan?weeks=4").text
t.ok("A16 the event's answers carry no phone, id number, address, note — and no income",
     not any(s_ in blob for s_ in (SECRET_PHONE, SECRET_ID, SECRET_NOTE, "רחוב סודי", "8000", "2000"))
     and '"score"' not in blob and '"days_since"' not in blob and '"priority"' not in blob)
t.ok("A16 about a person in an event the screen gets the name, the kind and the reason only",
     all(set(e) <= allowed for e in ed["main"] + ed["reserve_list"] + ed["out"]))
r = client.get("/api/print", params={"event": EV})
sheet = r.json().get("weeks", [{}])[0]
t.ok("A16 /api/print for an event: one sheet, named for the holiday and its day, by name, with the phones",
     r.status_code == 200 and len(r.json()["weeks"]) == 1 and "חלוקת חג" in sheet["title"] and "יום ראשון" in sheet["title"]
     and [x["name"] for x in sheet["main"]] == sorted(x["name"] for x in sheet["main"]) and len(sheet["main"]) == 3
     and all(x["phones"] == SECRET_PHONE for x in sheet["main"] if x["name"] != "בדיקה 0040")
     and not any(s_ in r.text for s_ in (SECRET_ID, SECRET_NOTE, "רחוב סודי")))
r = client.get("/api/export.xlsx", params={"event": EV})
wb = openpyxl.load_workbook(io.BytesIO(r.content)) if r.status_code == 200 else None
t.ok("A16 the Excel file of an event: a download named for its day, one right-to-left sheet with the list",
     wb is not None and r.headers.get("content-disposition") == f'attachment; filename="haluka-holiday-{HDAY}.xlsx"'
     and len(wb.worksheets) == 1 and wb.worksheets[0].sheet_view.rightToLeft
     and "חלוקת חג" in str(wb.worksheets[0]["A1"].value) and "בדיקה 0001" in [c.value for c in wb.worksheets[0]["B"]])
t.ok("A16 an event that does not exist has no paper and no file",
     client.get("/api/print", params={"event": "nope"}).status_code == 409
     and client.get("/api/export.xlsx", params={"event": "nope"}).status_code == 409
     and client.get("/api/export.xlsx").status_code == 422)
t.ok("A16 before printing the event carries no note", client.get("/api/event", params={"guid": EV}).json()["print"] is None)
r = post("/api/printed", {"event": EV, "how": "print"})
post("/api/event/manual", {"event": EV, "guid": "g0002", "action": "add"})
note = client.get("/api/event", params={"guid": EV}).json()["print"]
t.ok("A16 printed, then changed: the event says who was added since",
     r.status_code == 200 and note["changed"] is True and note["added_names"] == ["בדיקה 0002"] and note["removed"] == 0)
t.ok("A16 a 'printed' that names neither weeks nor an event is refused",
     post("/api/printed", {"how": "print"}).status_code == 422 and post("/api/printed", {"event": "nope", "how": "print"}).status_code == 409)

# ── A17: the clock closes an event too; then it is history ────────────────────
config.now = lambda: datetime(2026, 11, 30, 6, 5)                           # Monday morning: Sunday's event is over
p = client.get("/api/plan?weeks=2").json()
ovw = client.get("/api/events").json()
t.ok("A17 on Monday morning Sunday's event has closed by itself, once",
     p["closed_events_now"] == ["חלוקת חג 29/11/2026"] and client.get("/api/plan?weeks=2").json()["closed_events_now"] == []
     and ovw["open"] == [] and [e["guid"] for e in ovw["past"]] == [EV] and ovw["past"][0]["main_count"] == 4)
closed = client.get("/api/event", params={"guid": EV}).json()
t.ok("A17 the passed event is shown as it was written (the one added by hand included), names only",
     closed["closed"] is True and {e["guid"] for e in closed["main"]} == {"g0001", "g0002", "g0021", "g0040"}
     and SECRET_PHONE not in str(closed))
t.ok("A17 a passed event cannot be changed, set by hand, printed or deleted (409)",
     [post("/api/event/save", dict(EVENT, guid=EV, date="2026-12-06")).status_code,
      post("/api/event/manual", {"event": EV, "guid": "g0003", "action": "add"}).status_code,
      post("/api/event/delete", {"event": EV}).status_code,
      client.get("/api/print", params={"event": EV}).status_code] == [409] * 4)
r = post("/api/event/save", dict(EVENT, date="2026-12-06", holiday="חנוכה", portions=4))
EV2 = r.json().get("guid", "")
r = post("/api/event/delete", {"event": EV2})
t.ok("A17 an event that is still ahead can be deleted",
     r.status_code == 200 and client.get("/api/events").json()["open"] == []
     and client.get("/api/event", params={"guid": EV2}).status_code == 409)
config.now = lambda: datetime(2026, 11, 26, 7, 0)

client.close()
shutil.rmtree(TMP, ignore_errors=True)
t.done()
