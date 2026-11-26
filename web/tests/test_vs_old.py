# -*- coding: utf-8 -*-
"""The website's planner side by side with the desktop program — same data, same lists.

For each random population: build a real desktop database (through the desktop program's
own functions, in a throw-away folder), lay out several weeks the desktop way
(web/tests/oracle_old.py), import that database into the site and lay out the same weeks
with web/planner.py. Every week must match: who receives (in the same order), how many
regulars were in turn, and the reserve.

Stage 4: most populations also get one or two HOLIDAY rounds among the weeks (any day of
the week, a named holiday or all of them, with or without a filter). The holiday list must
match too — same people, same order, same reserve — and so must every week after it (the
desktop side records the holiday list as a holiday round; the site lays the event out).

Run:  <python 3.12> web/tests/test_vs_old.py [populations=14]
Invented people only. Nothing outside the temp folder is read or written.
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import timedelta

from _util import Checker, W0, guids, wk

import oracle_old as old

from web import import_old, planner, store
from web.engine import selection

N = int(sys.argv[1]) if len(sys.argv) > 1 else 14
t = Checker("website vs desktop program")
TMP = tempfile.mkdtemp(prefix="haluka_vs_old_")
os.environ["HALUKA_WEB_SKIP_GIT_GUARD"] = "1"          # the temp folder is not a repository
db = old.load(TMP)
FREQS = ["שבועי", "דו-שבועי", "תלת-שבועי", "חודשי"]


def holiday_fields(rng) -> dict:
    """The holiday mark of a card (general, or for some holidays) and the number of children."""
    return {"holiday_support": rng.choice([0, 1, 1]), "holidays": rng.choice(["", "", "פסח", "סוכות,פסח", "חנוכה"]),
            "children_total": rng.randint(0, 9)}


def random_events(rng, weeks) -> list:
    """0–2 holiday rounds anywhere from the Sunday before the first week to the end of the last one."""
    out = []
    for k in range(rng.choice([0, 1, 1, 2])):
        crit = {}
        if rng.random() < 0.5:
            crit["children_total"] = {"min": rng.randint(1, 5), "max": None}
        if rng.random() < 0.5:
            crit["income"] = {"min": None, "max": rng.choice([2500, 5000])}
        if rng.random() < 0.3:
            crit["per_soul"] = {"min": None, "max": rng.choice([400, 1500])}
        out.append({"guid": f"e{k}", "date": W0 + timedelta(days=rng.randint(-3, 7 * weeks - 1)),
                    "holiday": rng.choice(["*", "*", "פסח", "סוכות", "חנוכה"]), "criteria": crit,
                    "portions": rng.choice([1, 3, 8, 20, 60]), "reserve": rng.choice([0, 2, 5]),
                    "created_at": f"2026-11-0{k + 1} 10:00:00"})
    return out


def build_population(rng, case_dir, hrng):
    """A fresh desktop database with cards and a few weeks of recorded history. `hrng` is a
    stream of its own for what stage 4 added (the holiday marks, the children, the events),
    so the populations and the weeks of the earlier stages stay exactly the ones they were."""
    old.use_db(os.path.join(case_dir, "ManhalHaluka", "data.db"))
    with old.clock() as sim:
        sim._today = wk(-9)
        db.init_db()
        cooldown = rng.choice([0, 3, 4, 4, 4])
        db.set_setting("onetime_cooldown_weeks", str(cooldown))
        if rng.random() < 0.3:
            db.set_need_weights({"money": rng.randint(0, 60), "souls": rng.randint(0, 60),
                                 "recency": rng.randint(0, 60), "income": rng.randint(0, 30)})
        people = []
        names = [f"בדיקה {i:03d}" for i in range(200)]
        for i in range(rng.randint(4, 30)):                       # regulars
            name = rng.choice(names[:8]) if rng.random() < 0.1 else names[10 + i]   # some share a name
            card = {"full_name": name, "status": "פעיל", "frequency": rng.choice(FREQS),
                    "priority": rng.choice([4, 4, 3, None]), "souls": rng.randint(0, 12),
                    "per_soul": rng.choice(["", "0", "-300", str(rng.randint(1, 3000))]),
                    "income": rng.choice(["", str(rng.randint(0, 9000))]),
                    "start_date": (wk(-30) + timedelta(days=rng.randint(0, 120))).isoformat()}
            card.update(holiday_fields(hrng))
            if rng.random() < 0.25:                                # an imported "last distribution"
                card["last_distribution"] = (wk(-rng.randint(1, 6)) - timedelta(days=rng.choice([0, 0, 1, 2]))).isoformat()
            people.append(db.add_recipient(card))
        for i in range(rng.randint(0, 70)):                       # one-timers
            card = {"full_name": names[60 + i], "status": "פעיל", "frequency": "חד-פעמי",
                    "priority": rng.choice([3, 2, 2, 2, None, 1]), "souls": rng.randint(0, 12),
                    "per_soul": rng.choice(["", "0", "-50", str(rng.randint(1, 3000))]),
                    "income": hrng.choice(["", "0", str(hrng.randint(100, 9000))]),
                    "start_date": (wk(-40) + timedelta(days=rng.randint(0, 200))).isoformat()}
            card.update(holiday_fields(hrng))
            if rng.random() < 0.15:
                card["last_distribution"] = wk(-rng.randint(1, 7)).isoformat()
            people.append(db.add_recipient(card))
        for i in range(rng.randint(0, 6)):                        # data-only cards
            people.append(db.add_recipient(dict({"full_name": names[150 + i], "status": "פעיל", "frequency": "",
                                                 "priority": rng.choice([None, 1, 0])}, **holiday_fields(hrng))))
        all_guids = [dict(db.get_recipient(rid))["guid"] for rid in people]
        # recorded rounds of the last weeks: Wednesdays, a Sunday / Monday one, a late Thursday
        # one, holiday and bonus rounds, recorded no-shows
        days = sorted({wk(-k) + timedelta(days=off)
                       for k in range(1, 9) for off in rng.sample([0, 0, 0, -3, -2, 1], 1)
                       if rng.random() < 0.75})
        if rng.random() < 0.5:
            days = sorted(set(days) | {wk(-7) - timedelta(days=3), wk(-7) - timedelta(days=1)})   # 11/10 13/10: before the cut-over
        for day in days:
            sim._today = day
            picked = [g for g in all_guids if rng.random() < 0.35]
            missed = [g for g in all_guids if g not in picked and rng.random() < 0.05]
            holiday = rng.choice(["", "", "", "", "פסח", "בונוס"])
            old.record(picked, day, holiday=holiday, not_received=missed, name="past")
        for rid in people:                                         # some are paused / change frequency afterwards
            if rng.random() < 0.08:
                db.update_recipient(rid, {"status": "מושהה"})
            elif rng.random() < 0.05:
                db.update_recipient(rid, {"frequency": rng.choice(FREQS + ["חד-פעמי"])})
        sim._today = W0
        db.init_db()                                               # a program start: everything re-derived
    return cooldown


problems, cut_weeks, total_weeks, topped = [], 0, 0, 0
seen = {"people": 0, "regulars": 0, "one_timers": 0, "reserve": 0, "history_rows": 0,
        "weeks_with_waiting_regulars": 0, "weeks_with_paused_one_timers": 0}
hol = {"events": 0, "people": 0, "reserve": 0, "cut": 0, "filtered": 0, "missing_data": 0, "outside_filter": 0,
       "on_a_wednesday": 0, "weeks_after_an_event": 0, "one_timers_who_received": 0, "other_cards_who_received": 0}
for seed in range(N):
    rng, hrng = random.Random(1000 + seed), random.Random(5000 + seed)
    case = os.path.join(TMP, f"case{seed}")
    cooldown = build_population(rng, case, hrng)
    src = db.DB_PATH
    products = rng.choice([0, 3, 8, 15, 25, 52, 52, 80])
    reserve = rng.choice([0, 0, 3, 10])
    weeks = rng.randint(4, 9)
    events = random_events(hrng, weeks)

    # the site: import the desktop database, then plan forward
    web_db = os.path.join(case, "web", "haluka.db")
    import_old.import_old(src, web_db, now=__import__("datetime").datetime(W0.year, W0.month, W0.day, 10, 0))
    conn = store.connect(web_db)
    settings = store.get_settings(conn)
    mine_line = planner.plan_timeline(
        store.load_recipients(conn), store.load_received(conn), start=W0, weeks=weeks, horizon=W0,
        weights=planner.need_weights(settings),
        cooldown_weeks=store.int_setting(settings, "onetime_cooldown_weeks", 4),
        portions=products, reserve=reserve, events=events)
    mine = mine_line["weeks"]
    seen["history_rows"] += len(store.load_received(conn))
    conn.close()
    for w in mine:
        seen["people"] += len(w["main"])
        seen["regulars"] += w["main_regulars"]
        seen["one_timers"] += w["main_one_timers"]
        seen["reserve"] += len(w["reserve_list"])
        seen["weeks_with_waiting_regulars"] += any(e["group"] == planner.OUT_REG_WAIT for e in w["out"])
        seen["weeks_with_paused_one_timers"] += any(e["group"] == planner.OUT_ONE_PAUSE for e in w["out"])

    # the desktop program, on a throw-away copy of the same database
    sim_db = os.path.join(case, "sim", "ManhalHaluka", "data.db")
    old.copy_db(src, sim_db)
    old.use_db(sim_db)
    theirs_line = old.simulate_line(W0, weeks, products, reserve, events=events)
    theirs = theirs_line["weeks"]

    # the holiday rounds: same people, same order, same reserve
    if len(mine_line["events"]) != len(events) or len(theirs_line["events"]) != len(events):
        problems.append(f"population {seed}: {len(events)} holiday rounds, laid out {len(mine_line['events'])} / {len(theirs_line['events'])}")
    for a, b in zip(mine_line["events"], theirs_line["events"]):
        tag = (f"population {seed} holiday round {a['date']} ({a['holiday']}, portions {a['portions']}, "
               f"reserve {a['reserve']}, filter {sorted(a['criteria'])})")
        if a["date"] != b["date"] or guids(a["main"]) != b["main"]:
            problems.append(f"{tag}: the list differs ({len(a['main'])} vs {len(b['main'])})")
        if guids(a["reserve_list"]) != b["reserve_list"]:
            problems.append(f"{tag}: the reserve differs")
        hol["events"] += 1
        hol["people"] += len(a["main"])
        hol["reserve"] += len(a["reserve_list"])
        hol["cut"] += a["cut"]
        hol["filtered"] += bool(a["criteria"])
        hol["missing_data"] += a["missing"]
        hol["outside_filter"] += sum(1 for e in a["out"] if e["group"] == planner.OUT_EV_FILTER)
        hol["on_a_wednesday"] += a["date"].weekday() == 2
        hol["weeks_after_an_event"] += sum(1 for w in mine if w["date"] > a["date"])
        hol["one_timers_who_received"] += sum(1 for e in a["main"] if e["kind"] == "onetime")
        hol["other_cards_who_received"] += sum(1 for e in a["main"] if e["kind"] == "other")

    for i, (a, b) in enumerate(zip(mine, theirs)):
        total_weeks += 1
        tag = f"population {seed} week {i} (portions {products}, reserve {reserve}, pause {cooldown})"
        if products <= 0:
            # the desktop SCREEN shows an empty table for 0 portions (rule 8); its core does not cut
            if a["main"] or a["reserve_list"]:
                problems.append(tag + ": 0 portions must give an empty list")
            continue
        if a["regulars_due"] != b["regulars_due"]:
            problems.append(f"{tag}: regulars in turn {a['regulars_due']} != {b['regulars_due']}")
        if guids(a["main"]) != b["main"]:
            problems.append(f"{tag}: main list differs ({len(a['main'])} vs {len(b['main'])})")
        mine_res = guids(a["reserve_list"])
        if not b["cut"]:
            if mine_res != b["reserve_list"]:
                problems.append(f"{tag}: reserve differs")
        else:
            cut_weeks += 1
            # Rule 3 (21/10/2026): the reserve is always shown — after the regulars who were
            # cut, the site tops it up from the one-timers' queue (selection.top_up_reserve
            # on the desktop screen); the older composition left it short.
            regs_part = [e["guid"] for e in a["reserve_list"] if e["kind"] == "regular"]
            ones_part = [e["guid"] for e in a["reserve_list"] if e["kind"] == "onetime"]
            want = max(0, reserve - len(regs_part))
            if regs_part != b["reserve_list"] or ones_part != b["queue"][:want]:
                problems.append(f"{tag}: reserve after a cut differs")
            topped += bool(ones_part)

t.ok(f"{N} random populations, {total_weeks} weeks: same people, same order, same reserve as the desktop program",
     not problems, " | ".join(problems[:6]))
t.ok("the comparison covered weeks with more regulars than portions", cut_weeks > 0, f"cut weeks: {cut_weeks}")
t.ok("...and weeks where the reserve was topped up after a cut (rule 3)", topped > 0, f"topped: {topped}")
t.ok("the comparison was not empty: regulars, one-timers, reserve, waiting and paused people all appeared",
     all(seen.values()), str(seen))
t.ok("...and so were the holiday rounds: with and without a filter, cut and not, on a Wednesday and off it, "
     "one-timers and other cards receiving, weeks after them", all(hol.values()), str(hol))
print(f"       ({total_weeks} weeks compared, {cut_weeks} of them cut; {seen})")
print(f"       (holiday rounds: {hol})")
shutil.rmtree(TMP, ignore_errors=True)
t.done()
