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
