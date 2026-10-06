# -*- coding: utf-8 -*-
"""משימה 5 (6/10/2026): מצב החלוקה תמיד נפתח על "לפי לוח זמנים".
בכל הפעלה של התוכנה המצב חוזר ל'רגיל'; מצב אחר נבחר רק לחלוקה הנוכחית ושורד רענונים
באמצע העבודה; והמצב הוא פר-מחשב (לא מסונכרן) כדי שהמחשב השני לא יחזיר מצב ישן.
offscreen, DB זמני."""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8"); sys.path.insert(0, ".")
import database as db
db.DB_PATH = tempfile.mkstemp(suffix=".db")[1]; db.BACKUP_DIR = tempfile.mkdtemp(); db.init_db()
from PyQt6.QtWidgets import QApplication, QMessageBox
for _m in ("information", "warning", "critical"):
    setattr(QMessageBox, _m, staticmethod(lambda *a, **k: None))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
app = QApplication(sys.argv)

fails = []
def ok(name, cond, extra=""):
    print(("  OK  " if cond else "  ✗   ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)

for i in range(3):
    db.add_recipient({"full_name": f"כהן קבוע{i}", "status": "פעיל", "frequency": "שבועי",
                      "priority": 4, "souls": 3, "phone1": f"05{i}1111111", "income": "1000"})

# ── M1: הפעלה אחרי שהמצב נשמר כ'לפי ניקוד' (מהפעלה קודמת / מהמחשב השני) ───────────
db.set_setting("dist_regulars_mode", "scored")
from main import MainWindow
win = MainWindow()
gt = win.group_tab
ok("M1a startup: combo opens on 'schedule'", gt._current_mode() == "schedule", gt._current_mode())
ok("M1b startup: the stored mode is 'schedule' too (all consumers agree)",
   db.get_regulars_mode() == "schedule", db.get_regulars_mode())
ok("M1c startup: the advanced fold stays closed in the ordinary mode",
   not gt.adv_section.header.isChecked())

# ── M2: מצב שנבחר לחלוקה הנוכחית שורד רענון / חזרה ללשונית / refresh_all ──────────
gt.mode_combo.setCurrentIndex(gt.mode_combo.findData("scored"))
ok("M2a picking 'scored' sticks for the current round", gt._current_mode() == "scored")
gt.refresh(); win.refresh_all(); gt.refresh()
win.navigate_to_tab(win.recipients_tab); win.navigate_to_tab(gt)
ok("M2b refresh / refresh_all / tab hop keep the picked mode",
   gt._current_mode() == "scored" and db.get_regulars_mode() == "scored",
   f"{gt._current_mode()} / {db.get_regulars_mode()}")

# ── M3: המצב אינו מסונכרן — המחשב השני לא יכול להחזיר אותו ───────────────────────
from utils import sync
ok("M3a the mode is not a synced setting", not sync._setting_syncable("dist_regulars_mode"))
ok("M3b other settings still sync", sync._setting_syncable("available_products")
   and sync._setting_syncable("dist_filter_criteria"))
db.set_setting("dist_regulars_mode", "scored")
conn_rec = {"key": "dist_regulars_mode", "value": "none", "ts": "2999-01-01T00:00:00Z"}
import sqlite3
_c = sqlite3.connect(db.DB_PATH)
try:
    sync._apply_setting(_c, conn_rec, {})
    _c.commit()
finally:
    _c.close()
ok("M3c an incoming journal record for the mode is ignored", db.get_setting("dist_regulars_mode") == "scored",
   str(db.get_setting("dist_regulars_mode")))

# ── M4: 'סינון מותאם' + חג שנשארו שמורים — בהפעלה הבאה המסך על 'רגיל' והחג לא פעיל ──
db.set_filter_criteria({"children_total": {"min": 2, "max": None}, "holiday": "פסח"})
db.set_setting("dist_regulars_mode", "filter")
win2 = MainWindow()
gt2 = win2.group_tab
ok("M4a restart with a saved filter mode: back to 'schedule'", gt2._current_mode() == "schedule",
   gt2._current_mode())
ok("M4b the saved holiday is inert outside the filter mode", gt2._active_holiday() == "")
ok("M4c the weekly list is the plain schedule list (3 regulars, no holiday gate)",
   len(gt2._rows_data) == 3, str(len(gt2._rows_data)))
ok("M4d the saved thresholds are kept for the next time filter is chosen",
   (db.get_filter_criteria().get("children_total") or {}).get("min") == 2
   and db.get_filter_criteria().get("holiday") == "פסח", str(db.get_filter_criteria()))
ok("M4e a leftover filter doesn't force the advanced fold open in 'schedule'",
   not gt2._special_active(), str(gt2._special_active()))

# ── M5: ערך ישן 'all' ממופה ל-schedule בהפעלה ────────────────────────────────────
db.set_setting("dist_regulars_mode", "all")
win3 = MainWindow()
ok("M5 legacy 'all' opens as 'schedule'", win3.group_tab._current_mode() == "schedule")

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("ALL MODE-RESET CHECKS PASS ✓"); sys.exit(0)
