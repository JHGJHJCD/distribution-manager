# -*- coding: utf-8 -*-
"""The comparison with the desktop program, on a COPY of real data — run by hand, locally.

    <python 3.12> web/tests/local_check_real.py --from <copy of data.db>
                  [--sent-history <json>] [--weeks 13] [--portions 52] [--reserve 10] [--start YYYY-MM-DD]

Works only inside a temp folder: the source file is opened read-only, copied there, and
both sides run on the copies. Prints NUMBERS ONLY (no names) — safe to paste anywhere.
Not part of run_all.py: it needs real data, which never enters the repository.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime

from _util import guids

import oracle_old as old

from web import config, import_old, planner, service, store
from web.engine import selection

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="src", required=True)
ap.add_argument("--sent-history")
ap.add_argument("--weeks", type=int, default=13)
ap.add_argument("--portions", type=int, default=config.DEFAULT_PORTIONS)
ap.add_argument("--reserve", type=int, default=config.DEFAULT_RESERVE)
ap.add_argument("--start")
args = ap.parse_args()

now = config.now()
start = date.fromisoformat(args.start) if args.start else service.current_week(now)
sent = json.load(open(args.sent_history, encoding="utf-8")) if args.sent_history else []
TMP = tempfile.mkdtemp(prefix="haluka_real_check_")
os.environ["HALUKA_WEB_SKIP_GIT_GUARD"] = "1"
ok = True
try:
    # read-only snapshot of the source (through SQLite, so the -wal file is included)
    snap = os.path.join(TMP, "snapshot", "data.db")
    os.makedirs(os.path.dirname(snap))
    a = sqlite3.connect("file:" + os.path.abspath(args.src).replace("\\", "/") + "?mode=ro", uri=True)
    b = sqlite3.connect(snap)
    try:
        a.backup(b)
    finally:
        b.close()
        a.close()

    # the site
    web_db = os.path.join(TMP, "web", "haluka.db")
    report = import_old.import_old(snap, web_db, sent_history=args.sent_history, now=now)
    conn = store.connect(web_db)
    settings = store.get_settings(conn)
    mine = planner.plan_weeks(
        store.load_recipients(conn), store.load_received(conn), start=start, weeks=args.weeks,
        horizon=selection.upcoming_wednesday(now.date()), weights=planner.need_weights(settings),
        cooldown_weeks=store.int_setting(settings, "onetime_cooldown_weeks", 4),
        portions=args.portions, reserve=args.reserve)
    conn.close()

    # the desktop program, on its own copy
    db = old.load(os.path.join(TMP, "desktop"))
    sim = os.path.join(TMP, "desktop", "ManhalHaluka", "data.db")
    old.copy_db(snap, sim)
    old.use_db(sim)
    with old.clock() as clk:
        clk._today = now.date()
        db.init_db()
    theirs = old.simulate(start, args.weeks, args.portions, args.reserve, prior=sent)

    print("import report:", json.dumps(report, ensure_ascii=False))
    print(f"\n{'week':<12}{'in turn':>8}{'main':>6}{'reg':>5}{'one':>5}{'res':>5}  same list / same order / same reserve")
    for a_, b_ in zip(mine, theirs):
        same_set = set(guids(a_["main"])) == set(b_["main"])
        same_order = guids(a_["main"]) == b_["main"]
        same_res = guids(a_["reserve_list"]) == b_["reserve_list"] or b_["cut"]
        same_due = a_["regulars_due"] == b_["regulars_due"]
        ok = ok and same_set and same_order and same_res and same_due
        print(f"{a_['date'].isoformat():<12}{a_['regulars_due']:>8}{len(a_['main']):>6}{a_['main_regulars']:>5}"
              f"{a_['main_one_timers']:>5}{len(a_['reserve_list']):>5}  "
              f"{'yes' if same_set else 'NO'} / {'yes' if same_order else 'NO'} / {'yes' if same_res else 'NO'}"
              f"{'' if same_due else '  (regulars in turn differ: desktop %d)' % b_['regulars_due']}")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("\nRESULT:", "the site and the desktop program give the SAME lists on this data ✓" if ok
      else "DIFFERENCES found — do not trust the site on this data yet")
sys.exit(0 if ok else 1)
