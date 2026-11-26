# -*- coding: utf-8 -*-
"""The cards screen (stage 3): the list, one card, adding, editing, pausing, look-alikes —
on throw-away databases with invented people, and through the real routes.

Run:  <python 3.12> web/tests/test_cards.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime

from _util import Checker, W0, person, wk

TMP = tempfile.mkdtemp(prefix="haluka_cards_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")
os.environ.pop("HALUKA_WEB_HOSTS", None)

from fastapi.testclient import TestClient  # noqa: E402

from web import app as webapp, cards, config, service, store  # noqa: E402

t = Checker("web cards")
NOW = datetime(W0.year, W0.month, W0.day, 10, 0)
LATER = datetime(W0.year, W0.month, W0.day, 11, 30)


def refusal(fn):
    try:
        fn()
    except cards.Refused as e:
        return e
    return None


def fresh(name, recs, hist=()):
    path = os.path.join(TMP, name, "haluka.db")
    store.create(path)
    conn = store.connect(path)
    with store.tx(conn):
        for r in recs:
            cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in r]
            conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [r[c] for c in cols])
        for i, (g, d) in enumerate(hist):
            conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES (?,?,?,'test')",
                         (f"h{i}", g, d.isoformat()))
        store.set_setting(conn, "default_portions", 5)
        store.set_setting(conn, "default_reserve", 1)
        store.set_meta(conn, "closed_through", wk(-1).isoformat())
    return path, conn


NEW = {"first_name": "חדש", "last_name": "בדיקה", "phone1": "050-1110099", "souls": 5, "status": "פעיל",
       "kind": "regular", "schedule": "דו-שבועי", "per_soul": "-300", "notes": "הערה"}

# ── C1: the pure helpers ──────────────────────────────────────────────────────
t.ok("C1 the name is kept family-first", cards.join_name("פרטי", "משפחה") == "משפחה פרטי" and cards.join_name("יחיד", "") == "יחיד")
t.ok("C1 a card without name parts is split: first word = family; one word = first name",
     cards.name_parts({"full_name": "בדיקה אחת שתיים"}) == ("אחת שתיים", "בדיקה") and cards.name_parts({"full_name": "יחיד"}) == ("יחיד", "")
     and cards.name_parts({"full_name": "x y", "first_name": "א", "last_name": "ב"}) == ("א", "ב"))
t.ok("C1 a phone: 0 and 8 or 9 more digits, with spaces / dashes / brackets / + around",
     all(cards.phone_ok(p) for p in ("0501234567", "050-123 4567", "(02)5812345", "025812345"))
     and not any(cards.phone_ok(p) for p in ("501234567", "05012345", "05012345678", "050-abc-4567", "")))
t.ok("C1 two phones are compared by digits only", cards.phone_key("050-123 4567") == cards.phone_key("0501234567")
     and cards.phone_key("501234567") == "0501234567" and cards.phone_key("12") == "")
t.ok("C1 the kind box of a stored card",
     [cards.kind_of(person(1, f, p, **kw)) for f, p, kw in (
         ("שבועי", None, {}), ("", 4, {}), ("חד-פעמי", 3, {}), ("חד-פעמי", 2, {}), ("חד-פעמי", None, {}),
         ("", None, {"priority_raw": "חובת בירור"}), ("", 1, {}))]
     == ["regular", "regular", "first", "second", "none", "check", "none"])

# ── C2: cleaning what the form sends ──────────────────────────────────────────
f = cards.clean(NEW)
t.ok("C2 a new קבוע: family-first name, priority 4, his schedule; money kept as typed (minus = debt)",
     (f["full_name"], f["first_name"], f["last_name"], f["priority"], f["frequency"], f["status"], f["souls"], f["per_soul"])
     == ("בדיקה חדש", "חדש", "בדיקה", 4, "דו-שבועי", "פעיל", 5, "-300"))
kinds = {k: cards.clean(dict(NEW, kind=k)) for k in ("first", "second", "none", "check")}
t.ok("C2 the kind decides priority and frequency together",
     [(kinds[k]["priority"], kinds[k]["frequency"]) for k in ("first", "second", "none", "check")]
     == [(3, "חד-פעמי"), (2, "חד-פעמי"), (None, ""), (None, "")] and kinds["check"]["priority_raw"] == "חובת בירור")
bad = {
    "no first name": dict(NEW, first_name="  "), "a one-letter name": dict(NEW, first_name="א", last_name=""),
    "a name of 61 letters": dict(NEW, first_name="א" * 61), "a phone without the 0": dict(NEW, phone1="501234567"),
    "letters in a phone": dict(NEW, phone2="טלפון"), "a status that does not exist": dict(NEW, status="הסתיים"),
    "100 souls": dict(NEW, souls=100), "souls that are text": dict(NEW, souls="הרבה"), "minus one child": dict(NEW, children_home=-1),
    "a קבוע without a schedule": dict(NEW, schedule=""), "a kind that does not exist": dict(NEW, kind="vip"),
    "a date that is not a date": dict(NEW, birth_date="1980-13-40"), "a mail that is not a mail": dict(NEW, email="בלי שטרודל"),
    "a note of 2001 letters": dict(NEW, notes="א" * 2001),
}
for what, data in bad.items():
    e = refusal(lambda: cards.clean(data))
    t.ok(f"C2 refused: {what}", e is not None and e.code == "invalid" and len(e.fields) == 1, "it was accepted")
e = refusal(lambda: cards.clean(dict(NEW, first_name="", phone1="12", souls=-3)))
t.ok("C2 several wrong fields are all named at once, each with a sentence",
     e is not None and set(e.fields) == {"first_name", "phone1", "souls"} and all(e.fields.values()))

# ── C3: adding a card — and the weeks follow at once ──────────────────────────
recs = ([person(n, "שבועי", phone1=f"05011100{n:02d}", first_name="", last_name="") for n in (1, 2, 3)]
        + [person(4, "דו-שבועי", phone1="0501110004")]
        + [person(n, "חד-פעמי", 3, per_soul=str(n)) for n in (21, 22, 23, 24)]
        + [person(40, "", 1), person(41, "שבועי", status="מושהה")])
path, conn = fresh("c3", recs, hist=[(f"g{n:04d}", wk(-1)) for n in (1, 2, 3, 4)])
before = service.plan_overview(conn, NOW, 3, path)
card = cards.add_card(conn, NOW, NEW)
g = card["guid"]
stored = store.get_recipient(conn, g)
t.ok("C3 the new card is stored with its own id, the time it was opened, and what was typed",
     len(g) == 32 and stored["full_name"] == "בדיקה חדש" and stored["created_at"] == "2026-11-25 10:00:00"
     and stored["updated_at"] == stored["created_at"] and stored["phone1"] == "050-1110099" and stored["priority"] == 4)
after = service.plan_overview(conn, NOW, 3, path)
t.ok("C3 a new bi-weekly who never received is on this week's list at once, and again in two weeks",
     [g in w["main"] for w in after["weeks"]] == [True, False, True] and g not in before["weeks"][0]["main"])
t.ok("C3 he took the portion of a one-timer, not of a regular",
     after["weeks"][0]["main_regulars"] == before["weeks"][0]["main_regulars"] + 1
     and after["weeks"][0]["main_one_timers"] == before["weeks"][0]["main_one_timers"] - 1)
t.ok("C3 the card as the screen gets it: name parts, kind, schedule, and that he never received",
     (card["first_name"], card["last_name"], card["kind"], card["schedule"], card["received_count"], card["last_received"])
     == ("חדש", "בדיקה", "regular", "דו-שבועי", 0, "") and card["changes"][0]["new"] == "כרטיס חדש")

# ── C4: the same person twice is never created silently ───────────────────────
e = refusal(lambda: cards.add_card(conn, NOW, NEW))
t.ok("C4 adding the same name again is refused, and the existing card is pointed out",
     e is not None and e.code == "duplicate" and [d["guid"] for d in e.duplicates] == [g] and "אותו שם" in e.duplicates[0]["why"])
e = refusal(lambda: cards.add_card(conn, NOW, dict(NEW, first_name="אחר", phone1="0501110004")))
t.ok("C4 a different name with a phone another card has is refused too",
     e is not None and e.code == "duplicate" and [d["guid"] for d in e.duplicates] == ["g0004"] and e.duplicates[0]["why"] == "אותו טלפון")
n_before = conn.execute("SELECT COUNT(*) FROM recipients").fetchone()[0]
t.ok("C4 ...and nothing was written", n_before == len(recs) + 1)
twin = cards.add_card(conn, NOW, NEW, confirmed=True)
t.ok("C4 'these are two different people' saves a second card; both stay, nothing is merged",
     twin["guid"] != g and conn.execute("SELECT COUNT(*) FROM recipients WHERE full_name='בדיקה חדש'").fetchone()[0] == 2
     and [d["guid"] for d in twin["lookalikes"]] == [g])
groups = cards.duplicate_groups(conn)
t.ok("C4 the list of possible doubles shows the pair once (by name), not again by phone",
     [(x["why"], sorted(c["guid"] for c in x["cards"])) for x in groups] == [("שם כפול", sorted([g, twin["guid"]]))])
with store.tx(conn):
    conn.execute("DELETE FROM recipients WHERE guid=?", (twin["guid"],))

# ── C5: editing ───────────────────────────────────────────────────────────────
card = cards.get_card(conn, g)
saved = cards.save_card(conn, LATER, g, dict(card, souls=7, phone2="0521110099", schedule="חודשי"), card["updated_at"])
stored = store.get_recipient(conn, g)
t.ok("C5 only what was changed is written, and the card gets a new stamp",
     saved["changed"] == 3 and (stored["souls"], stored["phone2"], stored["frequency"]) == (7, "0521110099", "חודשי")
     and stored["updated_at"] == "2026-11-25 11:30:00" and stored["created_at"] == "2026-11-25 10:00:00")
log = {c["field"]: (c["old"], c["new"]) for c in saved["changes"]}
t.ok("C5 each change is in the card's list: what it was and what it is",
     log.get("נפשות") == ("5", "7") and log.get("תדירות") == ("דו-שבועי", "חודשי") and log.get("טלפון נוסף") == ("", "0521110099"))
again = cards.save_card(conn, LATER, g, cards.get_card(conn, g), saved["updated_at"])
t.ok("C5 saving a card nobody touched writes nothing", again["changed"] == 0 and again["updated_at"] == saved["updated_at"]
     and len(again["changes"]) == len(saved["changes"]))
e = refusal(lambda: cards.save_card(conn, LATER, g, dict(card, souls=9), card["updated_at"]))
t.ok("C5 a form that was opened before somebody else's change does not overwrite it",
     e is not None and e.code == "stale" and store.get_recipient(conn, g)["souls"] == 7)
e = refusal(lambda: cards.save_card(conn, LATER, g, dict(saved, phone1="12"), saved["updated_at"]))
t.ok("C5 a wrong field stops the whole save", e is not None and e.code == "invalid" and store.get_recipient(conn, g)["phone1"] == "050-1110099")
t.ok("C5 a card that does not exist", refusal(lambda: cards.save_card(conn, LATER, "g9999", NEW)).code == "missing"
     and refusal(lambda: cards.get_card(conn, "g9999")).code == "missing")
# an old card with an unusual combination: priority 1 with a weekly schedule
with store.tx(conn):
    conn.execute("UPDATE recipients SET priority=1, priority_raw='ישן' WHERE guid='g0001'")
odd = cards.get_card(conn, "g0001")
cards.save_card(conn, LATER, "g0001", dict(odd, notes="רק הערה"), odd["updated_at"])
stored = store.get_recipient(conn, "g0001")
t.ok("C5 opening and saving an old card does not 'fix' its priority behind the user's back",
     (stored["priority"], stored["priority_raw"], stored["frequency"], stored["notes"]) == (1, "ישן", "שבועי", "רק הערה"))
t.ok("C5 a card that had no name parts keeps its full name exactly when saved untouched", stored["full_name"] == "בדיקה 0001")
odd = cards.get_card(conn, "g0001")
cards.save_card(conn, LATER, "g0001", dict(odd, kind="first"), odd["updated_at"])
stored = store.get_recipient(conn, "g0001")
t.ok("C5 ...but choosing another kind does change it: first priority = a one-timer",
     (stored["priority"], stored["frequency"]) == (3, "חד-פעמי"))

# ── C6: pausing and bringing back ─────────────────────────────────────────────
plan = service.plan_overview(conn, NOW, 2, path)
t.ok("C6 before: the weekly is on the list", "g0002" in plan["weeks"][0]["main"])
c2 = cards.get_card(conn, "g0002")
paused = cards.save_card(conn, LATER, "g0002", {"status": "מושהה"}, c2["updated_at"])
plan = service.plan_overview(conn, NOW, 2, path)
t.ok("C6 paused: off every coming list at once, and nothing else on the card moved",
     paused["status"] == "מושהה" and paused["changed"] == 1 and all("g0002" not in w["main"] + w["reserve_list"] for w in plan["weeks"])
     and store.get_recipient(conn, "g0002")["frequency"] == "שבועי" and store.get_recipient(conn, "g0002")["full_name"] == "בדיקה 0002")
back = cards.save_card(conn, LATER, "g0002", {"status": "פעיל"}, paused["updated_at"])
t.ok("C6 brought back: on the list again", back["status"] == "פעיל"
     and "g0002" in service.plan_overview(conn, NOW, 2, path)["weeks"][0]["main"])

# ── C7: the list ──────────────────────────────────────────────────────────────
lst = cards.card_list(conn)
by = {c["guid"]: c for c in lst["cards"]}
t.ok("C7 every card is on the list, by name", len(lst["cards"]) == len(recs) + 1
     and [c["name"] for c in lst["cards"]] == sorted(c["name"] for c in lst["cards"]))
t.ok("C7 each row says the kind in words, the status, and whether he takes part in the lists",
     by["g0004"]["kind_text"] == "דו-שבועי" and by["g0021"]["kind_text"] == "חד-פעמי · עדיפות ראשונה"
     and by["g0041"]["status"] == "מושהה" and not by["g0041"]["takes_part"] and not by["g0040"]["takes_part"] and by["g0004"]["takes_part"])
t.ok("C7 a row carries the name, the first phone and the souls — no id number, address or notes",
     all(set(c) == {"guid", "name", "status", "kind", "kind_text", "phone", "souls", "takes_part"} for c in lst["cards"]))
conn.close()

# ── C8: through the real routes ───────────────────────────────────────────────
config.now = lambda: NOW
client = TestClient(webapp.app, base_url="http://127.0.0.1")
SITE = {"x-haluka": "1"}
SECRET_ID, SECRET_NOTE = "123456782", "הערה-פרטית-מאוד"
store.create(config.db_path())
conn = store.connect(config.db_path())
with store.tx(conn):
    for r in [person(1, "שבועי", phone1="0501110001", id_number=SECRET_ID, notes=SECRET_NOTE), person(21, "חד-פעמי", 3)]:
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in r]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [r[c] for c in cols])
    store.set_meta(conn, "closed_through", wk(-1).isoformat())
conn.close()
r = client.get("/cards")
t.ok("C8 the cards page is served, with its own script only",
     r.status_code == 200 and "/static/cards.js" in r.text and "<script>" not in r.text and "style=" not in r.text
     and client.get("/static/cards.js").status_code == 200)
page = r.text + client.get("/static/cards.js").text
t.ok("C8 the page loads nothing from other sites and writes no markup from data",
     "http://" not in page and "https://" not in page and "innerHTML" not in page and "document.write" not in page)
r = client.get("/api/cards")
t.ok("C8 /api/cards: the list, without id numbers or notes", r.status_code == 200 and len(r.json()["cards"]) == 2
     and SECRET_ID not in r.text and SECRET_NOTE not in r.text)
r = client.get("/api/card", params={"guid": "g0001"})
one = r.json()
t.ok("C8 /api/card: the whole card, for the form", r.status_code == 200 and one["id_number"] == SECRET_ID and one["notes"] == SECRET_NOTE)
t.ok("C8 a card that does not exist: 404; a guid that is not a guid: 422",
     client.get("/api/card", params={"guid": "g9999"}).status_code == 404 and client.get("/api/card", params={"guid": "a b'"}).status_code == 422)
body = {"guid": None, "card": NEW}
t.ok("C8 adding without the site's own header is refused, and nothing is added",
     client.post("/api/card", json=body).status_code == 403 and len(client.get("/api/cards").json()["cards"]) == 2)
r = client.post("/api/card", json=body, headers=SITE)
new_guid = r.json().get("guid")
t.ok("C8 adding through the route; the weeks' screen shows him at once",
     r.status_code == 200 and new_guid in client.get("/api/plan?weeks=1").json()["weeks"][0]["main"])
r = client.post("/api/card", json=body, headers=SITE)
t.ok("C8 the same person again: 409 with the look-alike, until confirmed",
     r.status_code == 409 and r.json()["code"] == "duplicate" and r.json()["duplicates"][0]["guid"] == new_guid
     and client.post("/api/card", json=dict(body, confirmed=True), headers=SITE).status_code == 200)
r = client.post("/api/card", json={"guid": new_guid, "updated_at": r.json().get("updated_at"), "card": {"phone1": "12"}}, headers=SITE)
t.ok("C8 a wrong field: 409 with a sentence for that field", r.status_code == 409 and r.json()["code"] == "invalid" and "phone1" in r.json()["fields"])
r = client.post("/api/card", json={"guid": new_guid, "updated_at": "1999-01-01 00:00:00", "card": {"souls": 2}}, headers=SITE)
t.ok("C8 a stale form: 409 'stale'", r.status_code == 409 and r.json()["code"] == "stale")
r = client.post("/api/card", json={"guid": new_guid, "card": {"status": "מושהה"}}, headers=SITE)
t.ok("C8 pausing through the route takes him off the weeks",
     r.status_code == 200 and new_guid not in client.get("/api/plan?weeks=1").json()["weeks"][0]["main"])
t.ok("C8 /api/duplicates lists the two cards with one name", len(client.get("/api/duplicates").json()["groups"]) == 1)
blob = client.get("/api/plan?weeks=4").text + client.get("/api/week", params={"date": W0.isoformat()}).text + client.get("/api/people").text
t.ok("C8 the weeks' screen still gets no phone, id number or note", not any(s in blob for s in ("0501110001", SECRET_ID, SECRET_NOTE)))
t.ok("C8 the desktop program's data layer is never loaded by the site", "database" not in sys.modules)

client.close()
shutil.rmtree(TMP, ignore_errors=True)
t.done()
