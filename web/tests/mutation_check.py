# -*- coding: utf-8 -*-
"""Do the planner tests really bite?  (project rule: a test must be seen failing.)

Breaks the planner in one way at a time and runs test_planner.py against the broken
version; every break must make the tests FAIL. Run by hand after touching the tests:
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

from web import planner  # noqa: E402

TARGET = os.path.join(HERE, "test_planner.py")


def run() -> int:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            runpy.run_path(TARGET, run_name="__main__")
    except SystemExit as e:
        return int(e.code or 0)
    except Exception:                 # a broken planner may crash the test script: also a catch
        return 1
    return 0


def mutate(name, apply, undo):
    apply()
    try:
        code = run()
    finally:
        undo()
    caught = code != 0
    print(f"  {'OK  caught' if caught else 'MISSED    '}  {name}")
    return caught


results = []
base = run()
print(f"  {'OK' if base == 0 else 'FAIL'}  unbroken planner passes (exit {base})")
results.append(base == 0)

_add = planner.Ledger.add_regular
results.append(mutate("a laid-out week is not recorded (nobody's turn advances)",
                      lambda: setattr(planner.Ledger, "add_regular", lambda self, g, w: None),
                      lambda: setattr(planner.Ledger, "add_regular", _add)))

_extra = planner.is_extra_round
results.append(mutate("holiday / bonus rounds move the regular turn",
                      lambda: setattr(planner, "is_extra_round", lambda d, h: False),
                      lambda: setattr(planner, "is_extra_round", _extra)))

_init = planner.Ledger.__init__


def _no_horizon(self, horizon):
    _init(self, date.max)


results.append(mutate("future (typo) dates are counted",
                      lambda: setattr(planner.Ledger, "__init__", _no_horizon),
                      lambda: setattr(planner.Ledger, "__init__", _init)))

_between = planner.Ledger.regular_between
results.append(mutate("rule 9 is off (served this week, listed again)",
                      lambda: setattr(planner.Ledger, "regular_between", lambda self, g, lo, hi: False),
                      lambda: setattr(planner.Ledger, "regular_between", _between)))

_plan_week = planner.plan_week


def _reserve_receives(*a, **k):
    w = _plan_week(*a, **k)
    w["main"] = w["main"] + w["reserve_list"]
    return w


results.append(mutate("the reserve is recorded as having received",
                      lambda: setattr(planner, "plan_week", _reserve_receives),
                      lambda: setattr(planner, "plan_week", _plan_week)))

_recency = planner.recency_days
results.append(mutate("waiting days are ignored (who waited longest is lost)",
                      lambda: setattr(planner, "recency_days", lambda rec, today: 0),
                      lambda: setattr(planner, "recency_days", _recency)))

if all(results):
    print(f"\nRESULT: ALL {len(results) - 1} BREAKS WERE CAUGHT — the planner tests bite ✓")
    sys.exit(0)
print("\nRESULT: some breaks were NOT caught — strengthen test_planner.py")
sys.exit(1)
