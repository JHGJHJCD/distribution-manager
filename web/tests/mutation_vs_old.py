# -*- coding: utf-8 -*-
"""Does the comparison with the desktop program really bite?

Breaks the website's planner in one way at a time and runs test_vs_old.py against the
broken version (a fresh process each time); every break must make the comparison FAIL.
    <python 3.12> web/tests/mutation_vs_old.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = r"""
import runpy, sys
sys.path.insert(0, {here!r})
import _util
from web import planner
{patch}
sys.argv = ["test_vs_old.py", "8"]
runpy.run_path({target!r}, run_name="__main__")
"""
MUTATIONS = [
    ("an imported 'last distribution' (base date) is ignored",
     "planner.to_date_orig = planner.to_date\n"
     "_wr = planner.week_row\n"
     "def week_row(rec, wed, ledger):\n"
     "    return _wr(dict(rec, last_dist_base=''), wed, ledger)\n"
     "planner.week_row = week_row"),
    ("holiday / bonus rounds move the regular turn",
     "planner.is_extra_round = lambda d, h: False"),
    ("a recorded no-show counts as received",
     "_load = planner.Ledger.load\n"
     "planner.Ledger.load = lambda self, rows: _load(self, [dict(r, received=1) for r in rows])\n"
     "from web import store\n"
     "store.load_received = lambda conn: [dict(r) for r in conn.execute("
     "'SELECT recipient_guid, dist_date, 1 AS received, holiday FROM history WHERE recipient_guid IS NOT NULL')]"),
    # (a break must touch the SITE's side only: selection.py is shared with the desktop
    #  code in this process, so patching it would break both sides alike and prove nothing)
    ("a one-timer's last round is read a week too early (he returns a week too soon)",
     "import datetime\n"
     "from web.engine import selection\n"
     "_wr2 = planner.week_row\n"
     "def week_row(rec, wed, ledger):\n"
     "    row = _wr2(rec, wed, ledger)\n"
     "    if row['last_distribution'] and not selection.is_regular(row):\n"
     "        d = datetime.date.fromisoformat(row['last_distribution']) - datetime.timedelta(days=7)\n"
     "        row['last_distribution'] = d.isoformat()\n"
     "    return row\n"
     "planner.week_row = week_row"),
    ("waiting days count from today instead of from the week being planned",
     "import datetime\n"
     "_rd = planner.recency_days\n"
     "planner.recency_days = lambda rec, today: _rd(rec, today - datetime.timedelta(days=7 * ((today - datetime.date(2026, 11, 25)).days // 7)))"),
    ("cards are not ordered by name before ranking (ties fall differently)",
     "_ap = planner.active_people\n"
     "planner.active_people = lambda recs: sorted(_ap(recs), key=lambda r: r.get('guid') or '')"),
    # ── stage 4: the holiday rounds ──
    ("the regular lists count a holiday / bonus portion as 'received last' (a one-timer is paused after it)",
     "_wr3 = planner.week_row\n"
     "def week_row(rec, wed, ledger):\n"
     "    row = _wr3(rec, wed, ledger)\n"
     "    a = planner._last_dates(rec, ledger)[0]\n"
     "    row['last_distribution'] = a.isoformat() if a else ''\n"
     "    row['days_since'] = planner.recency_days(row, wed)\n"
     "    return row\n"
     "planner.week_row = week_row"),
    ("a holiday portion is forgotten: a later holiday list does not see it",
     "planner.Ledger.add_extra = lambda self, guid, day: None"),
    ("a holiday round counts as a regular round (it moves the regular turn)",
     "planner.Ledger.add_extra = planner.Ledger.add_regular"),
    ("the thresholds of a holiday event are dropped (everybody marked is on its list)",
     "_ec = planner.event_criteria\n"
     "planner.event_criteria = lambda event: {'holiday': _ec(event)['holiday']}"),
    ("a named holiday is read as 'all the holidays'",
     "_ec2 = planner.event_criteria\n"
     "planner.event_criteria = lambda event: dict(_ec2(event), holiday='*')"),
    ("on a holiday list only the last REGULAR round counts as 'received last' (an earlier holiday portion is forgotten)",
     "_er = planner.event_row\n"
     "import datetime\n"
     "def event_row(rec, day, ledger):\n"
     "    row = _er(rec, day, ledger)\n"
     "    a, r, b = planner._last_dates(rec, ledger)\n"
     "    row['last_distribution'] = r.isoformat() if r else ''\n"
     "    row['days_since'] = planner.recency_days(row, day)\n"
     "    return row\n"
     "planner.event_row = event_row"),
    # ── after stage 4: a week by need score, a holiday list split between the communities ──
    ("a week that is marked 'by score' is cut by who waited longest",
     "from web.engine import selection\n"
     "def _c(due, by_hand, weights, portions, reserve_auto):\n"
     "    ranked = selection.rank_by_wait(due, weights)\n"
     "    slots = max(0, portions - len(by_hand[planner.MANUAL_ADD]))\n"
     "    selection.assign_roles(ranked, slots, reserve_auto)\n"
     "    return ranked, len(ranked) > slots\n"
     "planner._cut_by_score = _c"),
    ("by score, the regulars who were cut are not put on the reserve",
     "_cs = planner._cut_by_score\n"
     "planner._cut_by_score = lambda due, by_hand, weights, portions, reserve_auto: _cs(due, by_hand, weights, portions, 0)"),
    ("a holiday list that should be split between the communities is cut by who waited longest",
     "_pe = planner.plan_event\n"
     "planner.plan_event = lambda event, people, ledger, **kw: _pe(dict(event, balance=False), people, ledger, **kw)"),
    ("the percentages fixed for communities are ignored",
     "_pe2 = planner.plan_event\n"
     "planner.plan_event = lambda event, people, ledger, weights, pinned=None: _pe2(event, people, ledger, weights=weights, pinned=None)"),
    ("a split holiday list is built from everybody active, marked or not",
     "_pe3 = planner.plan_event\n"
     "planner.plan_event = lambda event, people, ledger, **kw: _pe3(event, [dict(p, holiday_support=1, holidays='') for p in people] "
     "if event.get('balance') else people, ledger, **kw)"),
    ("on a holiday list nobody's waiting days are counted (who waited longest is lost)",
     "_er3 = planner.event_row\n"
     "planner.event_row = lambda rec, day, ledger: dict(_er3(rec, day, ledger), days_since=0)"),
]


def run(patch: str) -> int:
    code = RUNNER.format(here=HERE, patch=patch, target=os.path.join(HERE, "test_vs_old.py"))
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-c", code], capture_output=True, env=env).returncode


results = []
base = run("")
print(f"  {'OK' if base == 0 else 'FAIL'}  unbroken planner agrees with the desktop program (exit {base})")
results.append(base == 0)
for name, patch in MUTATIONS:
    caught = run(patch) != 0
    print(f"  {'OK  caught' if caught else 'MISSED    '}  {name}")
    results.append(caught)
if all(results):
    print(f"\nRESULT: ALL {len(MUTATIONS)} BREAKS WERE CAUGHT — the comparison bites ✓")
    sys.exit(0)
print("\nRESULT: some breaks were NOT caught — strengthen test_vs_old.py")
sys.exit(1)
