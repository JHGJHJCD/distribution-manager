# -*- coding: utf-8 -*-
"""Regression tests for the fix round of 2026-07 (bugs #4/#5/#7/#9/#12/#14).

Standalone (not pytest): run with the project's Python 3.12.
    python test_fixes.py
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
from datetime import date, timedelta
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

def _next_wed(d):
    return d if d.weekday() == 2 else d + timedelta((2 - d.weekday()) % 7)


# ── #14 / #10: regulars stay on the weekly list after a distribution dated on
#    the upcoming Wednesday (future date) ──────────────────────────────────────
for i in range(3):
    db.add_recipient({"full_name": f"קבוע {i}", "status": "פעיל", "frequency": "שבועי",
                      "souls": 3, "last_distribution": "2026-06-01"})
wk = db.get_weekly_list()
ok("#14 weekly shows regulars before distribution", len(wk) == 3)
wed = _next_wed(date.today())
bid = db.bulk_add_distributions([dict(r) for r in wk], wed.isoformat(), "", 0, "מחלק",
                                dist_name="בדיקה", general_note="הערה כללית")
ok("#14 regulars STILL on the weekly list after a Wednesday-dated distribution",
   len(db.get_weekly_list()) == 3, str([r["full_name"] for r in db.get_weekly_list()]))

# ── #7: the general note is stored once on the batch, not on each recipient ────
batch = db.get_distribution_batches()[0]
ok("#7 general note on the batch", batch["general_note"] == "הערה כללית")
ok("#7 general note NOT duplicated into recipients",
   all("הערה כללית" not in (r["notes"] or "") for r in db.get_batch_recipients(bid)))

# ── #4: deleting the batch rolls back last/next distribution ───────────────────
db.delete_batch(bid)
regs = [r for r in db.get_all_recipients() if r["frequency"] != "חד-פעמי"]
ok("#4 delete_batch clears last_distribution", all(not r["last_distribution"] for r in regs))
ok("#4 delete_batch clears next_distribution", all(not r["next_distribution"] for r in regs))

# ── #4 (single record): delete_distribution rolls back too ─────────────────────
r0 = regs[0]["id"]
b2 = db.bulk_add_distributions([db.get_recipient(r0)], "2026-07-01", "", 0, "מחלק", dist_name="ב")
did = db.get_distributions_for_recipient(r0)[0]["id"]
db.delete_distribution(did)
ok("#4 delete_distribution clears the recipient's last_distribution",
   not db.get_recipient(r0)["last_distribution"])
db.delete_batch(b2)

# ── #12: scored mode (group tab base) ranks regulars only — one-timers join only
#    when explicitly added ──────────────────────────────────────────────────────
db.add_recipient({"full_name": "חדפ א", "status": "פעיל", "frequency": "חד-פעמי",
                  "priority": 3, "souls": 4})
db.add_recipient({"full_name": "נטול עדיפות", "status": "פעיל", "frequency": "חד-פעמי",
                  "priority": 1, "souls": 2})
scored = db.get_regulars_scored()
ok("#12 scored base has no one-timers",
   not any(r.get("frequency") == "חד-פעמי" for r in scored))

# ── #5: the one-time tab lists only real candidates (priority ראשונה/שנייה) ────
from main import MainWindow
win = MainWindow()
win.one_time_tab.refresh()
names = [r["full_name"] for r in win.one_time_tab._rows_data]
ok("#5 one-time list excludes no-priority people", "נטול עדיפות" not in names, str(names))
ok("#5 one-time list keeps real candidates", "חדפ א" in names)

# ── #9: the print gate blocks when products leave portions for one-timers and
#    none were chosen; passes once picks exist ─────────────────────────────────
# Fresh regulars that ARE due this week (a past last_distribution).
for i in range(3):
    db.add_recipient({"full_name": f"בתור {i}", "status": "פעיל", "frequency": "שבועי",
                      "souls": 3, "last_distribution": "2026-06-01"})
due = len(db.get_weekly_list())
ok("#9 setup: regulars are due this week", due >= 3, f"due={due}")
gt = win.group_tab
gt.refresh()
db.set_setting("available_products", "5"); db.set_setting("reserve_count", "0")
gt.products_spin.setValue(5)     # 3 regulars due → 2 left for one-timers
ok("#9 gate BLOCKS print before one-time picks are made", gt._one_time_gate_ok("הדפסה") is False)
gt.add_one_time_picks([{"id": [r for r in db.get_one_time_list() if r["in_distribution"]][0]["id"],
                        "_reserve": False}])
ok("#9 gate PASSES once a one-time pick is added", gt._one_time_gate_ok("הדפסה") is True)
gt.products_spin.setValue(2)     # only enough for the regulars (2<3) → no leftover
gt._extra_ids.clear(); gt._reserve_ids.clear()
ok("#9 gate PASSES when products only cover the regulars", gt._one_time_gate_ok("הדפסה") is True)

print("\nRESULT:", "ALL FIX TESTS PASS ✓" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
