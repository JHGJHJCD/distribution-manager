# -*- coding: utf-8 -*-
"""Stage 3 — the recipients: the card rules, the list, adding / changing / pausing /
deleting, and the look-alike suggestions. Through the real FastAPI app, on a throw-away
database of invented people.

Run:  <python 3.12> web/tests/test_cards.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime

from _util import Checker, W0, person, wk

TMP = tempfile.mkdtemp(prefix="haluka_cards_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")       # BEFORE the app is imported
os.environ.pop("HALUKA_WEB_HOSTS", None)

from fastapi.testclient import TestClient  # noqa: E402

from web import app as webapp, cards, config, store  # noqa: E402

t = Checker("web cards")
config.now = lambda: datetime(W0.year, W0.month, W0.day, 20, 30)          # Wednesday evening
client = TestClient(webapp.app, base_url="http://127.0.0.1")
H = {"X-Haluka": "1"}


def post(url, body, headers=H):
    return client.post(url, json=body, headers=headers)


def get(url, **params):
    return client.get(url, params=params)


def db():
    return store.connect(config.db_path())


def count(sql, *args):
    conn = db()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def main_of(week=0):
    return get("/api/plan", weeks=week + 1).json()["weeks"][week]["main"]


# ── C1: the rules of a card (pure) ────────────────────────────────────────────
t.ok("C1 the name is family first: 'משפחה פרטי'",
     cards.join_name("פרטי", "משפחה") == "משפחה פרטי" and cards.split_full_name("משפחה פרטי שני") == ("פרטי שני", "משפחה"))
t.ok("C1 a status is only פעיל / מושהה (empty = active, the old 'הסתיים' = paused)",
     [cards.normalize_status(s) for s in ("", None, "פעיל", "מושהה", "הסתיים")]
     == ["פעיל", "פעיל", "פעיל", "מושהה", "מושהה"])
t.ok("C1 the same phone, however it was typed", cards.phone_key("050-123 4567") == cards.phone_key("0501234567")
     == cards.phone_key("501234567"))
t.ok("C1 each of the eight kinds is written and read back as itself",
     all(cards.type_key(cards.clean({"last_name": "א", "type": k}, None)) == k for k, _l, _f, _p in cards.TYPES))
new = cards.clean({"last_name": "  בדיקה ", "first_name": "אחת   שתיים", "type": "one2", "souls": "5"}, None)
t.ok("C1 a new card: name built, active, one-timer of the second priority",
     new["full_name"] == "בדיקה אחת שתיים" and new["status"] == "פעיל" and new["frequency"] == "חד-פעמי"
     and new["priority"] == 2 and new["souls"] == 5, str(new))


def refused(data, existing=None):
    try:
        cards.clean(data, existing)
    except cards.Invalid:
        return True
    return False


t.ok("C1 refused: no name / an unknown kind / a third status / souls that is not a number / a phone of 4 digits",
     refused({"type": "w1"}) and refused({"last_name": "א", "type": "zzz"})
     and refused({"last_name": "א", "status": "אולי"}) and refused({"last_name": "א", "souls": "הרבה"})
     and refused({"last_name": "א", "phone1": "1234"}))
odd = {"guid": "x", "full_name": "בדיקה מוזר", "frequency": "חד-פעמי", "priority": 1, "priority_raw": "חובת בירור"}
kept = cards.clean({"type": cards.type_key(odd), "souls": "3"}, odd)
t.ok("C1 saving without changing the kind leaves an unusual priority exactly as it was",
     "priority" not in kept and "frequency" not in kept and "priority_raw" not in kept, str(kept))
t.ok("C1 nothing can write a derived date or the identity through a card",
     not {"last_distribution", "next_distribution", "guid", "id", "created_at"} & set(
         cards.clean({"last_name": "א", "type": "w1", "last_distribution": "2026-01-01", "next_distribution": "2026-01-01",
                      "guid": "zz", "id": 7, "created_at": "x"}, None)))

# ── an invented database ──────────────────────────────────────────────────────
SECRET_PHONE, SECRET_ID, SECRET_NOTE, SECRET_ADDR = "0501234567", "123456782", "הערה-פרטית-מאוד", "רחוב-סודי 7"
recs = ([person(n, f, 4, phone1=SECRET_PHONE[:-1] + str(n), id_number=SECRET_ID, notes=SECRET_NOTE, address=SECRET_ADDR)
         for n, f in enumerate(["שבועי", "שבועי", "דו-שבועי", "חודשי"], 1)]
        + [person(n, "חד-פעמי", 3 if n % 2 else 2) for n in range(21, 27)]
        + [person(40, "", 1), person(41, "שבועי", 4, status="מושהה")])
path = config.db_path()
store.create(path)
conn = store.connect(path)
with store.tx(conn):
    for rec in recs:
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in rec]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [rec[c] for c in cols])
    for i, d in enumerate((wk(-1), wk(-2), wk(-3))):
        conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES (?, 'g0001', ?, 'test')",
                     (f"h{i}", d.isoformat()))
    store.set_setting(conn, "default_portions", 8)
    store.set_setting(conn, "default_reserve", 2)
    store.set_meta(conn, "closed_through", wk(-1).isoformat())
conn.close()
N0 = len(recs)

# ── C2: the list and the search ───────────────────────────────────────────────
lst = get("/api/cards").json()
t.ok("C2 the list: every card, by name, with its kind in words",
     lst["total"] == N0 and lst["found"] == N0 and lst["active"] == N0 - 1
     and [c["name"] for c in lst["cards"]] == sorted(c["name"] for c in lst["cards"])
     and {c["guid"]: c["type_label"] for c in lst["cards"]}["g0003"] == "קבוע · דו-שבועי")
t.ok("C2 the list tells when each one last received — from the history, not from a stored date",
     {c["guid"]: c["last"] for c in lst["cards"]}["g0001"] == wk(-1).isoformat())
found = get("/api/cards", q="050-1234 563").json()
t.ok("C2 a phone number finds its card (dashes and spaces ignored)", [c["guid"] for c in found["cards"]] == ["g0003"])
t.ok("C2 a name finds its card; 'paused' shows only the paused",
     [c["guid"] for c in get("/api/cards", q="0022").json()["cards"]] == ["g0022"]
     and [c["guid"] for c in get("/api/cards", show="paused").json()["cards"]] == ["g0041"])
leaks = [u for u, r in (("/api/cards", client.get("/api/cards")),
                        ("/api/cards?q=phone", get("/api/cards", q="0501234563")),
                        ("/api/cards?q=addr", get("/api/cards", q="סודי")),
                        ("/api/duplicates", client.get("/api/duplicates")),
                        ("/api/cards/deleted", client.get("/api/cards/deleted")))
         if any(s in r.text for s in (SECRET_PHONE[:-1], SECRET_ID, SECRET_NOTE, SECRET_ADDR))]
t.ok("C2 the list, the search and the suggestions never carry a phone, an ID, an address or a note", not leaks, str(leaks))

# ── C3: one card that was opened ──────────────────────────────────────────────
card = get("/api/card", guid="g0003").json()
t.ok("C3 an opened card has its phone and details",
     card["phone1"] == SECRET_PHONE[:-1] + "3" and card["id_number"] == SECRET_ID and card["notes"] == SECRET_NOTE
     and card["type"] == "w2" and card["status"] == "פעיל")
t.ok("C3 the card says in which coming weeks he receives (every second week)",
     card["coming"]["receives"][:3] == [wk(0).isoformat(), wk(2).isoformat(), wk(4).isoformat()], str(card["coming"]))
t.ok("C3 a card that is not there: a clear refusal", get("/api/card", guid="nope").status_code == 409)

# ── C4: adding ────────────────────────────────────────────────────────────────
before = main_of()
r = post("/api/card/save", {"last_name": "חדש", "first_name": "בדיקה", "type": "w1", "souls": "3", "phone1": "052-0000001"}, headers={})
t.ok("C4 without the site's own header nothing is added", r.status_code == 403 and count("SELECT COUNT(*) FROM recipients") == N0)
r = post("/api/card/save", {"last_name": "חדש", "first_name": "בדיקה", "type": "w1", "souls": "3", "phone1": "052-0000001"})
added = r.json()
t.ok("C4 a new card is written: family-first name, active, registered today",
     r.status_code == 200 and added["ok"] and added["new"] and count("SELECT COUNT(*) FROM recipients") == N0 + 1
     and count("SELECT COUNT(*) FROM recipients WHERE guid=? AND full_name='חדש בדיקה' AND status='פעיל' "
               "AND frequency='שבועי' AND start_date=?", added["guid"], W0.isoformat()) == 1)
NEW = added["guid"]
t.ok("C4 ... and the coming week is computed again with him on it, at once",
     NEW not in before and NEW in main_of() and NEW in main_of(3))
t.ok("C4 refused, and nothing written: no name / an unknown kind / a field that is not on a card",
     post("/api/card/save", {"type": "w1"}).status_code == 409
     and post("/api/card/save", {"last_name": "א", "type": "zz"}).status_code == 409
     and post("/api/card/save", {"last_name": "א", "type": "w1", "last_distribution": "2026-01-01"}).status_code == 422
     and post("/api/card/save", {"last_name": "א", "type": "w1", "full_name": "ב א"}).status_code == 422
     and count("SELECT COUNT(*) FROM recipients") == N0 + 1)

# ── C5: a new card that looks like an existing one ────────────────────────────
r = post("/api/card/save", {"last_name": "חדש", "first_name": "בדיקה", "type": "one1", "phone1": "052-9999999"})
t.ok("C5 the same name with another phone: asked first, nothing written, nothing merged",
     r.status_code == 200 and r.json()["ok"] is False and [a["guid"] for a in r.json()["alike"]] == [NEW]
     and r.json()["alike"][0]["same_name"] and count("SELECT COUNT(*) FROM recipients") == N0 + 1)
r = post("/api/card/save", {"last_name": "אחר", "first_name": "לגמרי", "type": "one1", "phone1": "0520000001"})
t.ok("C5 the same phone typed differently is noticed too",
     r.json()["ok"] is False and r.json()["alike"][0]["same_phone"] and not r.json()["alike"][0]["same_name"])
t.ok("C5 the question itself carries no phone", "052" not in r.text)
r = post("/api/card/save", {"last_name": "חדש", "first_name": "בדיקה", "type": "one1", "phone1": "052-9999999", "sure": True})
TWIN = r.json().get("guid")
t.ok("C5 'two different people' = a second card; the first one is untouched",
     r.json()["ok"] and TWIN != NEW and count("SELECT COUNT(*) FROM recipients WHERE full_name='חדש בדיקה'") == 2
     and count("SELECT COUNT(*) FROM recipients WHERE guid=? AND phone1='052-0000001' AND phone2=''", NEW) == 1)
t.ok("C5 ... and that answer is remembered: the pair is not suggested again",
     not any({NEW, TWIN} <= {m["guid"] for m in g["members"]} for g in client.get("/api/duplicates").json()["groups"]))

# ── C6: changing ──────────────────────────────────────────────────────────────
card = get("/api/card", guid=NEW).json()
r = post("/api/card/save", {"guid": NEW, "seen": card["seen"], "type": "w4", "souls": "7", "phone2": "03-1112223",
                            "last_name": card["last_name"], "first_name": card["first_name"]})
after = get("/api/card", guid=NEW).json()
t.ok("C6 a change is saved, and the coming weeks follow (monthly: every fourth week)",
     r.status_code == 200 and after["type"] == "w4" and after["souls"] == 7 and after["phone2"] == "03-1112223"
     and after["coming"]["receives"][:2] == [wk(0).isoformat(), wk(4).isoformat()] and NEW not in main_of(1),
     str(after["coming"]))
r = post("/api/card/save", {"guid": NEW, "seen": card["seen"], "souls": "9"})
t.ok("C6 a card that was changed elsewhere meanwhile is not overwritten",
     r.status_code == 409 and get("/api/card", guid=NEW).json()["souls"] == 7)
conn = db()
with store.tx(conn):
    conn.execute("UPDATE recipients SET first_name='אחר', last_name='שונה' WHERE guid='g0002'")   # a split that does not match
conn.close()
card = get("/api/card", guid="g0002").json()
form = {k: card[k] for k in ("last_name", "first_name", "phone1", "phone2", "phone3", "address", "id_number", "notes")}
r = post("/api/card/save", dict(form, guid="g0002", seen=card["seen"], type=card["type"], souls=str(card["souls"])))
t.ok("C6 saving a card without touching the name never changes the name (the identity)",
     r.status_code == 200 and count("SELECT COUNT(*) FROM recipients WHERE guid='g0002' AND full_name='בדיקה 0002'") == 1)
card = get("/api/card", guid="g0040").json()
post("/api/card/save", {"guid": "g0040", "seen": card["seen"], "type": card["type"], "souls": "2"})
t.ok("C6 ... nor the stored priority of a card whose kind was not changed",
     count("SELECT COUNT(*) FROM recipients WHERE guid='g0040' AND priority=1 AND frequency='' AND souls=2") == 1)

# ── C7: pausing ───────────────────────────────────────────────────────────────
t.ok("C7 the only two statuses", post("/api/card/status", {"guid": "g0002", "status": "נמחק"}).status_code == 409)
r = post("/api/card/status", {"guid": "g0002", "status": "מושהה"})
t.ok("C7 a paused card is on no coming list, and says why",
     r.status_code == 200 and "g0002" not in main_of() and "g0002" not in main_of(2)
     and "מושהה" in get("/api/card", guid="g0002").json()["why_out"])
post("/api/card/status", {"guid": "g0002", "status": "פעיל"})
t.ok("C7 back to active: on the list again", "g0002" in main_of())

# ── C8: deleting, and bringing back ───────────────────────────────────────────
r = post("/api/card/delete", {"guid": "g0001"})
t.ok("C8 a card with history cannot be deleted (it can be paused)",
     r.status_code == 409 and "היסטוריה" in r.json()["message"] and get("/api/card", guid="g0001").status_code == 200
     and get("/api/card", guid="g0001").json()["can_delete"] is False)
post("/api/week/manual", {"date": wk(1).isoformat(), "guid": TWIN, "action": "add"})
r = post("/api/card/delete", {"guid": TWIN})
gone = client.get("/api/cards/deleted").json()["cards"]
t.ok("C8 a card that never received is deleted — and kept whole, to be brought back",
     r.status_code == 200 and get("/api/card", guid=TWIN).status_code == 409 and [d["guid"] for d in gone] == [TWIN]
     and count("SELECT COUNT(*) FROM week_manual WHERE recipient_guid=?", TWIN) == 0
     and count("SELECT COUNT(*) FROM history") == 3)
t.ok("C8 a backup was taken before the delete",
     any("before-delete-card" in f for f in os.listdir(config.backup_dir())))
r = post("/api/card/restore", {"guid": TWIN})
back = get("/api/card", guid=TWIN).json()
t.ok("C8 restored: the same card, with its phone and kind",
     r.status_code == 200 and back.get("phone1") == "052-9999999" and back.get("type") == "one1"
     and back.get("name") == "חדש בדיקה" and client.get("/api/cards/deleted").json()["cards"] == [])

# ── C9: look-alikes — a suggestion only ───────────────────────────────────────
conn = db()
with store.tx(conn):
    store.insert_recipient(conn, {"full_name": "בדיקה 0001", "phone1": "0531111111", "phone2": "0532222222",
                                  "phone3": "0533333333", "frequency": "חד-פעמי", "priority": 3, "souls": 6,
                                  "address": "רחוב אחר 1", "email": "x@example.org", "notes": "הערה של הכפיל"},
                           config.now(), guid="dupA")
    store.insert_recipient(conn, {"full_name": "אחר לגמרי", "phone1": "050-123-4562", "frequency": "שבועי",
                                  "priority": 4, "id_number": "999999998"}, config.now(), guid="dupB")
    conn.execute("UPDATE recipients SET phone2='0541111111', phone3='0542222222' WHERE guid='g0001'")
    conn.execute("INSERT INTO history (guid, recipient_guid, dist_date, source) VALUES ('hd', 'dupA', ?, 'test')",
                 (wk(-5).isoformat(),))
conn.close()
groups = client.get("/api/duplicates").json()["groups"]
as_sets = {(g["type"], frozenset(m["guid"] for m in g["members"])) for g in groups}
t.ok("C9 suggested: the same name, and the same phone on two cards",
     as_sets == {("name", frozenset({"g0001", "dupA"})), ("phone", frozenset({"g0002", "dupB"}))}, str(as_sets))
t.ok("C9 the list counts the suggestions", get("/api/cards").json()["duplicates"] == 2)
total = count("SELECT COUNT(*) FROM recipients")
t.ok("C9 a suggestion changes nothing by itself: every card is still there",
     total == N0 + 4 and get("/api/card", guid="dupA").status_code == 200)

cmp_ = get("/api/duplicates/compare", a="dupB", b="g0002").json()
t.ok("C9 comparing: the older card stays when neither has history; different IDs are pointed out",
     cmp_["keep"]["guid"] == "g0002" and cmp_["drop"]["guid"] == "dupB" and cmp_["ids_differ"] is True)
r = post("/api/duplicates/different", {"guids": ["g0002", "dupB"]})
t.ok("C9 'different people': the suggestion is gone, both cards exactly as they were",
     r.status_code == 200 and len(client.get("/api/duplicates").json()["groups"]) == 1
     and count("SELECT COUNT(*) FROM recipients") == total
     and get("/api/card", guid="dupB").json()["phone1"] == "050-123-4562")

cmp_ = get("/api/duplicates/compare", a="dupA", b="g0001").json()
t.ok("C9 comparing for a merge: the card with more history stays, and what it would gain is said",
     cmp_["keep"]["guid"] == "g0001" and cmp_["keep"]["history_count"] == 3 and cmp_["drop"]["history_count"] == 1
     and "מייל" in cmp_["gains"] and any(d["label"] == "טלפונים" for d in cmp_["differences"]), str(cmp_))
r = post("/api/duplicates/merge", {"keep": "dupA", "drop": "g0001"})
t.ok("C9 a merge the other way round (not what the comparison showed) is refused",
     r.status_code == 409 and count("SELECT COUNT(*) FROM recipients") == total)
t.ok("C9 a merge needs the site's header too", post("/api/duplicates/merge", {"keep": "g0001", "drop": "dupA"}, headers={}).status_code == 403)
post("/api/week/manual", {"date": wk(2).isoformat(), "guid": "dupA", "action": "reserve"})
r = post("/api/duplicates/merge", {"keep": "g0001", "drop": "dupA"})
kept = get("/api/card", guid="g0001").json()
numbers = " ".join(str(kept[k]) for k in ("phone1", "phone2", "phone3", "notes"))
t.ok("C9 merged on request: one card left, and it moved 1 history row",
     r.status_code == 200 and r.json()["moved"] == 1 and count("SELECT COUNT(*) FROM recipients") == total - 1
     and get("/api/card", guid="dupA").status_code == 409)
t.ok("C9 no phone number is lost: the kept card's three stay, the other three are in the notes",
     all(p in numbers for p in ("0541111111", "0542222222", "0531111111", "0532222222", "0533333333"))
     and kept["phone1"] == SECRET_PHONE[:-1] + "1", numbers)
t.ok("C9 what the kept card had stays; only its empty fields were filled",
     kept["address"] == SECRET_ADDR and kept["email"] == "x@example.org" and kept["type"] == "w1"
     and kept["name"] == "בדיקה 0001" and SECRET_NOTE in kept["notes"] and "הערה של הכפיל" in kept["notes"])
t.ok("C9 the history of both is on the kept card, none of it deleted",
     kept["history_count"] == 4 and count("SELECT COUNT(*) FROM history") == 4
     and count("SELECT COUNT(*) FROM history WHERE recipient_guid='dupA'") == 0)
t.ok("C9 what was set by hand for the other card moved with it",
     count("SELECT COUNT(*) FROM week_manual WHERE recipient_guid='g0001' AND week_wed=? AND action='reserve'",
           wk(2).isoformat()) == 1)
conn = db()
row = conn.execute("SELECT reason, merged_into, card FROM deleted_cards WHERE guid='dupA'").fetchone()
conn.close()
t.ok("C9 the merged-away card is kept whole (with its phones), and a backup was taken first",
     row is not None and row["reason"] == "merge" and row["merged_into"] == "g0001"
     and json.loads(row["card"])["phone2"] == "0532222222"
     and any("before-merge-cards" in f for f in os.listdir(config.backup_dir())))
t.ok("C9 it is not offered for 'restore' (its history lives on the other card)",
     client.get("/api/cards/deleted").json()["cards"] == [] and post("/api/card/restore", {"guid": "dupA"}).status_code == 409)
plan = get("/api/plan", weeks=4)
t.ok("C9 the weeks are still computed after all this, and the merged card is on them once",
     plan.status_code == 200 and all(w["main"].count("g0001") <= 1 and "dupA" not in w["main"] + w["reserve_list"]
                                     for w in plan.json()["weeks"]))

# ── C10: the page ─────────────────────────────────────────────────────────────
page = client.get("/people")
t.ok("C10 the page is served: right-to-left, no code or style inside it, nothing from outside",
     page.status_code == 200 and 'dir="rtl"' in page.text and "<style" not in page.text and "onclick" not in page.text
     and "http://" not in page.text and "https://" not in page.text)
js = client.get("/static/people.js").text + client.get("/static/common.js").text
t.ok("C10 the page's code never builds markup from data", "innerHTML" not in js and "insertAdjacentHTML" not in js
     and "document.write" not in js)

t.done()
