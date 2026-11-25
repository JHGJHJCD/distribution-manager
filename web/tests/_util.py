# -*- coding: utf-8 -*-
"""Shared helpers for the website's tests.

The tests are standalone scripts like the rest of the project (run each one with the
project's Python 3.12; all of them with web/tests/run_all.py). Every person here is
invented ("בדיקה 001") — the repository is public, real names never enter a test.
"""
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

W0 = date(2026, 11, 25)                      # a Wednesday
assert W0.weekday() == 2


def wk(n: int) -> date:
    """The Wednesday n weeks after W0 (negative = before)."""
    return W0 + timedelta(days=7 * n)


class Checker:
    def __init__(self, title: str):
        self.title, self.fails, self.count = title, [], 0

    def ok(self, name: str, cond, extra: str = ""):
        self.count += 1
        if cond:
            print(f"  OK  {name}")
        else:
            self.fails.append(name)
            print(f"FAIL  {name}  {extra}")

    def done(self):
        if self.fails:
            print(f"\nRESULT: {len(self.fails)} of {self.count} checks FAILED in {self.title}")
            for f in self.fails:
                print("   -", f)
            sys.exit(1)
        print(f"\nRESULT: ALL {self.count} CHECKS PASS — {self.title} ✓")
        sys.exit(0)


def person(n: int, freq: str = "", priority=None, **kw) -> dict:
    """An invented card. freq: שבועי / דו-שבועי / תלת-שבועי / חודשי / חד-פעמי / ''."""
    rec = {
        "id": n, "guid": f"g{n:04d}", "full_name": f"בדיקה {n:04d}", "status": "פעיל",
        "frequency": freq, "priority": priority, "souls": 4, "per_soul": "", "income": "",
        "housing_expenses": "", "medical_expenses": "", "start_date": "2026-01-01",
        "created_at": "2026-01-01 08:00:00", "last_dist_base": "",
    }
    rec.update(kw)
    return rec


def got(guid: str, d, holiday: str = "", received: int = 1) -> dict:
    """A history row: `guid` received (or was a recorded no-show) on day `d`."""
    return {"recipient_guid": guid, "dist_date": d.isoformat() if isinstance(d, date) else d,
            "received": received, "holiday": holiday}


def guids(entries) -> list:
    return [e["guid"] for e in entries]
