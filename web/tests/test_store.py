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

from web import config, import_old, planner, service, store

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

shutil.rmtree(TMP, ignore_errors=True)
t.done()
