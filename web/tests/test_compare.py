# -*- coding: utf-8 -*-
"""The comparison tool itself (web/tests/local_check_real.py), on invented people.

The tool is run by hand on real data, where nobody can check its answer by eye. So here it
gets a desktop database of invented people and must: find the two programs identical; really
cover every kind of round it claims to; report a planted fault as a difference (also one of
order only, and one of the reserve only); put down to the decision "חג לא נספר" only what
that decision causes; leave its source untouched; and never let a name, a phone, an id or a
community's name into what it writes.

Run:  <python 3.12> web/tests/test_compare.py
"""
import gc
import hashlib
import io
import os
import shutil
import sqlite3
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta

from _util import Checker, W0, wk

import oracle_old as old

import local_check_real as real

from web import config, planner

t = Checker("the comparison tool")
TMP = tempfile.mkdtemp(prefix="haluka_compare_")
os.environ["HALUKA_WEB_SKIP_GIT_GUARD"] = "1"              # the temp folder is not a repository
os.environ["HALUKA_WEB_DATA"] = os.path.join(TMP, "site-data")
db = old.load(os.path.join(TMP, "desktop"))
SRC = os.path.join(old._state["root"], "source-" + os.path.basename(TMP), "ManhalHaluka", "data.db")
NOW = datetime(W0.year, W0.month, W0.day, 10, 0)
_real_now, config.now = config.now, lambda: NOW
PHONE, FREQS = "0501234567", ["שבועי", "דו-שבועי", "תלת-שבועי", "חודשי"]
COMM = ["קהילה א", "קהילה א", "קהילה ב", "קהילה ג", ""]


def folder_state(path: str) -> dict:
    """Every file beside a data file (and the file itself), with a digest of its bytes."""
    folder, out = os.path.dirname(path), {}
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            with open(full, "rb") as f:
                out[name] = hashlib.sha256(f.read()).hexdigest()
    return out


# ── a desktop database of invented people ─────────────────────────────────────
old.use_db(SRC)
with old.clock() as sim:
    sim._today = wk(-9)
    db.init_db()
    db.set_setting("onetime_cooldown_weeks", "4")
    ids = []
    for i in range(26):                                     # regulars of every frequency
        ids.append(db.add_recipient({
            "full_name": f"בדיקה {i:03d}", "status": "פעיל", "frequency": FREQS[i % 4], "priority": 4,
            "souls": 2 + i % 7, "per_soul": str(200 + 137 * (i % 9)), "income": str(1500 + 410 * (i % 8)),
            "phone1": PHONE, "id_number": "123456782", "representative": COMM[i % 5],
            "holiday_support": 1 if i % 3 else 0, "holidays": ["", "חנוכה", "פסח,סוכות"][i % 3],
            "children_total": i % 6, "start_date": (wk(-30) + timedelta(days=3 * i)).isoformat()}))
    for i in range(44):                                     # one-timers of a first / second priority
        ids.append(db.add_recipient({
            "full_name": f"בדיקה {100 + i:03d}", "status": "פעיל", "frequency": "חד-פעמי", "priority": 3 if i % 2 else 2,
            "souls": 1 + i % 8, "per_soul": str(100 + 91 * (i % 11)), "income": str(900 + 333 * (i % 7)),
            "phone1": PHONE, "representative": COMM[(i + 2) % 5], "holiday_support": 1 if i % 4 else 0,
            "holidays": ["", "חנוכה", "", "פסח"][i % 4], "children_total": i % 5,
            "start_date": (wk(-40) + timedelta(days=4 * i)).isoformat()}))
    for i in range(4):                                      # cards that take no part in the weekly lists
        ids.append(db.add_recipient({
            "full_name": f"בדיקה {200 + i:03d}", "status": "פעיל", "frequency": "", "priority": 1, "souls": 5,
            "per_soul": "300", "income": "2000", "representative": COMM[i], "holiday_support": 1, "holidays": "",
            "children_total": 3 + i}))
    GUIDS = [dict(db.get_recipient(r))["guid"] for r in ids]
    regs, ones = GUIDS[:26], GUIDS[26:70]
    for k in range(8, 0, -1):                               # eight recorded Wednesdays
        sim._today = wk(-k)
        old.record([g for j, g in enumerate(regs) if (j + k) % 2 == 0] + (ones + ones)[(k * 5) % 44:][:6], wk(-k), name="past")
    sim._today = wk(-1) + timedelta(days=4)                 # last Sunday: a holiday round, inside the one-timers' pause
    old.record(regs[1:9] + ones[20:32], sim._today, holiday="חנוכה", name="holiday")
    sim._today = wk(-1) + timedelta(days=5)                 # ...and a bonus round on the Monday
    old.record(regs[10:14] + ones[32:38], sim._today, holiday="בונוס", name="bonus")
    db.update_recipient(ids[5], {"status": "מושהה"})
    db.set_filter_criteria({"children_total": {"min": 2, "max": None}})
    db.set_community_quotas({"קהילה ב": 40.0})
    sim._today = W0
    db.init_db()                                            # a program start: everything re-derived
gc.collect()                                                # the desktop code lets go of the file (and folds its -wal in)
before = folder_state(SRC)


def run(**kw) -> dict:
    said.clear()
    return real.run(SRC, TMP, NOW, weeks=6, portions=20, reserve=5, say=lambda *a: said.append(" ".join(map(str, a))), **kw)


def private(text: str) -> list:
    """What must never be in anything the tool writes."""
    return [w for w in ["בדיקה", PHONE, "123456782", "קהילה א", "קהילה ב", "קהילה ג"] + GUIDS[:5] + GUIDS[40:43] if w in text]


said = []
res = run()
sec = {s["key"]: s for s in res["sections"]}
hol = [s for s in res["sections"] if s["key"].startswith("holiday")]
rows = [r for s in res["sections"] if not s["expected"] for r in s["rows"]]

# ── C1: on sound data the two programs agree, and the tool says so ────────────
t.ok("C1 the site and the desktop program give the same lists on every round that was laid out",
     res["identical"] is True and res["differ"] == 0 and res["lists"] == len(rows) > 30,
     str([(s["key"], s["differ"]) for s in res["sections"]]))
t.ok("C1 what was compared: ordinary weeks, weeks short of portions, weeks by score, the program as it is, holiday lists",
     {"ordinary", "short", "scored", "as_it_is"} <= set(sec) and len(hol) >= 5
     and all(len(sec[k]["rows"]) == 6 for k in ("ordinary", "short", "scored", "as_it_is")))

# ── C2: the comparison was not empty ──────────────────────────────────────────
t.ok("C2 the short weeks were really short (fewer on the list than regulars in turn), and the weeks by score were marked so",
     any(r["main"] < r["in_turn"] for r in sec["short"]["rows"]) and all(r["by_score"] for r in sec["scored"]["rows"])
     and not any(r["by_score"] for r in sec["ordinary"]["rows"]))
ev = [r for s in hol for r in s["rows"] if r["what"] == "event"]
t.ok("C2 holiday lists: for all the holidays and for named ones, plain, split between the communities, with the saved filter",
     len({r["holiday"] for r in ev}) >= 3 and any(r["balance"] for r in ev) and any(not r["balance"] for r in ev)
     and any(r["filtered"] for r in ev) and any(r["filtered"] and r["balance"] for r in ev)
     and all(0 < r["main"] <= r["portions"] < r["eligible"] <= r["marked"] for r in ev), str(ev[:2]))
t.ok("C2 ...each holiday list with the weeks around it, and there were people on the reserves",
     all(sum(1 for r in s["rows"] if r["what"] == "week") == 4 and sum(1 for r in s["rows"] if r["what"] == "event") == 1
         for s in hol) and any(r["reserve"] for r in ev) and any(r["reserve"] for r in sec["ordinary"]["rows"]))
t.ok("C2 the numbers of the data come with the result, and they are numbers",
     res["data"]["cards"] == 74 and res["data"]["active"] == 73 and res["data"]["history_rows"] > 100
     and sum(res["regulars"].values()) == 25 and res["start"] == W0.isoformat())

# ── C3: the decision "חג לא נספר" is reported as what it is ────────────────────
t.ok("C3 against the desktop program exactly as it is, the weeks differ (a holiday portion pauses a one-timer there)",
     sec["as_it_is"]["expected"] is True and sec["as_it_is"]["differ"] > 0
     and res["expected_differences"] == sec["as_it_is"]["differ"])
t.ok("C3 ...that is not counted as a fault, and it is put down to the decision because the same weeks match with it applied",
     res["identical"] is True and res["expected_explained"] is True and sec["ordinary"]["differ"] == 0)

# ── C4: the report ────────────────────────────────────────────────────────────
page = real.render(res)
t.ok("C4 the report opens with the answer, and says what was compared",
     "האתר והתוכנה הישנה נותנים אותן רשימות" in page and 'dir="rtl"' in page and "שבועות רגילים" in page
     and "חלוקת חג" in page and "מה לא הושווה" in page and "הבדל צפוי" in page and "ולא תקלה" in page)
t.ok("C4 nothing private is in the report or in what was printed: no name, phone, id, community or card id",
     private(page) == [] and private("\n".join(said)) == [] and private(str(res)) == [], str(private(page + str(res))))
t.ok("C4 the report loads nothing from outside", "http://" not in page and "https://" not in page and "<script" not in page)

# ── C5: a fault in the site shows as a difference ─────────────────────────────
_extra = planner.is_extra_round
planner.is_extra_round = lambda d, h: False                 # a holiday / bonus round moves the regular turn
bad = run()
planner.is_extra_round = _extra
bad_rows = [r for s in bad["sections"] if not s["expected"] for r in s["rows"] if not r["same"]]
lines = [d for r in bad_rows for d in r["differences"]]
bad_page = real.render(bad)
t.ok("C5 a site that counts a holiday round as a regular one is caught: lists differ, and the answer is 'differences'",
     bad["identical"] is False and bad["differ"] == len(bad_rows) > 0 and "יש הבדל ב־" in bad_page
     and "נותנים אותן רשימות" not in bad_page)
t.ok("C5 each difference says what KIND of recipient, where each program put him, and the site's category — in fixed words",
     len(lines) > 0 and all(d["site"] in real.PLACE and d["old"] in real.PLACE and d["site"] != d["old"] for d in lines)
     and all(d["who"].split(" ")[0] in ("קבוע", "חד-פעמי", "כרטיס") for d in lines)
     and all(d["why"] in list(real.WHY_OUT.values()) + ["", "נכנס כדי להשלים את החלק של הקהילה שלו"] for d in lines)
     and any(d["why"] for d in lines), str(lines[:3]))
t.ok("C5 ...still with nothing private, and the difference from the program as it is is no longer put down to the decision",
     private(bad_page) == [] and private(str(bad)) == [] and bad["expected_explained"] is False and "אי אפשר לייחס" in bad_page)

_site = real.Both.site


def first_week_changed(change):
    def site(self, *a, **k):
        line = _site(self, *a, **k)
        change(line["weeks"][0])
        return line
    return site


real.Both.site = first_week_changed(lambda w: w["main"].reverse())
swapped = run()
real.Both.site = _site
first = swapped["sections"][0]["rows"][0]
t.ok("C5 the same people in another order is a difference too, and the report says from which place",
     swapped["identical"] is False and first["same_people"] is True and first["same_order"] is False
     and first["first_out_of_order"] == 1 and "הסדר שונה החל מהמקום ה־1" in real.render(swapped))
real.Both.site = first_week_changed(lambda w: w["reserve_list"].pop())
short_reserve = run()
real.Both.site = _site
first = short_reserve["sections"][0]["rows"][0]
t.ok("C5 ...and so is a reserve that is one person short, when the list itself is the same",
     short_reserve["identical"] is False and first["same_order"] is True and first["same_reserve"] is False
     and first["same"] is False and first["reserve"] == first["reserve_old"] - 1)

_event = planner.plan_event
planner.plan_event = lambda event, people, ledger, **kw: _event(dict(event, balance=False), people, ledger, **kw)
flat = run()
planner.plan_event = _event
differing = [s["title"] for s in flat["sections"] if s["differ"] and not s["expected"]]
t.ok("C5 a site that ignores the split between the communities differs in the split lists only",
     len(differing) >= 2 and all("איזון" in title for title in differing)
     and all(s["differ"] == 0 for s in flat["sections"] if s["key"] in ("ordinary", "short", "scored")), str(differing))
t.ok("C5 ...and its report names no community (a community is called after a person)", private(real.render(flat)) == [])

# ── C6: the command itself ────────────────────────────────────────────────────
leftovers = {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("haluka_real_check_")}
out = os.path.join(TMP, "out", "report.html")
buf = io.StringIO()
with redirect_stdout(buf):
    code = real.main(["--from", SRC, "--weeks", "3", "--portions", "20", "--reserve", "5", "--quick", "--report", out])
with open(out, encoding="utf-8") as f:
    written = f.read()
t.ok("C6 the command answers 0 when the lists are the same, writes the report where it was asked to, and prints numbers only",
     code == 0 and "נותנים אותן רשימות" in written and "הרצה מקוצרת" in written and "SAME" in buf.getvalue()
     and private(buf.getvalue()) == [] and private(written) == [], buf.getvalue()[-300:])
with redirect_stdout(io.StringIO()):
    code = real.main(["--from", SRC, "--weeks", "2", "--portions", "20", "--reserve", "5", "--quick", "--report"])
default = real.default_report_path(NOW)
t.ok("C6 with no place given the report goes into the site's data folder (which is never published)",
     code == 0 and os.path.isfile(default) and default.startswith(os.path.join(TMP, "site-data", "compare")))
planner.is_extra_round = lambda d, h: False
with redirect_stdout(io.StringIO()) as printed:
    code = real.main(["--from", SRC, "--weeks", "3", "--portions", "20", "--reserve", "5", "--quick"])
planner.is_extra_round = _extra
t.ok("C6 it answers 1 when lists differ", code == 1 and "DIFFERENCES" in printed.getvalue())
out2 = os.path.join(TMP, "out", "failed.html")
with redirect_stdout(io.StringIO()) as printed:
    codes = [real.main(["--from", os.path.join(TMP, "no-such-file.db"), "--report", out2]),
             real.main(["--from", SRC, "--weeks", "0"]), real.main(["--from", SRC, "--portions", "0"])]
with open(out2, encoding="utf-8") as f:
    failed = f.read()
t.ok("C6 it answers 2 when it could not run (no such file, impossible numbers), and the page says so in words",
     codes == [2, 2, 2] and "ההשוואה לא רצה" in failed and "COULD NOT RUN" in printed.getvalue())
t.ok("C6 the copies it worked on are gone when it ends",
     {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("haluka_real_check_")} == leftovers)

# ── C7: the source was only read ──────────────────────────────────────────────
t.ok("C7 after everything, the data file is byte for byte what it was — and nothing was added beside it",
     folder_state(SRC) == before and list(before) == ["data.db"], str(sorted(folder_state(SRC))))
# a data file the desktop program is working on right now: what it wrote last is still in its -wal file
busy = os.path.join(TMP, "busy", "data.db")
os.makedirs(os.path.dirname(busy))
shutil.copy(SRC, busy)
keep = sqlite3.connect(busy)
keep.execute("PRAGMA wal_autocheckpoint=0")
keep.execute("UPDATE recipients SET notes='written a moment ago' WHERE id=1")
keep.commit()
state = folder_state(busy)
real.snapshot(busy, os.path.join(TMP, "snap-busy", "data.db"))
c = sqlite3.connect(os.path.join(TMP, "snap-busy", "data.db"))
t.ok("C7 a copy taken while the desktop program has the file open holds what it wrote a moment ago (it was still in the -wal file)",
     "data.db-wal" in state and c.execute("SELECT notes FROM recipients WHERE id=1").fetchone()[0] == "written a moment ago"
     and c.execute("SELECT COUNT(*) FROM recipients").fetchone()[0] == 74)
c.close()
t.ok("C7 ...and taking it wrote nothing in the program's folder: the same files, the same bytes", folder_state(busy) == state)
keep.close()
_pair, turn = real._read_pair, [0]


def never_still(src):
    turn[0] += 1
    return (b"x" * turn[0], b"")


real._read_pair, real.SNAPSHOT_TRIES = never_still, 3
try:
    real.snapshot(SRC, os.path.join(TMP, "snap-moving", "data.db"))
    stopped = ""
except RuntimeError as e:
    stopped = str(e)
real._read_pair, real.SNAPSHOT_TRIES = _pair, 20
t.ok("C7 a file that keeps changing while it is being copied is not compared at all (no half copy), and the reason is said",
     "kept changing" in stopped and not os.path.exists(os.path.join(TMP, "snap-moving", "data.db")))
with open(os.path.join(TMP, "broken.db"), "wb") as f:
    f.write(os.urandom(8192))
with redirect_stdout(io.StringIO()):
    code = real.main(["--from", os.path.join(TMP, "broken.db")])
t.ok("C7 a file that is not a database is not compared either (2)", code == 2)

keep_in = os.environ.get("HALUKA_KEEP_REPORTS")           # to look at the pages the tool writes (invented people)
if keep_in:
    os.makedirs(keep_in, exist_ok=True)
    for name, text in (("same.html", page), ("differences.html", bad_page), ("failed.html", failed)):
        with open(os.path.join(keep_in, name), "w", encoding="utf-8") as f:
            f.write(text)
config.now = _real_now
shutil.rmtree(TMP, ignore_errors=True)
t.done()
