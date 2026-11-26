# -*- coding: utf-8 -*-
"""The site's store, the roll-forward ("a week that passed becomes history") and the import
guard — on throw-away databases with invented people.

Run:  <python 3.12> web/tests/test_store.py
"""
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta

from _util import Checker, ROOT, W0, guids, person, wk

from web import card_service, config, event_service, import_old, planner, service, store

t = Checker("web store")
TMP = tempfile.mkdtemp(prefix="haluka_store_")
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "data")       # backups land in the temp folder too


def at(day, hour=10):
    return datetime(day.year, day.month, day.day, hour, 0)


def fresh(name, recs, hist=(), closed=None, settings=None):
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
        for k, v in (settings or {}).items():
            store.set_setting(conn, k, v)
        if closed:
            store.set_meta(conn, "closed_through", closed.isoformat())
    return path, conn


# ── S1: which week is "now" ───────────────────────────────────────────────────
t.ok("S1 on Wednesday the current week is today", service.current_week(at(W0, 20)) == W0)
t.ok("S1 Sunday–Tuesday: the coming Wednesday", service.current_week(at(W0 - timedelta(days=3))) == W0)
t.ok("S1 Thursday 05:59 is still this week", service.current_week(datetime(2026, 11, 26, 5, 59)) == W0)
t.ok("S1 Thursday 06:00 moves to the next week", service.current_week(datetime(2026, 11, 26, 6, 0)) == wk(1))

# ── S2: nothing to close; a fresh database starts from this week ──────────────
recs = [person(1, "שבועי"), person(2, "דו-שבועי"), person(21, "חד-פעמי", 3), person(22, "חד-פעמי", 2)]
path, conn = fresh("s2", recs)
t.ok("S2 a fresh database closes nothing", service.roll_forward(conn, at(W0), path) == [])
t.ok("S2 ...and starts from the current week", store.closed_through(conn) == wk(-1)
     and service.first_open_week(conn, at(W0)) == W0)
ov = service.plan_overview(conn, at(W0), 3, path)
t.ok("S2 the overview starts today and reads nothing into the history",
     ov["current_week"] == W0.isoformat() and len(ov["weeks"]) == 3 and ov["closed_now"] == []
     and conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0)
conn.close()

# ── S3: a week that passed is written exactly as it was laid out ──────────────
settings = {"default_portions": 3, "default_reserve": 1}
path, conn = fresh("s3", recs, hist=[("g0001", wk(-1)), ("g0002", wk(-1))], closed=wk(-1), settings=settings)
before = service.plan_overview(conn, at(W0), 4, path)                    # Wednesday: nothing closes
week0 = service.week_detail(conn, at(W0), W0, path)
t.ok("S3 on the day itself nothing is written", before["closed_now"] == []
     and conn.execute("SELECT COUNT(*) FROM weeks").fetchone()[0] == 0)
after = service.plan_overview(conn, datetime(2026, 11, 26, 6, 30), 4, path)   # Thursday 06:30
t.ok("S3 on Thursday 06:00 the week closes by itself", after["closed_now"] == [W0.isoformat()]
     and after["current_week"] == wk(1).isoformat())
rows = [r["recipient_guid"] for r in conn.execute(
    "SELECT recipient_guid FROM history WHERE dist_date=? AND source='web' ORDER BY id", (W0.isoformat(),))]
t.ok("S3 everybody on the MAIN list is in the history as received", rows == guids(week0["main"]), f"{rows} vs {guids(week0['main'])}")
members = {r["recipient_guid"]: r["role"] for r in conn.execute("SELECT * FROM week_members WHERE week_wed=?", (W0.isoformat(),))}
t.ok("S3 the reserve is kept for the record but did not receive",
     [g for g, role in members.items() if role == "reserve"] == guids(week0["reserve_list"])
     and not (set(guids(week0["reserve_list"])) & set(rows)))
t.ok("S3 the lists that follow are the ones that were shown before the week closed",
     [w["main"] for w in after["weeks"][:3]] == [w["main"] for w in before["weeks"][1:4]])
again = service.plan_overview(conn, datetime(2026, 11, 26, 9, 0), 4, path)
t.ok("S3 asking again closes nothing twice", again["closed_now"] == []
     and conn.execute("SELECT COUNT(*) FROM history WHERE source='web'").fetchone()[0] == len(rows)
     and conn.execute("SELECT COUNT(*) FROM weeks").fetchone()[0] == 1)
t.ok("S3 a backup was taken before the automatic write",
     any(f.endswith("before-closing-weeks.db") for f in os.listdir(config.backup_dir())))
try:
    service.week_detail(conn, datetime(2026, 11, 26, 9, 0), W0, path)
    passed_refused = False
except LookupError:
    passed_refused = True
t.ok("S3 a week that passed is no longer offered as a coming week", passed_refused)
conn.close()

# ── S4: several weeks passed while the site was closed ────────────────────────
path, conn = fresh("s4", recs, hist=[("g0001", wk(-1)), ("g0002", wk(-1))], closed=wk(-1), settings=settings)
straight = planner.plan_weeks(store.load_recipients(conn), store.load_received(conn), start=W0, weeks=6,
                              horizon=W0, weights=planner.need_weights({}), cooldown_weeks=4, portions=3, reserve=1)
ov = service.plan_overview(conn, at(wk(3)), 3, path)                     # opened three weeks later
t.ok("S4 the three weeks that passed are closed, oldest first",
     ov["closed_now"] == [W0.isoformat(), wk(1).isoformat(), wk(2).isoformat()] and ov["current_week"] == wk(3).isoformat())
hist_by_week = {}
for r in conn.execute("SELECT recipient_guid, dist_date FROM history WHERE source='web' ORDER BY id"):
    hist_by_week.setdefault(r["dist_date"], []).append(r["recipient_guid"])
t.ok("S4 each closed week holds the list the planner laid out for it",
     [hist_by_week.get(w["date"].isoformat(), []) for w in straight[:3]] == [guids(w["main"]) for w in straight[:3]])
t.ok("S4 the coming weeks continue the same chain", [w["main"] for w in ov["weeks"]] == [guids(w["main"]) for w in straight[3:6]])
conn.close()

# ── S5: closing a week is all-or-nothing and never doubles ────────────────────
path, conn = fresh("s5", recs, closed=wk(-1), settings=settings)
week = planner.plan_weeks(store.load_recipients(conn), [], start=W0, weeks=1, horizon=W0,
                          weights=planner.need_weights({}), cooldown_weeks=4, portions=3, reserve=1)[0]
with store.tx(conn):
    first = store.close_week(conn, week, at(W0))
with store.tx(conn):
    second = store.close_week(conn, week, at(W0))
t.ok("S5 the same week cannot be closed twice", first and not second
     and conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == len(week["main"]))
try:
    with store.tx(conn):
        conn.execute("INSERT INTO settings (key, value) VALUES ('x', '1')")
        raise RuntimeError("boom")
except RuntimeError:
    pass
t.ok("S5 a failed write leaves nothing behind", conn.execute("SELECT COUNT(*) FROM settings WHERE key='x'").fetchone()[0] == 0)
conn.close()

# ── S6: backup ────────────────────────────────────────────────────────────────
b = store.backup(path, os.path.join(TMP, "bk"), "manual check", at(W0))
c = sqlite3.connect(b)
t.ok("S6 a backup is a full, readable copy", c.execute("SELECT COUNT(*) FROM recipients").fetchone()[0] == len(recs))
c.close()
b2 = store.backup(path, os.path.join(TMP, "bk"), "manual check", at(W0))
t.ok("S6 a second backup in the same second does not overwrite the first", b2 != b and os.path.exists(b) and os.path.exists(b2))
t.ok("S6 no database, no backup, no error", store.backup(os.path.join(TMP, "none.db"), os.path.join(TMP, "bk"), "x") == "")

# ── S7: the names leave the store only as far as the screen needs ─────────────
path, conn = fresh("s7", recs + [person(30, "חד-פעמי", None), person(31, ""), person(32, "שבועי", status="מושהה")])
ppl = service.people(conn)
t.ok("S7 the search list: who takes part and who does not, with a reason",
     {p["guid"] for p in ppl["participants"]} == {"g0001", "g0002", "g0021", "g0022"}
     and {p["guid"] for p in ppl["others"]} == {"g0030", "g0031", "g0032"} and all(p["why"] for p in ppl["others"]))
t.ok("S7 only the name and the kind leave the store — no phone, no address",
     all(set(p) <= {"guid", "name", "kind", "freq", "why", "active"} for p in ppl["participants"] + ppl["others"]))
conn.close()

# ── S8: personal data may not land in a folder git would publish ──────────────
os.environ.pop("HALUKA_WEB_SKIP_GIT_GUARD", None)
repo = os.path.join(TMP, "repo")
os.makedirs(os.path.join(repo, "open"))
os.makedirs(os.path.join(repo, "private"))
have_git = subprocess.run(["git", "init", "-q", repo], capture_output=True).returncode == 0
if have_git:
    with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("private/\n")
    try:
        import_old.assert_not_publishable(os.path.join(repo, "open"))
        refused = False
    except import_old.ImportRefused:
        refused = True
    t.ok("S8 a data folder inside a repository that is NOT ignored is refused", refused)
    try:
        import_old.assert_not_publishable(os.path.join(repo, "private"))
        allowed = True
    except import_old.ImportRefused:
        allowed = False
    t.ok("S8 an ignored folder is accepted", allowed)
    ignored = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", os.path.join(ROOT, "web", "data", "haluka.db")],
                             capture_output=True).returncode == 0
    t.ok("S8 the site's real data folder (web/data) is ignored by this repository", ignored)
else:
    print("  --  S8 skipped: git is not available here")
import_old.assert_not_publishable(os.path.join(TMP, "plain"))
t.ok("S8 a folder outside any repository is accepted", True)


# ══ stage 2: what the manager sets by hand, numbers for a week, print and Excel ══
# three weekly, one bi-weekly (received last week: his turn is NEXT week), four one-timers,
# a card that takes no part, and a paused card. 5 portions, 1 in reserve.
recs2 = ([person(n, "שבועי", phone1=f"05011100{n:02d}") for n in (1, 2, 3)]
         + [person(4, "דו-שבועי", phone1="0501110004", phone2="0521110004")]
         + [person(n, "חד-פעמי", 3, per_soul=str(n), phone1=f"05011100{n:02d}") for n in (21, 22, 23, 24)]
         + [person(40, "", 1), person(41, "שבועי", status="מושהה")])
hist2 = [(f"g{n:04d}", wk(-1)) for n in (1, 2, 3, 4)]
settings2 = {"default_portions": 5, "default_reserve": 1}
NOW = at(W0)
THURSDAY = datetime(2026, 11, 26, 6, 30)


def lists(ov):
    return [(w["main"], w["reserve_list"]) for w in ov["weeks"]]


def refusal(fn) -> str:
    try:
        fn()
    except service.Refused as e:
        return str(e) or "refused"
    return ""


# ── S9: a change by hand is kept, and every list follows it ───────────────────
path, conn = fresh("s9", recs2, hist=hist2, closed=wk(-1), settings=settings2)
base = service.plan_overview(conn, NOW, 3, path)
t.ok("S9 before any change: nothing is marked as set by hand",
     [w["manual_count"] for w in base["weeks"]] == [0, 0, 0] and "g0004" not in base["weeks"][0]["main"])
service.set_manual(conn, NOW, W0, "g0004", "add", path)
service.set_manual(conn, NOW, W0, "g0001", "remove", path)
service.set_manual(conn, NOW, wk(1), "g0002", "reserve", path)
conn.close()
conn = store.connect(path)                                             # a new connection: it is on the disk
t.ok("S9 the three changes are saved, each for its own week",
     store.load_manual(conn) == {W0: {"g0004": "add", "g0001": "remove"}, wk(1): {"g0002": "reserve"}})
ov = service.plan_overview(conn, NOW, 3, path)
t.ok("S9 the lists follow: added is on the list, removed is on none, reserved is first on the reserve",
     "g0004" in ov["weeks"][0]["main"] and "g0001" not in ov["weeks"][0]["main"] + ov["weeks"][0]["reserve_list"]
     and ov["weeks"][1]["reserve_list"][0] == "g0002" and "g0002" not in ov["weeks"][1]["main"])
t.ok("S9 each week says how many changes were set by hand in it", [w["manual_count"] for w in ov["weeks"]] == [2, 1, 0])
d = service.week_detail(conn, NOW, W0, path)
marked = {e["guid"]: e["manual"] for e in d["main"] + d["reserve_list"] + d["out"] if e.get("manual")}
t.ok("S9 the screen is told who was set by hand, and how", marked == {"g0004": "add", "g0001": "remove"}
     and next(e for e in d["out"] if e["guid"] == "g0001")["group"] == planner.OUT_REMOVED)
service.set_manual(conn, NOW, W0, "g0004", "reserve", path)
t.ok("S9 a second change for the same person in the same week replaces the first",
     store.load_manual(conn)[W0] == {"g0004": "reserve", "g0001": "remove"}
     and conn.execute("SELECT COUNT(*) FROM week_manual").fetchone()[0] == 3)
service.set_manual(conn, NOW, W0, "g0040", "add", path)
t.ok("S9 a card that takes no part in the lists can be added by hand to one week",
     "g0040" in service.plan_overview(conn, NOW, 2, path)["weeks"][0]["main"]
     and "g0040" not in service.plan_overview(conn, NOW, 2, path)["weeks"][1]["main"])
for wed, g in ((W0, "g0004"), (W0, "g0001"), (W0, "g0040"), (wk(1), "g0002")):
    service.set_manual(conn, NOW, wed, g, "clear", path)
t.ok("S9 'clear' forgets the change: nothing is kept, and the lists are exactly as before",
     store.load_manual(conn) == {} and service.plan_overview(conn, NOW, 3, path) == base)

# ── S10: the number of portions / reserve for one week ────────────────────────
service.set_numbers(conn, NOW, wk(1), 3, 0, path)
ov = service.plan_overview(conn, NOW, 3, path)
w1 = ov["weeks"][1]
t.ok("S10 3 portions and no reserve for next week: that week only",
     (w1["portions"], w1["reserve"], w1["numbers_set"], len(w1["main"]), w1["reserve_list"]) == (3, 0, True, 3, [])
     and [(w["portions"], w["reserve"], w["numbers_set"]) for w in (ov["weeks"][0], ov["weeks"][2])] == [(5, 1, False)] * 2)
t.ok("S10 ...and it is saved", store.load_numbers(conn) == {wk(1): {"portions": 3, "reserve": 0}})
service.set_numbers(conn, NOW, wk(1), 0, None, path)
w1 = service.plan_overview(conn, NOW, 3, path)["weeks"][1]
t.ok("S10 one number alone: the other stays the ordinary one; 0 portions = an empty list",
     (w1["portions"], w1["reserve"], w1["main"]) == (0, 1, []))
service.set_numbers(conn, NOW, wk(1), None, None, path)
t.ok("S10 back to the ordinary numbers: nothing is kept, and the lists are exactly as before",
     store.load_numbers(conn) == {} and service.plan_overview(conn, NOW, 3, path) == base)
conn.close()

# ── S11: a week that closes by itself closes as it was set by hand ────────────
path, conn = fresh("s11", recs2, hist=hist2, closed=wk(-1), settings=settings2)
service.set_manual(conn, NOW, W0, "g0004", "add", path)                 # the bi-weekly, a week early
service.set_manual(conn, NOW, W0, "g0001", "remove", path)
service.set_manual(conn, NOW, W0, "g0002", "reserve", path)
service.set_numbers(conn, NOW, W0, 4, 2, path)
shown = service.week_detail(conn, NOW, W0, path)
after = service.plan_overview(conn, THURSDAY, 2, path)
rows = [r["recipient_guid"] for r in conn.execute(
    "SELECT recipient_guid FROM history WHERE dist_date=? AND source='web' ORDER BY id", (W0.isoformat(),))]
t.ok("S11 on Thursday the week is written to the history exactly as it was on the screen",
     after["closed_now"] == [W0.isoformat()] and rows == guids(shown["main"]) and len(rows) == 4, f"{rows} vs {guids(shown['main'])}")
t.ok("S11 added by hand received; removed and moved to the reserve did not",
     "g0004" in rows and "g0001" not in rows and "g0002" not in rows)
members = {r["recipient_guid"]: r["role"] for r in conn.execute("SELECT * FROM week_members WHERE week_wed=?", (W0.isoformat(),))}
week_row = conn.execute("SELECT portions, reserve, main_count FROM weeks WHERE week_wed=?", (W0.isoformat(),)).fetchone()
t.ok("S11 the record of the week: the reserve as it was, the removed one not in it, the week's own numbers",
     members.get("g0002") == "reserve" and "g0001" not in members and members.get("g0004") == "main"
     and tuple(week_row) == (4, 2, 4))
nxt, then = after["weeks"][0], after["weeks"][1]
t.ok("S11 the next week: removed and reserved are on the list (they did not receive); the one added has his turn counted from the week he got",
     "g0001" in nxt["main"] and "g0002" in nxt["main"] and "g0004" not in nxt["main"] and "g0004" in then["main"])
t.ok("S11 a week that has passed can no longer be changed",
     "עבר" in refusal(lambda: service.set_manual(conn, THURSDAY, W0, "g0003", "remove", path))
     and "עבר" in refusal(lambda: service.set_numbers(conn, THURSDAY, W0, 9, 9, path)))
conn.close()

# ── S12: "changed since it was printed" ───────────────────────────────────────
path, conn = fresh("s12", recs2, hist=hist2, closed=wk(-1), settings=settings2)
before = service.plan_overview(conn, NOW, 3, path)
t.ok("S12 a week that was never printed carries no note",
     service.week_detail(conn, NOW, W0, path)["print"] is None and all(w["print"] is None for w in before["weeks"]))
n = service.mark_printed(conn, NOW, W0, 2, "print", path)
ov = service.plan_overview(conn, NOW, 3, path)
d = service.week_detail(conn, NOW, W0, path)
t.ok("S12 printing two weeks is remembered for those two, with the time",
     n == 2 and d["print"]["printed_at"] == "2026-11-25 10:00" and d["print"]["how"] == "print"
     and ov["weeks"][1]["print"] is not None and ov["weeks"][2]["print"] is None)
t.ok("S12 right after printing nothing has changed", d["print"]["changed"] is False
     and (d["print"]["added"], d["print"]["removed"], d["print"]["added_names"], d["print"]["removed_names"]) == (0, 0, [], []))
t.ok("S12 printing holds nothing in place: the lists are the same lists", lists(ov) == lists(before))
service.set_manual(conn, NOW, W0, "g0004", "add", path)
d = service.week_detail(conn, NOW, W0, path)
pushed = [g for g in before["weeks"][0]["main"] if g not in guids(d["main"])]
t.ok("S12 after a change the week says who was added and who went out, by name",
     d["print"]["changed"] is True and d["print"]["added_names"] == ["בדיקה 0004"] and len(pushed) == 1
     and d["print"]["removed_names"] == [f"בדיקה {pushed[0][1:]}"] and (d["print"]["added"], d["print"]["removed"]) == (1, 1),
     str(d["print"]))
ov = service.plan_overview(conn, NOW, 3, path)
t.ok("S12 the strip of weeks gets the numbers only (no names there)",
     ov["weeks"][0]["print"]["changed"] is True and (ov["weeks"][0]["print"]["added"], ov["weeks"][0]["print"]["removed"]) == (1, 1)
     and "added_names" not in ov["weeks"][0]["print"])
d1 = service.week_detail(conn, NOW, wk(1), path)
t.ok("S12 a later printed week that moved because of it is marked too (his turn there is gone)",
     d1["print"]["changed"] is True and d1["print"]["removed_names"] == ["בדיקה 0004"] and len(d1["print"]["added_names"]) == 1)
service.set_manual(conn, NOW, W0, "g0004", "clear", path)
t.ok("S12 back to the list that is on the paper: the note is quiet again",
     service.week_detail(conn, NOW, W0, path)["print"]["changed"] is False
     and service.week_detail(conn, NOW, wk(1), path)["print"]["changed"] is False)
with store.tx(conn):
    conn.execute("UPDATE recipients SET status='מושהה' WHERE guid='g0002'")
d = service.week_detail(conn, NOW, W0, path)
t.ok("S12 not only hand changes: a card that was paused after the printing is named as gone",
     d["print"]["changed"] is True and d["print"]["removed_names"] == ["בדיקה 0002"])
later = datetime(2026, 11, 25, 15, 45)
service.mark_printed(conn, later, W0, 1, "excel", path)
d = service.week_detail(conn, later, W0, path)
t.ok("S12 printing / exporting again starts the comparison afresh from the new paper",
     d["print"]["changed"] is False and d["print"]["how"] == "excel" and d["print"]["printed_at"] == "2026-11-25 15:45"
     and service.week_detail(conn, later, wk(1), path)["print"]["how"] == "print")
with store.tx(conn):
    conn.execute("DELETE FROM recipients WHERE guid='g0003'")
d = service.week_detail(conn, later, W0, path)
t.ok("S12 a card that was deleted since is said so, not shown as a blank", d["print"]["removed_names"] == ["כרטיס שנמחק"])
conn.close()

# ── S13: what cannot be done is refused in words, and nothing is written ──────
path, conn = fresh("s13", recs2, hist=hist2, closed=wk(-1), settings=settings2)
day_after = W0 + timedelta(days=1)
said = {
    "a week that has passed": refusal(lambda: service.set_manual(conn, NOW, wk(-1), "g0001", "remove", path)),
    "a day that is not a Wednesday": refusal(lambda: service.set_manual(conn, NOW, day_after, "g0001", "remove", path)),
    "a paused card onto the list": refusal(lambda: service.set_manual(conn, NOW, W0, "g0041", "add", path)),
    "a paused card onto the reserve": refusal(lambda: service.set_manual(conn, NOW, W0, "g0041", "reserve", path)),
    "a card that does not exist": refusal(lambda: service.set_manual(conn, NOW, W0, "g9999", "add", path)),
    "an action that does not exist": refusal(lambda: service.set_manual(conn, NOW, W0, "g0001", "delete", path)),
    "a negative number of portions": refusal(lambda: service.set_numbers(conn, NOW, W0, -1, 1, path)),
    "a number beyond the ceiling": refusal(lambda: service.set_numbers(conn, NOW, W0, service.MAX_PORTIONS + 1, 1, path)),
    "half a portion": refusal(lambda: service.set_numbers(conn, NOW, W0, 2.5, 1, path)),
    "a number that is text": refusal(lambda: service.set_numbers(conn, NOW, W0, "7", 1, path)),
    "true instead of a number": refusal(lambda: service.set_numbers(conn, NOW, W0, True, 1, path)),
    "numbers for a week that has passed": refusal(lambda: service.set_numbers(conn, NOW, wk(-1), 5, 1, path)),
    "printing from a week that has passed": refusal(lambda: service.mark_printed(conn, NOW, wk(-1), 1, "print", path)),
    "printing from a day that is not a Wednesday": refusal(lambda: service.mark_printed(conn, NOW, day_after, 1, "print", path)),
    "an unknown way of producing": refusal(lambda: service.mark_printed(conn, NOW, W0, 1, "fax", path)),
    "the paper list of a week that has passed": refusal(lambda: service.print_weeks(conn, NOW, wk(-1), 1, path)),
}
for what, words in said.items():
    t.ok(f"S13 refused: {what}", bool(words), "it was accepted")
t.ok("S13 the refusals are sentences the manager can read (Hebrew)",
     "עבר" in said["a week that has passed"] and "מושהה" in said["a paused card onto the list"]
     and "לא נמצא" in said["a card that does not exist"] and "מספר שלם" in said["half a portion"])
t.ok("S13 after all the refusals nothing was written",
     store.load_manual(conn) == {} and store.load_numbers(conn) == {} and store.load_prints(conn) == {})
service.set_manual(conn, NOW, W0, "g0041", "remove", path)
t.ok("S13 taking a paused card OFF a week is harmless and allowed (it is on no list anyway)",
     store.load_manual(conn) == {W0: {"g0041": "remove"}}
     and all("g0041" not in w["main"] + w["reserve_list"] for w in service.plan_overview(conn, NOW, 2, path)["weeks"]))
service.set_manual(conn, NOW, W0, "g0041", "clear", path)

# ── S14: the lists for paper / Excel ──────────────────────────────────────────
service.set_manual(conn, NOW, W0, "g0004", "add", path)
shown = service.week_detail(conn, NOW, W0, path)
paper = service.print_weeks(conn, NOW, W0, 2, path)
p0 = paper[0]
t.ok("S14 a range of two weeks gives two lists, in order", [p["date"] for p in paper] == [W0.isoformat(), wk(1).isoformat()])
t.ok("S14 on paper the list is by name, numbered from 1, the same people as on the screen",
     [r["name"] for r in p0["main"]] == sorted(e["name"] for e in shown["main"])
     and [r["n"] for r in p0["main"]] == list(range(1, len(shown["main"]) + 1)))
t.ok("S14 the reserve keeps its own order (who comes in first)",
     [r["name"] for r in p0["reserve_list"]] == [e["name"] for e in shown["reserve_list"]] and len(p0["reserve_list"]) == 1)
row4 = next(r for r in p0["main"] if r["name"] == "בדיקה 0004")
t.ok("S14 each row: all the phones, the souls, the kind, and whether it was set by hand",
     row4["phones"] == "0501110004 · 0521110004" and row4["souls"] == 4 and row4["kind"] == "קבוע"
     and row4["freq"] == "דו-שבועי" and row4["manual"] is True and row4["last"] == wk(-1).strftime("%d/%m/%Y"))
t.ok("S14 asking for the paper list writes nothing (only 'mark printed' remembers)", store.load_prints(conn) == {})
conn.close()

# ── S15: a database from stage 1 gets the new tables by itself ────────────────
path, conn = fresh("s15", recs2, hist=hist2, closed=wk(-1), settings=settings2)
conn.executescript("DROP TABLE week_manual; DROP TABLE week_numbers; DROP TABLE week_prints;")
conn.close()
store.ensure_schema(path)
conn = store.connect(path)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
t.ok("S15 the three new tables are added; cards and history are untouched",
     {"week_manual", "week_numbers", "week_prints"} <= tables
     and conn.execute("SELECT COUNT(*) FROM recipients").fetchone()[0] == len(recs2)
     and conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == len(hist2))
service.set_manual(conn, NOW, W0, "g0001", "remove", path)
t.ok("S15 ...and a change by hand can be saved in it", store.load_manual(conn) == {W0: {"g0001": "remove"}})
conn.close()


# ══ stage 4: holiday events ════════════════════════════════════════════════════
# two weekly and a monthly marked for the holidays, a weekly that is not; one-timers marked
# and not; a card that takes no part in the weeks but is marked; a paused marked card.
recs3 = ([person(n, "שבועי", holiday_support=1, phone1=f"05011200{n:02d}", income="3000") for n in (1, 2)]
         + [person(3, "חודשי", holiday_support=1, income="3000"), person(4, "שבועי", income="3000")]
         + [person(21, "חד-פעמי", 3, holiday_support=1, income="2000", phone1="0501120021"),
            person(22, "חד-פעמי", 3, income="2000"), person(23, "חד-פעמי", 2, holiday_support=1, income="")]
         + [person(40, "", None, holiday_support=1, income="1000"),
            person(41, "שבועי", holiday_support=1, status="מושהה")])
hist3 = [(g, wk(-1)) for g in ("g0001", "g0002", "g0003", "g0004")]
settings3 = {"default_portions": 4, "default_reserve": 1}
FRI, NEXT_SUN = W0 + timedelta(days=2), wk(1) - timedelta(days=3)
MARKED = {"g0001", "g0002", "g0003", "g0021", "g0023", "g0040"}


def new_event(conn, path, day, holiday="*", portions=10, reserve=2, criteria=None, now=None):
    return event_service.save(conn, now or NOW, {"date": day.isoformat(), "holiday": holiday, "portions": portions,
                                                 "reserve": reserve, "criteria": criteria or {}}, path)["guid"]


# ── S16: an event is set up, changed and taken away ───────────────────────────
path, conn = fresh("s16", recs3, hist=hist3, closed=wk(-1), settings=settings3)
before = service.plan_overview(conn, NOW, 4, path)
g = new_event(conn, path, FRI)
conn.close()
conn = store.connect(path)                                             # a new connection: it is on the disk
ev0 = store.load_events(conn)[0]
t.ok("S16 a new event is saved: its day, holiday and numbers",
     (ev0["guid"], ev0["date"], ev0["holiday"], ev0["portions"], ev0["reserve"], ev0["criteria"]) == (g, FRI, "*", 10, 2, {})
     and ev0["closed_at"] is None)
ov = event_service.overview(conn, NOW, path)
t.ok("S16 the holiday screen: one event ahead, in numbers; everybody marked receives",
     len(ov["open"]) == 1 and ov["open"][0]["main_count"] == 6 and ov["open"][0]["marked"] == 6
     and ov["open"][0]["name"] == "חלוקת חג" and ov["open"][0]["day"] == "יום שישי" and ov["past"] == [])
event_service.save(conn, NOW, {"guid": g, "date": NEXT_SUN.isoformat(), "holiday": "פסח", "portions": 3, "reserve": 1,
                               "criteria": {"income": {"min": None, "max": 2500}}}, path)
ev0 = store.load_events(conn)[0]
t.ok("S16 a change replaces the event's settings (it stays the same event)",
     len(store.load_events(conn)) == 1 and (ev0["date"], ev0["holiday"], ev0["portions"], ev0["reserve"]) == (NEXT_SUN, "פסח", 3, 1)
     and ev0["criteria"] == {"income": {"min": None, "max": 2500.0}})
event_service.remove(conn, NOW, g, path)
t.ok("S16 an event that has not happened can be taken away, and the weeks are exactly as before it",
     store.load_events(conn) == [] and service.plan_overview(conn, NOW, 4, path) == before)
bad_events = {
    "a day that has passed": {"date": (W0 - timedelta(days=1)).isoformat(), "holiday": "*", "portions": 5},
    "a day too far ahead": {"date": (W0 + timedelta(days=900)).isoformat(), "holiday": "*", "portions": 5},
    "a date that is not a date": {"date": "soon", "holiday": "*", "portions": 5},
    "a holiday that does not exist": {"date": FRI.isoformat(), "holiday": "יום העצמאות", "portions": 5},
    "no holiday": {"date": FRI.isoformat(), "holiday": "", "portions": 5},
    "a negative number of portions": {"date": FRI.isoformat(), "holiday": "*", "portions": -1},
    "portions that are text": {"date": FRI.isoformat(), "holiday": "*", "portions": "5"},
    "a filter field that does not exist": {"date": FRI.isoformat(), "holiday": "*", "portions": 5, "criteria": {"souls": {"min": 3}}},
    "'from' above 'up to'": {"date": FRI.isoformat(), "holiday": "*", "portions": 5, "criteria": {"income": {"min": 9, "max": 3}}},
    "a threshold that is not a number": {"date": FRI.isoformat(), "holiday": "*", "portions": 5, "criteria": {"income": {"max": "הרבה"}}},
    "a change to an event that does not exist": {"guid": "nope", "date": FRI.isoformat(), "holiday": "*", "portions": 5},
}
said = {what: refusal(lambda d=d: event_service.save(conn, NOW, d, path)) for what, d in bad_events.items()}
for what, words in said.items():
    t.ok(f"S16 refused: {what}", bool(words), "it was accepted")
t.ok("S16 the refusals are sentences, and nothing was written",
     "עבר" in said["a day that has passed"] and "לאיזה חג" in said["no holiday"] and store.load_events(conn) == [])
t.ok("S16 today itself is still allowed (the day is over only at 06:00 the next morning)",
     bool(new_event(conn, path, W0, now=datetime(2026, 11, 26, 5, 30))) and store.load_events(conn)[0]["date"] == W0)
conn.close()

# ── S17: one event in full — the reasons, names only ──────────────────────────
path, conn = fresh("s17", recs3, hist=hist3, closed=wk(-1), settings=settings3)
g = new_event(conn, path, FRI, criteria={"income": {"min": None, "max": 2500}})
d = event_service.detail(conn, NOW, g, path)
where3 = {e["guid"]: "main" for e in d["main"]}
where3.update({e["guid"]: e["group"] for e in d["out"]})
t.ok("S17 on the list: the marked cards that pass the filter",
     {x for x, v in where3.items() if v == "main"} == {"g0021", "g0040"} and (d["marked"], d["eligible"], d["missing"]) == (6, 2, 1))
t.ok("S17 outside: who is missing a value is set apart from who is outside the filter",
     where3["g0023"] == planner.OUT_EV_MISSING and where3["g0001"] == where3["g0003"] == planner.OUT_EV_FILTER)
t.ok("S17 a card that is not marked is not listed at all, only counted", "g0004" not in where3 and d["unmarked"] == 2)
allowed3 = {"guid", "name", "kind", "freq", "role", "why", "group", "manual"}
t.ok("S17 about a person the screen gets the name, the kind and the reason — nothing else",
     all(set(e) <= allowed3 for e in d["main"] + d["reserve_list"] + d["out"]) and "0501120021" not in str(d)
     and "2000" not in str(d["main"]) and "3000" not in str(d["out"]))
t.ok("S17 the same event in the overview, in numbers only",
     event_service.overview(conn, NOW, path)["open"][0]["main_count"] == 2
     and "main" not in event_service.overview(conn, NOW, path)["open"][0])
strip = service.plan_overview(conn, NOW, 3, path)
t.ok("S17 the weeks screen is told where the event sits among the weeks",
     [(e["guid"], e["date"], e["name"]) for e in strip["events"]] == [(g, FRI.isoformat(), "חלוקת חג")]
     and set(strip["events"][0]["main"]) == {"g0021", "g0040"})
t.ok("S17 an event that does not exist is refused in words", "לא נמצאה" in refusal(lambda: event_service.detail(conn, NOW, "nope", path)))
conn.close()

# ── S18: an event whose day has passed becomes history, as it was shown ───────
path, conn = fresh("s18", recs3, hist=hist3, closed=wk(-1), settings=settings3)
weeks_plain = service.plan_overview(conn, NOW, 4, path)["weeks"]
g = new_event(conn, path, NEXT_SUN, portions=10, reserve=1)             # Sunday of NEXT week
shown = event_service.detail(conn, NOW, g, path)
weeks_shown = service.plan_overview(conn, NOW, 4, path)["weeks"]
t.ok("S18 an event that is ahead changes no week: the weeks are exactly as before it was set up",
     weeks_shown == weeks_plain and "g0021" in guids(shown["main"]))
ov = service.plan_overview(conn, datetime(2026, 11, 26, 6, 30), 3, path)   # Thursday: the week closes, the event does not
t.ok("S18 Thursday 06:30: this week's list closed, the event of next Sunday is still ahead",
     ov["closed_now"] == [W0.isoformat()] and ov["closed_events_now"] == [] and len(store.load_events(conn)) == 1)
ov = service.plan_overview(conn, datetime(2026, 11, 29, 23, 0), 3, path)   # Sunday night: the day is not over
t.ok("S18 on the event's own day, and until 06:00 the next morning, nothing is written",
     ov["closed_events_now"] == [] and len(store.load_events(conn)) == 1
     and conn.execute("SELECT COUNT(*) FROM history WHERE holiday<>''").fetchone()[0] == 0)
monday = datetime(2026, 11, 30, 6, 0)
ov = service.plan_overview(conn, monday, 3, path)
rows = [r["recipient_guid"] for r in conn.execute(
    "SELECT recipient_guid FROM history WHERE dist_date=? AND holiday='*' AND received=1 ORDER BY id", (NEXT_SUN.isoformat(),))]
t.ok("S18 Monday 06:00: the event closes by itself — everybody on its list is in the history, in a holiday round",
     ov["closed_events_now"] == ["חלוקת חג " + NEXT_SUN.strftime("%d/%m/%Y")] and ov["closed_now"] == []
     and rows == guids(shown["main"]) and len(rows) == 6, f"{rows} vs {guids(shown['main'])}")
batch = conn.execute("SELECT * FROM batches WHERE holiday='*'").fetchone()
ev_row = conn.execute("SELECT * FROM events WHERE guid=?", (g,)).fetchone()
t.ok("S18 the round is recorded with its name, its code and its numbers; the event is marked as passed",
     batch["dist_name"] == "חלוקת חג " + NEXT_SUN.strftime("%d/%m/%Y") and batch["recipient_count"] == 6
     and ev_row["closed_at"] and ev_row["main_count"] == 6 and ev_row["batch_guid"] == batch["guid"]
     and store.load_events(conn) == [])
t.ok("S18 the weeks after are exactly the lists that were shown before: a holiday portion in the history is not counted in them",
     ov["weeks"][0]["date"] == wk(1).isoformat() and ov["weeks"][0]["main"] == weeks_shown[1]["main"]
     and ov["weeks"][1]["main"] == weeks_shown[2]["main"])
again = service.plan_overview(conn, datetime(2026, 11, 30, 9, 0), 3, path)
t.ok("S18 asking again writes nothing twice", again["closed_events_now"] == []
     and conn.execute("SELECT COUNT(*) FROM history WHERE holiday='*'").fetchone()[0] == 6
     and conn.execute("SELECT COUNT(*) FROM batches WHERE holiday='*'").fetchone()[0] == 1)
closed = event_service.detail(conn, monday, g, path)
t.ok("S18 a passed event is shown as it was written — and can no longer be changed, set by hand or deleted",
     closed["closed"] is True and guids(closed["main"]) == rows and closed["name"] == "חלוקת חג"
     and "עברה" in refusal(lambda: event_service.save(conn, monday, {"guid": g, "date": "2026-12-06", "holiday": "*", "portions": 3}, path))
     and "עברה" in refusal(lambda: event_service.set_manual(conn, monday, g, "g0004", "add", path))
     and "עברה" in refusal(lambda: event_service.remove(conn, monday, g, path)))
t.ok("S18 ...and it is listed among the events that passed",
     [e["guid"] for e in event_service.overview(conn, monday, path)["past"]] == [g]
     and event_service.overview(conn, monday, path)["past"][0]["main_count"] == 6)
t.ok("S18 a backup was taken before the automatic write",
     sum(1 for f in os.listdir(config.backup_dir()) if f.endswith("before-closing-weeks.db")) >= 2)
conn.close()

# ── S19: weeks and events that passed while the site was closed close in date order ──
path, conn = fresh("s19", recs3, hist=hist3, closed=wk(-1), settings=settings3)
g_sun = new_event(conn, path, NEXT_SUN, portions=2, reserve=1)          # before the Wednesday of week 1
g_wed = new_event(conn, path, wk(1), holiday="פסח", portions=10)       # ON the Wednesday of week 1
g_far = new_event(conn, path, wk(5) + timedelta(days=1), portions=10)   # still ahead later on
ctx0 = service._context(conn, NOW)
straight = planner.plan_timeline(ctx0["recipients"], ctx0["received"], start=W0, weeks=5, horizon=W0,
                                 weights=ctx0["weights"], cooldown_weeks=ctx0["cooldown"], portions=4, reserve=1,
                                 events=ctx0["events"])
ov = service.plan_overview(conn, at(wk(3)), 2, path)                     # opened three weeks later
hist_w, hist_e = {}, {}
for r in conn.execute("SELECT recipient_guid, dist_date, holiday FROM history WHERE source='web' ORDER BY id"):
    (hist_e if r["holiday"] else hist_w).setdefault((r["dist_date"], r["holiday"]), []).append(r["recipient_guid"])
t.ok("S19 three weeks and two events closed; the event that is still ahead did not",
     ov["closed_now"] == [W0.isoformat(), wk(1).isoformat(), wk(2).isoformat()] and len(ov["closed_events_now"]) == 2
     and [e["guid"] for e in store.load_events(conn)] == [g_far])
t.ok("S19 each closed week holds the list of the one straight computation (the events among them included)",
     [hist_w.get((w["date"].isoformat(), ""), []) for w in straight["weeks"][:3]] == [guids(w["main"]) for w in straight["weeks"][:3]])
t.ok("S19 each closed event holds its list too — the Sunday one before that Wednesday, the Wednesday one after the regular list",
     [x["guid"] for x in straight["events"][:2]] == [g_sun, g_wed]
     and hist_e.get((NEXT_SUN.isoformat(), "*")) == guids(straight["events"][0]["main"])
     and hist_e.get((wk(1).isoformat(), "פסח")) == guids(straight["events"][1]["main"]))
order = [r["guid"] for r in conn.execute("SELECT guid FROM batches WHERE source='web' ORDER BY rowid")]
t.ok("S19 they were written oldest first: week, the Sunday event, week, the Wednesday event, week",
     order == [store.week_batch_guid(W0), store.event_batch_guid(g_sun), store.week_batch_guid(wk(1)),
               store.event_batch_guid(g_wed), store.week_batch_guid(wk(2))])
t.ok("S19 the coming weeks continue the same chain",
     [w["main"] for w in ov["weeks"]] == [guids(w["main"]) for w in straight["weeks"][3:5]])
conn.close()

# ── S20: by hand for an event, and "changed since it was printed" ─────────────
path, conn = fresh("s20", recs3, hist=hist3, closed=wk(-1), settings=settings3)
g = new_event(conn, path, FRI, portions=10, reserve=1)
base_d = event_service.detail(conn, NOW, g, path)
event_service.set_manual(conn, NOW, g, "g0004", "add", path)             # not marked: by hand only
event_service.set_manual(conn, NOW, g, "g0001", "remove", path)
event_service.set_manual(conn, NOW, g, "g0002", "reserve", path)
d = event_service.detail(conn, NOW, g, path)
marks = {e["guid"]: e["manual"] for e in d["main"] + d["reserve_list"] + d["out"] if e.get("manual")}
t.ok("S20 by hand: added is on the list, moved is first on the reserve, removed is on no list — each marked",
     marks == {"g0004": "add", "g0001": "remove", "g0002": "reserve"} and d["main"][0]["guid"] == "g0004"
     and d["reserve_list"][0]["guid"] == "g0002" and d["manual_count"] == 3
     and store.get_event(conn, g)["manual"] == marks)
said = {
    "a paused card onto an event's list": refusal(lambda: event_service.set_manual(conn, NOW, g, "g0041", "add", path)),
    "a card that does not exist": refusal(lambda: event_service.set_manual(conn, NOW, g, "g9999", "add", path)),
    "an action that does not exist": refusal(lambda: event_service.set_manual(conn, NOW, g, "g0001", "delete", path)),
    "an event that does not exist": refusal(lambda: event_service.set_manual(conn, NOW, "nope", "g0001", "add", path)),
}
t.ok("S20 what cannot be set by hand is refused in words", all(said.values()) and "מושהה" in said["a paused card onto an event's list"])
for card in ("g0004", "g0001", "g0002"):
    event_service.set_manual(conn, NOW, g, card, "clear", path)
t.ok("S20 'clear' forgets the change: the event is exactly as before",
     event_service.detail(conn, NOW, g, path) == base_d and store.get_event(conn, g)["manual"] == {})
t.ok("S20 an event that was never printed carries no note", base_d["print"] is None)
event_service.mark_printed(conn, NOW, g, "print", path)
d = event_service.detail(conn, NOW, g, path)
t.ok("S20 right after printing nothing has changed", d["print"]["changed"] is False and d["print"]["printed_at"] == "2026-11-25 10:00")
event_service.set_manual(conn, NOW, g, "g0004", "add", path)
event_service.set_manual(conn, NOW, g, "g0001", "remove", path)
d = event_service.detail(conn, NOW, g, path)
t.ok("S20 after a change the event says who was added and who went out, by name; the overview only how many",
     d["print"]["changed"] is True and d["print"]["added_names"] == ["בדיקה 0004"] and d["print"]["removed_names"] == ["בדיקה 0001"]
     and "added_names" not in event_service.overview(conn, NOW, path)["open"][0]["print"]
     and event_service.overview(conn, NOW, path)["open"][0]["print"]["changed"] is True)
sheet = event_service.paper(conn, NOW, g, path)[0]
t.ok("S20 the paper sheet: named for the holiday and the day, by name, with the phones",
     "חלוקת חג" in sheet["title"] and "יום שישי" in sheet["title"] and FRI.strftime("%d/%m/%Y") in sheet["title"]
     and [r["name"] for r in sheet["main"]] == sorted(e["name"] for e in d["main"])
     and next(r for r in sheet["main"] if r["name"] == "בדיקה 0021")["phones"] == "0501120021"
     and next(r for r in sheet["main"] if r["name"] == "בדיקה 0040")["kind"] == "כרטיס בלבד")
t.ok("S20 an unknown way of producing is refused", bool(refusal(lambda: event_service.mark_printed(conn, NOW, g, "fax", path))))
conn.close()

# ── S21: a database from stage 3 gets the event tables; a merged card keeps its events ──
path, conn = fresh("s21", recs3, hist=hist3, closed=wk(-1), settings=settings3)
conn.executescript("DROP TABLE events; DROP TABLE event_manual; DROP TABLE event_prints; DROP TABLE event_members;")
conn.close()
store._ensured.discard(path)
store.ensure_schema(path)
conn = store.connect(path)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
t.ok("S21 the four event tables are added; cards and history are untouched",
     {"events", "event_manual", "event_prints", "event_members"} <= tables
     and conn.execute("SELECT COUNT(*) FROM recipients").fetchone()[0] == len(recs3)
     and conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == len(hist3))
g = new_event(conn, path, FRI)
event_service.set_manual(conn, NOW, g, "g0022", "add", path)
event_service.mark_printed(conn, NOW, g, "print", path)
with store.tx(conn):
    store.merge_recipients(conn, "g0004", "g0022", {}, NOW)              # g0022 becomes part of g0004
t.ok("S21 a card that is merged into another takes its place in the event with it",
     store.get_event(conn, g)["manual"] == {"g0004": "add"}
     and "g0004" in store.load_event_prints(conn)[g]["main"] and "g0022" not in store.load_event_prints(conn)[g]["main"])
with store.tx(conn):
    store.insert_recipient(conn, {"full_name": "בדיקה 0050", "frequency": ""}, NOW, guid="g0050")
event_service.set_manual(conn, NOW, g, "g0050", "add", path)
card_service.delete(conn, NOW, "g0050", path)
t.ok("S21 a card that never received can be deleted also when it was set by hand for an event (the mark goes with it)",
     "g0050" not in store.get_event(conn, g)["manual"] and store.get_recipient(conn, "g0050") is None)
saturday = datetime(2026, 11, 28, 7, 0)                                 # the Friday event is over
service.roll_forward(conn, saturday, path)
t.ok("S21 a card that received in a holiday event has history: it cannot be deleted",
     "g0040" in [r["recipient_guid"] for r in conn.execute("SELECT recipient_guid FROM history WHERE holiday='*'")]
     and "היסטוריה" in refusal(lambda: card_service.delete(conn, saturday, "g0040", path)))
conn.close()

# ── S22: an event that is taken away can be brought back, as it was ───────────
path, conn = fresh("s22", recs3, hist=hist3, closed=wk(-1), settings=settings3)
weeks_before = service.plan_overview(conn, NOW, 4, path)
g = new_event(conn, path, FRI, holiday="פסח", portions=3, reserve=1, criteria={"income": {"min": None, "max": 5000}})
event_service.set_manual(conn, NOW, g, "g0004", "add", path)
event_service.mark_printed(conn, NOW, g, "print", path)
whole = event_service.detail(conn, NOW, g, path)
event_service.remove(conn, NOW, g, path)
ov = event_service.overview(conn, NOW, path)
t.ok("S22 an event that was taken away is on no list of events, and the weeks are as before it",
     ov["open"] == [] and store.load_events(conn) == [] and store.load_events(conn, open_only=False) == []
     and service.plan_overview(conn, NOW, 4, path) == weeks_before)
t.ok("S22 ...but it is offered for bringing back, by its name and day",
     [(e["guid"], e["name"], e["day"], e["portions"]) for e in ov["deleted"]] == [(g, "חלוקת פסח", "יום שישי", 3)])
said = {
    "showing it": refusal(lambda: event_service.detail(conn, NOW, g, path)),
    "changing it": refusal(lambda: event_service.save(conn, NOW, {"guid": g, "date": FRI.isoformat(), "holiday": "*", "portions": 9}, path)),
    "setting somebody by hand in it": refusal(lambda: event_service.set_manual(conn, NOW, g, "g0001", "add", path)),
    "printing it": refusal(lambda: event_service.paper(conn, NOW, g, path)),
    "taking it away again": refusal(lambda: event_service.remove(conn, NOW, g, path)),
}
t.ok("S22 while it is away it cannot be shown, changed, set by hand, printed or taken away again",
     all("לא נמצאה" in words for words in said.values()), str(said))
t.ok("S22 nothing of it was erased: its settings and what was set by hand are still stored",
     store.get_event(conn, g)["manual"] == {"g0004": "add"} and store.get_event(conn, g)["portions"] == 3
     and g in store.load_event_prints(conn))
event_service.restore(conn, NOW, g, path)
t.ok("S22 brought back, it is exactly the event it was — its filter, what was set by hand and its print note",
     event_service.detail(conn, NOW, g, path) == whole and event_service.overview(conn, NOW, path)["deleted"] == [])
t.ok("S22 bringing back what is not away is refused",
     "לשחזר" in refusal(lambda: event_service.restore(conn, NOW, g, path))
     and "לשחזר" in refusal(lambda: event_service.restore(conn, NOW, "nope", path)))
event_service.remove(conn, NOW, g, path)
sunday = datetime(2026, 11, 29, 9, 0)                                   # the Friday of the event is over
ov = event_service.overview(conn, sunday, path)
t.ok("S22 an event that was away when its day passed is NOT written to the history",
     conn.execute("SELECT COUNT(*) FROM history WHERE holiday<>''").fetchone()[0] == 0
     and conn.execute("SELECT COUNT(*) FROM batches WHERE holiday<>''").fetchone()[0] == 0
     and ov["past"] == [] and ov["open"] == [])
t.ok("S22 ...and it can no longer be brought back (the past is fixed), nor is it offered",
     "עבר" in refusal(lambda: event_service.restore(conn, sunday, g, path)) and ov["deleted"] == []
     and store.get_event(conn, g)["deleted_at"] is not None)
conn.close()

# ── S23: an events table from before "taken away" gets the new column by itself ──
path, conn = fresh("s23", recs3, hist=hist3, closed=wk(-1), settings=settings3)
g = new_event(conn, path, FRI)
conn.execute("ALTER TABLE events DROP COLUMN deleted_at")
conn.close()
store._ensured.discard(path)
store.ensure_schema(path)
conn = store.connect(path)
t.ok("S23 the column is added, and the event that was there is still there",
     "deleted_at" in {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
     and [e["guid"] for e in store.load_events(conn)] == [g] and store.get_event(conn, g)["deleted_at"] is None)
event_service.remove(conn, NOW, g, path)
t.ok("S23 ...and it can be taken away and brought back", store.load_events(conn) == []
     and event_service.restore(conn, NOW, g, path)["guid"] == g and len(store.load_events(conn)) == 1)
conn.close()

shutil.rmtree(TMP, ignore_errors=True)
t.done()
