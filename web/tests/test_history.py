# -*- coding: utf-8 -*-
"""The history screen's answers — every round that passed, who was in it, the old records
that belong to no round, and "when did so-and-so receive" — on a throw-away database with
invented people.

Run:  <python 3.12> web/tests/test_history.py
"""
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta

from _util import Checker, W0, person, wk

from web import event_service, history_service, service, store
from web.service import Refused

t = Checker("web history")
TMP = tempfile.mkdtemp(prefix="haluka_history_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")       # backups land in the temp folder too
SECRET_PHONE, SECRET_ID, SECRET_NOTE = "0501234567", "123456782", "הערה-פרטית-מאוד"
NOW = datetime(W0.year, W0.month, W0.day, 10, 0)                # Wednesday morning: nothing closes
SUN = wk(-2) - timedelta(days=3)                                # the Sunday before the Wednesday of week -2


def refusal(fn) -> str:
    try:
        fn()
    except Refused as e:
        return str(e)
    return ""


def names(people) -> list:
    return [p["name"] for p in people]


recs = [person(1, "שבועי", phone1=SECRET_PHONE, id_number=SECRET_ID, notes=SECRET_NOTE, holiday_support=1),
        person(2, "דו-שבועי", phone1=SECRET_PHONE), person(3, "חודשי", holiday_support=1),
        person(21, "חד-פעמי", 3, phone1=SECRET_PHONE), person(22, "חד-פעמי", 2),
        person(40, "", None, holiday_support=1), person(41, "שבועי", status="מושהה")]
path = os.path.join(TMP, "h", "haluka.db")
store.create(path)
conn = store.connect(path)
with store.tx(conn):
    for r in recs:
        cols = ["id", "guid"] + [c for c in store.RECIPIENT_COLUMNS if c in r]
        conn.execute(f"INSERT INTO recipients ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [r[c] for c in cols])

    def batch(guid, name, day, holiday="", created="2026-01-01 08:00:00"):
        conn.execute("INSERT INTO batches (guid, dist_name, dist_date, holiday, created_at, source, general_note, distributor) "
                     "VALUES (?,?,?,?,?, 'import', ?, ?)", (guid, name, day, holiday, created, SECRET_NOTE, SECRET_NOTE))

    n = [0]

    def row(card, day, batch_guid=None, received=1, holiday="", name=None):
        n[0] += 1
        conn.execute("INSERT INTO history (guid, recipient_guid, recipient_name, dist_date, received, holiday, batch_guid, "
                     "notes, distributor, area, what_dist, source) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'import')",
                     (f"h{n[0]}", card, name if name is not None else (f"שם ישן {card}" if card else ""), day, received,
                      holiday, batch_guid, SECRET_NOTE, SECRET_NOTE, SECRET_NOTE, SECRET_NOTE))

    # three rounds from the desktop program: a regular week, a holiday round, a bonus round
    batch("b-week", "חלוקה שבועית", wk(-3).isoformat())
    row("g0001", wk(-3).isoformat(), "b-week")
    row("g0002", wk(-3).isoformat(), "b-week", received=0)                 # recorded as "did not come"
    row("g0003", wk(-3).isoformat(), "b-week")
    row(None, wk(-3).isoformat(), "b-week", name="משפחה בלי כרטיס")        # the card is gone
    batch("b-feast", "", SUN.isoformat(), holiday="פסח")
    row("g0001", SUN.isoformat(), "b-feast", holiday="פסח")
    row("g0040", SUN.isoformat(), "b-feast", holiday="פסח")
    batch("b-bonus", "חלוקת ירקות", wk(-2).isoformat(), holiday="בונוס")
    row("g0021", wk(-2).isoformat(), "b-bonus", holiday="בונוס")
    batch("b-empty", "חלוקה בלי רישומים", wk(-6).isoformat())
    # old records that belong to no round
    row("g0001", wk(-9).isoformat())
    row("g0021", wk(-9).isoformat(), received=0)
    row("g0002", wk(-8).isoformat(), "b-that-is-not-there")                # names a round that does not exist
    row("g0003", "לא ידוע")                                               # a date that is not a date
    store.set_meta(conn, "closed_through", wk(-1).isoformat())
    store.set_setting(conn, "default_portions", 3)
    store.set_setting(conn, "default_reserve", 1)


def snapshot():
    return [tuple(r) for table in ("history", "batches", "weeks", "week_members", "recipients")
            for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


before = snapshot()

# ── H1: the rounds that passed, the latest first ──────────────────────────────
ov = history_service.overview(conn, NOW, 0, 30, path)
t.ok("H1 every round is listed, the latest first", [r["batch"] for r in ov["rounds"]] == ["b-bonus", "b-feast", "b-week", "b-empty"]
     and ov["total"] == 4 and ov["more"] is False, str([r["batch"] for r in ov["rounds"]]))
by = {r["batch"]: r for r in ov["rounds"]}
t.ok("H1 each round says how many received and how many were recorded as not coming",
     (by["b-week"]["received"], by["b-week"]["absent"]) == (3, 1) and (by["b-feast"]["received"], by["b-feast"]["absent"]) == (2, 0)
     and (by["b-empty"]["received"], by["b-empty"]["absent"]) == (0, 0))
t.ok("H1 a round carries its day, its name and its kind: regular / holiday / bonus",
     (by["b-week"]["kind"], by["b-week"]["label"], by["b-week"]["name"], by["b-week"]["day"]) == ("regular", "", "חלוקה שבועית", "יום רביעי")
     and (by["b-feast"]["kind"], by["b-feast"]["label"], by["b-feast"]["day"]) == ("holiday", "חלוקת פסח", "יום ראשון")
     and (by["b-bonus"]["kind"], by["b-bonus"]["label"]) == ("bonus", "חלוקת בונוס") and by["b-week"]["from_site"] is False)
page1, page2 = history_service.overview(conn, NOW, 0, 3, path), history_service.overview(conn, NOW, 3, 3, path)
t.ok("H1 a page is a part, and always says that there is more: together the pages are everything",
     len(page1["rounds"]) == 3 and page1["more"] is True and page1["total"] == 4
     and [r["batch"] for r in page1["rounds"] + page2["rounds"]] == [r["batch"] for r in ov["rounds"]] and page2["more"] is False)
t.ok("H1 a page size that makes no sense falls back to an ordinary page (never everything, never nothing)",
     len(history_service.overview(conn, NOW, "x", "y", path)["rounds"]) == 4
     and len(history_service.overview(conn, NOW, -5, 0, path)["rounds"]) == 1)

# ── H2: who was in a round ────────────────────────────────────────────────────
d = history_service.round_detail(conn, NOW, "b-week", path)
t.ok("H2 a round lists who received, by name, and apart from them who was recorded as not coming",
     names(d["people"]) == ["בדיקה 0001", "בדיקה 0003", "משפחה בלי כרטיס"] and names(d["absent_people"]) == ["בדיקה 0002"]
     and d["received"] == 3 and d["absent"] == 1 and d["reserve"] == [])
t.ok("H2 a row whose card is gone is shown under the name that was written, with no card to open",
     next(p for p in d["people"] if p["name"] == "משפחה בלי כרטיס")["guid"] == "")
t.ok("H2 a card is shown under its name of today, in the colour of what it is today",
     [(p["guid"], p["kind"], p["freq"]) for p in d["people"][:2]] == [("g0001", "regular", "שבועי"), ("g0003", "regular", "חודשי")]
     and [p["kind"] for p in history_service.round_detail(conn, NOW, "b-feast", path)["people"]] == ["regular", "other"])
with store.tx(conn):
    conn.execute("UPDATE recipients SET full_name='שם חדש 0003' WHERE guid='g0003'")
t.ok("H2 a card that was renamed since is found under its new name",
     "שם חדש 0003" in names(history_service.round_detail(conn, NOW, "b-week", path)["people"]))
with store.tx(conn):
    conn.execute("UPDATE recipients SET full_name='בדיקה 0003' WHERE guid='g0003'")
t.ok("H2 a round with no rows is shown empty, and a round that does not exist is refused in words",
     history_service.round_detail(conn, NOW, "b-empty", path)["people"] == []
     and "לא נמצאה" in refusal(lambda: history_service.round_detail(conn, NOW, "nope", path)))

# ── H3: the old records that belong to no round ───────────────────────────────
old = {o["key"]: o for o in ov["old"]}
t.ok("H3 rows that belong to no round are gathered by their date, the latest first — also a row that names a round that is not there",
     [o["key"] for o in ov["old"]] == [wk(-8).isoformat(), wk(-9).isoformat(), "לא ידוע"] and ov["old_rows"] == 4,
     str([o["key"] for o in ov["old"]]))
t.ok("H3 each date says how many received and how many did not come; a date that is not a date is kept, without a day",
     (old[wk(-9).isoformat()]["received"], old[wk(-9).isoformat()]["absent"]) == (1, 1)
     and old[wk(-9).isoformat()]["day"] == "יום רביעי" and (old["לא ידוע"]["date"], old["לא ידוע"]["day"]) == ("", ""))
day = history_service.old_day(conn, NOW, wk(-9).isoformat(), path)
t.ok("H3 one date opens to its names", names(day["people"]) == ["בדיקה 0001"] and names(day["absent_people"]) == ["בדיקה 0021"]
     and names(history_service.old_day(conn, NOW, "לא ידוע", path)["people"]) == ["בדיקה 0003"])
t.ok("H3 the rows of a round are not old records, and a date with none is refused",
     "אין רישומים" in refusal(lambda: history_service.old_day(conn, NOW, wk(-3).isoformat(), path))
     and "אין רישומים" in refusal(lambda: history_service.old_day(conn, NOW, "", path)))
t.ok("H3 nothing is lost between the two views: rounds' rows + old records = every row of the history",
     sum(r["received"] + r["absent"] for r in ov["rounds"]) + ov["old_rows"] == ov["rows"] == 11)

# ── H4: when did one person receive ───────────────────────────────────────────
p = history_service.person(conn, NOW, "g0001", path)
t.ok("H4 one person: every row, the latest first", [r["date"] for r in p["rows"]] == [SUN.isoformat(), wk(-3).isoformat(), wk(-9).isoformat()]
     and p["received"] == 3 and p["absent"] == 0 and p["last"] == SUN.isoformat())
t.ok("H4 each row says what kind of round it was, and which round",
     [(r["kind"], r["label"], r["batch"]) for r in p["rows"]]
     == [("holiday", "חלוקת פסח", "b-feast"), ("regular", "", "b-week"), ("regular", "", "")]
     and p["regular"] == 2 and p["extra"] == 1 and p["rows"][1]["name"] == "חלוקה שבועית")
p2 = history_service.person(conn, NOW, "g0002", path)
t.ok("H4 a row that says 'did not come' is shown as such and is not counted as receiving",
     [(r["date"], r["received"]) for r in p2["rows"]] == [(wk(-3).isoformat(), False), (wk(-8).isoformat(), True)]
     and (p2["received"], p2["absent"], p2["last"]) == (1, 1, wk(-8).isoformat()))
p3 = history_service.person(conn, NOW, "g0003", path)
t.ok("H4 a row with a date that is not a date is still shown (nothing is hidden) — last, with the text that was written",
     (p3["rows"][-1]["date"], p3["rows"][-1]["raw_date"]) == ("", "לא ידוע") and p3["rows"][0]["date"] == wk(-3).isoformat()
     and p3["received"] == 2 and p3["last"] == wk(-3).isoformat())
p41 = history_service.person(conn, NOW, "g0041", path)
t.ok("H4 a card that never received: no rows; a paused card says so; a card that does not exist is refused",
     p41["rows"] == [] and p41["received"] == 0 and p41["last"] == "" and p41["active"] is False and p41["status"] == "מושהה"
     and "לא נמצא" in refusal(lambda: history_service.person(conn, NOW, "g9999", path)))
t.ok("H4 the card's kind of today comes with it", (p["kind"], p["freq"], p["name"]) == ("regular", "שבועי", "בדיקה 0001")
     and history_service.person(conn, NOW, "g0040", path)["kind"] == "other")

# ── H5: names only, and reading writes nothing ────────────────────────────────
answers = [ov, d, day, p, p2, p3, history_service.round_detail(conn, NOW, "b-feast", path)]
blob = json.dumps(answers, ensure_ascii=False)
t.ok("H5 no phone, id number or note leaves with the history — not a card's and not a row's",
     SECRET_PHONE not in blob and SECRET_ID not in blob and SECRET_NOTE not in blob)
t.ok("H5 a person in a list carries a name, a card to open and a colour — nothing else",
     all(set(x) == {"guid", "name", "kind", "freq"} for x in d["people"] + d["absent_people"] + day["people"]))
t.ok("H5 reading the history changed nothing in it", snapshot() == before)

# ── H6: a week and a holiday event the site closes become rounds, with their reserve ──
g = event_service.save(conn, NOW, {"date": (W0 + timedelta(days=2)).isoformat(), "holiday": "*", "portions": 2,
                                   "reserve": 1, "criteria": {}}, path)["guid"]
later = datetime(2026, 11, 29, 9, 0)                                    # Sunday: the week and the Friday event are over
ov2 = history_service.overview(conn, later, 0, 30, path)
t.ok("H6 opening the history first closes what has passed: the week and the event are its two latest rounds",
     [(r["kind"], r["from_site"]) for r in ov2["rounds"][:2]] == [("holiday", True), ("regular", True)]
     and ov2["rounds"][0]["batch"] == store.event_batch_guid(g) and ov2["rounds"][1]["batch"] == store.week_batch_guid(W0)
     and ov2["total"] == 6, str([(r["batch"], r["kind"]) for r in ov2["rounds"][:2]]))
week = history_service.round_detail(conn, later, store.week_batch_guid(W0), path)
plan = [m["recipient_guid"] for m in conn.execute("SELECT recipient_guid FROM week_members WHERE week_wed=? AND role='main' ORDER BY position", (W0.isoformat(),))]
t.ok("H6 the closed week lists exactly who was on its list, and who waited on its reserve (they did not receive)",
     sorted(x["guid"] for x in week["people"]) == sorted(plan) and len(week["people"]) == 3 and len(week["reserve"]) == 1
     and week["reserve"][0]["guid"] not in plan and week["name"] == "חלוקת רביעי 25/11/2026")
feast = history_service.round_detail(conn, later, store.event_batch_guid(g), path)
t.ok("H6 the closed holiday event too: two received, one waited on the reserve",
     len(feast["people"]) == 2 and len(feast["reserve"]) == 1 and feast["label"] == "חלוקת חג" and feast["day"] == "יום שישי")
p = history_service.person(conn, later, feast["people"][0]["guid"], path)
t.ok("H6 ...and both are in the person's own history, the latest first",
     p["rows"][0]["batch"] == store.event_batch_guid(g) and p["rows"][0]["kind"] == "holiday")
conn.close()

shutil.rmtree(TMP, ignore_errors=True)
t.done()
