# -*- coding: utf-8 -*-
"""Report 7/10/2026, package B — 'חלוקה ורישום' screen (#a0r4i #3cbl6 #fyctc #szhaf
#andd6 #o16li #5ft0t). Standalone:  python test_group_report.py"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
from datetime import date, timedelta
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()

from PyQt6.QtWidgets import QApplication, QMessageBox
MSGS = []
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else "")))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

today = date.today()
REG = [db.add_recipient({"full_name": f"קבוע {i}", "status": "פעיל", "frequency": "שבועי",
                         "priority": 4, "souls": 3, "children_total": 3,
                         "last_distribution": (today - timedelta(days=14 + 7 * i)).isoformat()})
       for i in range(6)]
OTHER = db.add_recipient({"full_name": "אחר", "status": "פעיל", "frequency": "חד-פעמי",
                          "priority": 3, "souls": 4})

from main import MainWindow
from tabs import group_update as G
win = MainWindow(); gt = win.group_tab
def ids(): return [r["id"] for r in gt._rows_data]
def mode(m): gt.mode_combo.setCurrentIndex(gt.mode_combo.findData(m))

db.set_filter_criteria({"children_total": {"min": 1, "max": None}, "balance_communities": False})
# b1 — empty until products are set, every mode
for m in ("schedule", "none", "scored", "filter"):
    mode(m); gt.products_spin.setValue(0)
    ok(f"B1 {m}: products 0 → no rows", ids() == [] and gt.table.rowCount() == 0)
ok("B1b explanation shown", "הקלד כמה מוצרים זמינים" in gt.table._empty_label.text())
mode("schedule")
MSGS.clear()
gt._print(); gt._export_pdf(); gt._export_excel(); gt._export_prep_excel(); gt._send_to_volunteer()
ok("B1c print/PDF/Excel/volunteer on an empty list → a message each, no crash", len(MSGS) == 5, str(len(MSGS)))
gt._on_stage_toggle("record")
ok("B1d record stage blocked on an empty list", gt._stage == "prep")
ok("B1e week_rows() is empty", gt.week_rows() == [])

# b2 — new distribution resets the reserve
gt.products_spin.setValue(10); gt.reserve_spin.setValue(4)
gt._reset_for_new()
ok("B2 reset → products 0, reserve 0, saved settings too",
   gt.reserve_spin.value() == 0 and gt.products_spin.value() == 0
   and db.get_setting("reserve_count") == "0" and db.get_setting("available_products") == "0")

# b3 — short warning
gt.products_spin.setValue(4)
t = gt.lbl_leftover.text()
ok("B3 short shortage line", t == "⚠ אין מספיק לקבועים — חסרים 2 מוצרים" and not gt.btn_pick_onetime.isVisibleTo(gt), t)

# b4 — button disappears after picks
gt.products_spin.setValue(9)
ok("B4 before picking → button shown", gt.btn_pick_onetime.isVisibleTo(gt) and gt.leftover_card.isVisibleTo(gt))
gt.add_one_time_picks([{"id": OTHER, "_reserve": False}])
ok("B4b after picking → button gone", not gt.btn_pick_onetime.isVisibleTo(gt), gt.lbl_leftover.text())

# b5 — trash column
ok("B5 🗑 column exists, Fixed, visible in prep",
   gt.table.columnCount() == len(G.COLS) and not gt.table.isColumnHidden(G._COL_DEL)
   and gt.table.item(0, G._COL_DEL).text() == "🗑")
row_of = lambda rid: next(i for i, r in enumerate(gt._visible_rows()) if r["id"] == rid)
gt._on_cell_clicked(row_of(OTHER), G._COL_DEL)
ok("B5b one-time pick removed from list + saved picks", OTHER not in ids() and OTHER not in gt._extra_ids
   and db.get_recipient(OTHER) is not None)
ok("B5c button returns once the picks are all removed", gt.btn_pick_onetime.isVisibleTo(gt))
gt._on_cell_clicked(row_of(REG[0]), G._COL_DEL)
ok("B5d regular removed; recipient still in DB", REG[0] not in ids() and db.get_recipient(REG[0]))
gt.products_spin.setValue(12)
ok("B5e removal survives a product change and a refresh", REG[0] not in ids() and (gt.refresh() or True) and REG[0] not in ids())
ok("B5f counts follow", f"{len(gt._rows_data)}" in gt.lbl_total.text(), gt.lbl_total.text())
gt._set_stage("record"); gt._check_all()
ok("B5g 🗑 hidden in record stage; removed one not a no-show",
   gt.table.isColumnHidden(G._COL_DEL) and REG[0] not in ids())
gt._set_stage("prep", clear=False)
gt._add_manual.__func__  # exists
gt._removed_ids.discard(REG[0]); gt.refresh()
ok("B5h re-adding (discard) brings him back", REG[0] in ids())
gt._remove_from_list(next(r for r in gt._rows_data if r["id"] == REG[1]))
gt._reset_for_new()
ok("B5i new distribution clears removals", not gt._removed_ids)

# b6 — manual-add dialog in 'none'
d = G._ManualAddDialog(gt, exclude_ids=set(), hide_frequencies=G._ManualAddDialog.HIDE_FREQ_NO_REGULARS)
items = [d._freq_filter.itemText(i) for i in range(d._freq_filter.count())]
ok("B6 'none': no שבועי/דו-שבועי in the selector", "שבועי" not in items and "דו-שבועי" not in items, str(items))
d2 = G._ManualAddDialog(gt, exclude_ids=set())
items2 = [d2._freq_filter.itemText(i) for i in range(d2._freq_filter.count())]
ok("B6b other modes unchanged", items2 == ["כל התדירויות", "שבועי", "דו-שבועי", "תלת-שבועי", "חודשי"])

# b7 — 'none' mode rows carry score parts; dialog clickable
mode("none"); gt.products_spin.setValue(5)
gt.add_one_time_picks([{"id": OTHER, "_reserve": False}])
ok("B7 'none': picked row has a score breakdown", bool(gt._rows_data) and bool(gt._rows_data[0].get("_score_parts")))
shown = []
G.show_score_breakdown = lambda parent, rec: shown.append(rec["id"])
gt._on_cell_clicked(0, 1)
ok("B7b click on the name opens the breakdown", shown == [OTHER])
d3 = G._ManualAddDialog(gt, exclude_ids=set()); d3._on_cell_clicked(0, 4)
ok("B7c manual-add: click on the score opens the breakdown", len(shown) == 2)

print("\nRESULT:", "ALL GROUP-REPORT TESTS PASS ✓" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
