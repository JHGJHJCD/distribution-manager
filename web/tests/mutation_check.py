# -*- coding: utf-8 -*-
"""Do the website's tests really bite?  (project rule: a test must be seen failing.)

Breaks the site in one way at a time and runs the test file that should notice against
the broken version; every break must make that file FAIL. Run by hand after touching the
tests:
    <python 3.12> web/tests/mutation_check.py
"""
import contextlib
import io
import os
import runpy
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _util  # noqa: E402,F401  (puts the repository root on sys.path)

from web import app as webapp, config, planner, service, store  # noqa: E402

PLANNER, STORE, API = "test_planner.py", "test_store.py", "test_api.py"


def run(target: str):
    """Run one test file inside this process (so it sees the broken module).
    Returns (exit code, what noticed: the first failing check, or the crash)."""
    buf = io.StringIO()
    keep_now, keep_env = config.now, dict(os.environ)      # the test files set these for themselves
    code, crash = 0, ""
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(os.path.join(HERE, target), run_name="__main__")
    except SystemExit as e:
        code = int(e.code or 0)
    except Exception as e:            # a broken site may crash the test script: also a catch
        code, crash = 1, f"the test stopped: {type(e).__name__}: {e}"
    finally:
        config.now = keep_now
        os.environ.clear()
        os.environ.update(keep_env)
    failed = [ln[4:].strip() for ln in buf.getvalue().splitlines() if ln.startswith("FAIL")]
    return code, (failed[0][:110] + (f"  (+{len(failed) - 1} more)" if len(failed) > 1 else "")) if failed else crash


results = []


def mutate(target, name, obj, attr, broken):
    """Replace obj.attr with `broken`, run `target`, put the original back."""
    original = getattr(obj, attr)
    setattr(obj, attr, broken)
    try:
        code, noticed = run(target)
    finally:
        setattr(obj, attr, original)
    caught = code != 0
    print(f"  {'OK  caught' if caught else 'MISSED    '}  {target:<16} {name}")
    if caught:
        print(f"                {'':<16}   <- {noticed}")
    results.append(caught)


for target in (PLANNER, STORE, API):
    code, noticed = run(target)
    print(f"  {'OK' if code == 0 else 'FAIL'}  {target:<16} passes on the unbroken site (exit {code}) {noticed}")
    results.append(code == 0)
BASELINES = len(results)

# ── the planner: weeks, turns, history ────────────────────────────────────────
mutate(PLANNER, "a laid-out week is not recorded (nobody's turn advances)",
       planner.Ledger, "add_regular", lambda self, g, w: None)

mutate(PLANNER, "holiday / bonus rounds move the regular turn",
       planner, "is_extra_round", lambda d, h: False)

_init = planner.Ledger.__init__
mutate(PLANNER, "future (typo) dates are counted",
       planner.Ledger, "__init__", lambda self, horizon: _init(self, date.max))

mutate(PLANNER, "rule 9 is off (served this week, listed again)",
       planner.Ledger, "regular_between", lambda self, g, lo, hi: False)

_plan_week = planner.plan_week


def _reserve_receives(*a, **k):
    w = _plan_week(*a, **k)
    w["main"] = w["main"] + w["reserve_list"]
    return w


mutate(PLANNER, "the reserve is recorded as having received", planner, "plan_week", _reserve_receives)

mutate(PLANNER, "waiting days are ignored (who waited longest is lost)",
       planner, "recency_days", lambda rec, today: 0)

# ── the planner: what the manager sets by hand ────────────────────────────────
_plan_weeks = planner.plan_weeks


def _hand_ignored(*a, **k):
    k["manual"] = None
    return _plan_weeks(*a, **k)


mutate(PLANNER, "what was set by hand is ignored when the weeks are computed", planner, "plan_weeks", _hand_ignored)


def _hand_every_week(wed, people, ledger, **k):
    k["manual"] = _SPILL
    return _plan_week(wed, people, ledger, **k)


def _hand_spills(*a, **k):
    global _SPILL
    _SPILL = {}
    for per_week in (k.get("manual") or {}).values():
        _SPILL.update(per_week)
    return _plan_weeks(*a, **k)


_SPILL = {}
planner.plan_week = _hand_every_week
try:
    mutate(PLANNER, "a change set for one week applies to every week", planner, "plan_weeks", _hand_spills)
finally:
    planner.plan_week = _plan_week


def _removed_receives(wed, people, ledger, **k):
    w = _plan_week(wed, people, ledger, **k)
    for e in w["out"]:
        if e.get("manual") == planner.MANUAL_REMOVE:
            ledger.add_regular(e["guid"], wed)
    return w


mutate(PLANNER, "taken off a week by hand, but recorded as having received", planner, "plan_week", _removed_receives)


def _hand_reserve_receives(wed, people, ledger, **k):
    w = _plan_week(wed, people, ledger, **k)
    for e in w["reserve_list"]:
        if e.get("manual") == planner.MANUAL_RESERVE:
            ledger.add_regular(e["guid"], wed)
    return w


mutate(PLANNER, "moved to the reserve by hand, but recorded as having received", planner, "plan_week", _hand_reserve_receives)

_add_regular = planner.Ledger.add_regular
_NOT_COUNTED = set()


def _note_added(wed, people, ledger, **k):
    w = _plan_week(wed, people, ledger, **k)
    _NOT_COUNTED.update((e["guid"], wed) for e in w["main"] if e.get("manual") == planner.MANUAL_ADD)
    return w


def _skip_added(self, guid, wed):
    if (guid, wed) not in _NOT_COUNTED:
        _add_regular(self, guid, wed)


planner.plan_week = _note_added
try:
    mutate(PLANNER, "added by hand, but not counted as having received (his turn does not move)",
           planner.Ledger, "add_regular", _skip_added)
finally:
    planner.plan_week = _plan_week

# ── the store and the service: saving, closing, the print note ────────────────
mutate(STORE, "a change by hand is not saved", store, "set_manual", lambda conn, wed, guid, action, now: None)

_set_manual = store.set_manual
mutate(STORE, "'clear' does not forget the change",
       store, "set_manual", lambda conn, wed, guid, action, now: action and _set_manual(conn, wed, guid, action, now))

mutate(STORE, "the numbers set for a week are not used", store, "load_numbers", lambda conn: {})

_roll_forward = service.roll_forward


def _closes_without_hand(conn, now, db_path=None):
    keep = store.load_manual
    store.load_manual = lambda c: {}
    try:
        return _roll_forward(conn, now, db_path)
    finally:
        store.load_manual = keep


mutate(STORE, "a week that closes by itself forgets what was set by hand for it", service, "roll_forward", _closes_without_hand)

_print_note = service._print_note


def _never_changed(w, ctx, names=None):
    note = _print_note(w, ctx, names)
    if note:
        note.update(changed=False, added=0, removed=0, **({"added_names": [], "removed_names": []} if names is not None else {}))
    return note


mutate(STORE, "a list that changed after it was printed says nothing", service, "_print_note", _never_changed)

_set_print = store.set_print
mutate(STORE, "printing keeps the first paper for ever (a second printing does not start afresh)",
       store, "set_print", lambda conn, wed, how, main, reserve, now:
       None if conn.execute("SELECT 1 FROM week_prints WHERE week_wed=?", (wed.isoformat(),)).fetchone()
       else _set_print(conn, wed, how, main, reserve, now))

_open_index = service._open_index


def _past_is_open(conn, now, wed):
    try:
        return _open_index(conn, now, wed)
    except LookupError:
        return 0


mutate(STORE, "a week that has passed can still be changed", service, "_open_index", _past_is_open)

_service_set_manual = service.set_manual


def _paused_is_welcome(conn, now, wed, guid, action, db_path=None):
    try:
        return _service_set_manual(conn, now, wed, guid, action, db_path)
    except service.Refused as e:
        if "מושהה" not in str(e):
            raise
        with store.tx(conn):
            store.set_manual(conn, wed, guid, action, now)


mutate(STORE, "a paused card can be put on a list by hand", service, "set_manual", _paused_is_welcome)

service.sorted = sorted                     # print_weeks finds this name before the built-in one
try:
    mutate(STORE, "the paper list is not ordered by name", service, "sorted", lambda entries, key=None: list(entries))
finally:
    del service.sorted

# ── the routes ────────────────────────────────────────────────────────────────
mutate(API, "a change is accepted without the site's own header", webapp, "_from_this_site", lambda request: True)

mutate(API, "a name that starts with '=' reaches Excel as a formula", service, "_keep_as_text", lambda cell, value: None)

_public = service._public
mutate(API, "the phones go out to the screen too",
       service, "_public", lambda entries: [dict(e, phones="0501234567") for e in _public(entries)])

_mark_printed = service.mark_printed
mutate(API, "printing is remembered for the first week of the range only",
       service, "mark_printed", lambda conn, now, start, weeks, how, db_path=None:
       _mark_printed(conn, now, start, 1, how, db_path) and weeks)

breaks = len(results) - BASELINES
if all(results):
    print(f"\nRESULT: ALL {breaks} BREAKS WERE CAUGHT — the website's tests bite ✓")
    sys.exit(0)
print(f"\nRESULT: {results.count(False)} of {breaks} breaks were NOT caught — strengthen the tests")
sys.exit(1)
