# -*- coding: utf-8 -*-
"""End-to-end use-case simulations through the real tabs (offscreen)."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(scn, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + scn + (f"  [{extra}]" if extra else ""))
    if not cond: fails.append(scn)

from utils.print_view import _build_html

# seed: regulars + one-timers
for i in range(5):
    db.add_recipient({"full_name": f"קבוע {i}", "status": "פעיל", "frequency": "שבועי",
                      "souls": 3 + i, "phone1": f"05{i}1111111", "last_distribution": "2026-06-01"})
for i, (nm, pr) in enumerate([("פלוני א", 3), ("פלוני ב", 3), ("פלוני ג", 2), ("פלוני ד", 2), ("פלוני ה", 2)]):
    db.add_recipient({"full_name": nm, "status": "פעיל", "frequency": "חד-פעמי", "priority": pr,
                      "souls": 4 + i, "phone1": f"05{i}2222222", "per_soul": str(400 + i * 120)})

from main import MainWindow
win = MainWindow()

# ── Scenario 1: weekly regulars appear & are exportable ───────────────────────
win.weekly_tab.refresh()
wk_reg = [r for r in win.weekly_tab._rows_data if r.get("frequency") != "חד-פעמי"]
ok("S1 weekly shows regulars", len(wk_reg) >= 5)
ok("S1 weekly excludes one-timers initially",
   not any(r.get("frequency") == "חד-פעמי" for r in win.weekly_tab._rows_data))

# ── Scenario 2: one-time main + reserve → picks arrive UNCHECKED (#p5vv0),
# reserve STANDBY (RULE 3). 8 products, 5 regulars served first → 3 slots for
# one-timers (main), +1 reserve. The operator ticks who actually arrives.
ot = win.one_time_tab
# 'מוצרים זמינים'/'רזרבה' now live in the group tab (shared via settings).
db.set_setting("available_products", "8"); db.set_setting("reserve_count", "1")
ot.refresh(); ot._calc_suggestion()
ot._add_to_group_update()
gt = win.group_tab
gt_checked = [gt._rows_data[r]["full_name"] for r in range(gt.table.rowCount())
              if gt.table.item(r, 0) and gt.table.item(r, 0).checkState() == Qt.CheckState.Checked]
ot_checked = [n for n in gt_checked if n.startswith("פלוני")]
# #p5vv0: one-time picks are imported into the list but NOT auto-checked.
ok("S2 one-time MAIN picks arrive UNCHECKED (#p5vv0)", len(ot_checked) == 0, str(ot_checked))
main_ids = set(gt._extra_ids) - set(gt._reserve_ids)
ok("S2 one-time MAIN picks ARE in the list (just unmarked)", len(main_ids) >= 1, str(main_ids))
# RULE 3: the reserve pick rides along but is NOT ticked for recording (standby).
reserve_ids = set(gt._reserve_ids)
ok("S2 reserve pick is standby (NOT checked for recording)",
   bool(reserve_ids) and not (reserve_ids & gt._checked_ids), str(reserve_ids))
wk_ot = [r["full_name"] for r in gt._rows_data if r.get("frequency") == "חד-פעמי"]
ok("S2 one-timers merged into the list", len(wk_ot) >= 1, str(wk_ot))
ok("S2 reserve still flagged for the print", any(r.get("_reserve") for r in gt._rows_data))
ok("S2 print INCLUDES the reserve section (standby handed to distributor)",
   "רזרבה — לפי סדר עדיפות" in _build_html(gt._get_export_rows(), "10/06/2026"))
# The operator marks the main picks as arrived (ticks them), then records.
gt._checked_ids |= main_ids
gt._populate()
gt.dist_input.setCurrentText("מחלק א")
n_before = len(db.get_distributions())
gt._save()
ok("S2 distribution recorded for the ticked picks", len(db.get_distributions()) > n_before)
# RULE 3: a standby reserve must NOT land in the distribution history.
ok("S2 reserve NOT recorded to history",
   all(len(db.get_distributions_for_recipient(rid)) == 0 for rid in reserve_ids))
ok("S2 picks cleared after save", len(gt._extra_ids) == 0)

# ── Scenario 3: add a new ראשונה recipient → enters one-time distribution ──────
_rid = db.add_recipient({"full_name": "חדש ראשונה", "status": "פעיל", "frequency": "חד-פעמי",
                         "priority": 3, "souls": 6})
ot.refresh()
ok("S3 new priority-3 is in_distribution",
   any(r["full_name"] == "חדש ראשונה" and r.get("in_distribution") for r in ot._rows_data))

# ── Scenario 4: suspend a recipient → leaves the active weekly view ────────────
_susp = db.add_recipient({"full_name": "להשהות", "status": "פעיל", "frequency": "שבועי", "souls": 2})
db.update_recipient(_susp, {"status": "מושהה"})
win.weekly_tab.refresh()
ok("S4 suspended recipient not in weekly",
   not any(r["full_name"] == "להשהות" for r in win.weekly_tab._rows_data))

# ── Scenario 5: search by name → details + history ────────────────────────────
win.search_tab.refresh()
win.search_tab.search_input.setText("פלוני א"); win.search_tab._run_search()
ok("S5 search finds the recipient", len(win.search_tab._results) >= 1)
if win.search_tab._results:
    win.search_tab.results_list.setCurrentRow(0)
    _hlay = win.search_tab._hdr_lay
    _hdr_text = " ".join(
        _hlay.itemAt(i).widget().text()
        for i in range(_hlay.count())
        if _hlay.itemAt(i).widget() is not None
        and hasattr(_hlay.itemAt(i).widget(), "text"))
    ok("S5 details show a name", "פלוני" in _hdr_text)

# ── Scenario 6: backup → reset → restore ──────────────────────────────────────
from utils.backup import auto_backup, restore_from_backup
import sqlite3
_bkfd, _bk = tempfile.mkstemp(suffix=".db"); os.close(_bkfd)
_s = sqlite3.connect(db.DB_PATH); _d = sqlite3.connect(_bk); _s.backup(_d); _d.close(); _s.close()
_count = len(db.get_all_recipients())
db.reset_all_data()
ok("S6 reset empties data", len(db.get_all_recipients()) == 0)
ok("S6 restore brings data back", restore_from_backup(_bk) and len(db.get_all_recipients()) == _count)
try: os.unlink(_bk)
except OSError: pass

# ── Scenario 7: score breakdown data available on a ranked recipient ──────────
ot.refresh()
_t = next((r for r in ot._rows_data if r.get("in_distribution")), None)
ok("S7 ranked recipient has score breakdown",
   _t is not None and isinstance(_t.get("_score_parts"), list) and len(_t["_score_parts"]) >= 1)

# ── Scenario 8: priority shown as Hebrew labels, never raw numbers ─────────────
from tabs.recipients import _priority_display
ok("S8 priority labels have no digits",
   _priority_display({"priority": 3}) == "ראשונה" and _priority_display({"priority": 1}) == "")

# ── Scenario 9: 'scored' mode ranks manual picks on the SAME need scale ────────
# A one-timer with NO distribution priority is excluded from get_scored_all, so it
# only reaches the list as a manual pick — the case that used to be scored on its
# own isolated 0–100 scale and mis-ordered. It must now share the merged scale.
gt = win.group_tab
_extra = db.add_recipient({"full_name": "מ.י בלי עדיפות", "status": "פעיל",
                           "frequency": "חד-פעמי", "priority": None, "souls": 5})
gt.mode_combo.setCurrentIndex(gt.mode_combo.findData("scored"))
gt.add_one_time_picks([{"id": _extra}])          # persist pick + refresh (scored)
pick = next((r for r in gt._rows_data if r.get("id") == _extra), None)
ok("S9 manual pick appears in the scored list", pick is not None)
ok("S9 manual pick scored on the shared scale (need_score + parts)",
   pick is not None and isinstance(pick.get("need_score"), (int, float))
   and isinstance(pick.get("_score_parts"), list))
_scores = [r.get("need_score") or 0 for r in gt._rows_data]
ok("S9 whole scored list is monotonic — one scale, not two",
   _scores == sorted(_scores, reverse=True), str(_scores[:6]))
gt.mode_combo.setCurrentIndex(gt.mode_combo.findData("schedule"))   # restore

print()
print("RESULT:", "ALL SCENARIOS PASS ✓" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
