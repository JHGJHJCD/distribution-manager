# -*- coding: utf-8 -*-
"""משימה 11: כפתור 'בחר חד-פעמיים' לא מופיע כשאין מספיק מוצרים אפילו לקבועים
(האזהרה האדומה 'אין מספיק מוצרים' בלי כפתור לצידה); כן מופיע כשיש עודף.
offscreen, DB זמני.  הרצה: python test_onetime_button.py  (Python 3.12)"""
import os, sys, tempfile
from datetime import timedelta
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

for i in range(6):
    db.add_recipient({"full_name": f"כהן קבוע{i}", "status": "פעיל", "frequency": "שבועי",
                      "priority": 4, "souls": 3, "phone1": f"05{i}1111111"})
db.set_setting("dist_regulars_mode", "schedule")
from main import MainWindow
win = MainWindow()
gt = win.group_tab
gt.refresh(); gt._needs_refresh = False
regs = db.compute_suggested_n(100)[1]
ok("יש קבועים בתור השבוע", regs >= 2, str(regs))

def shown():
    return (not gt.leftover_card.isHidden()), (not gt.btn_pick_onetime.isHidden())

# פחות מוצרים מקבועים → אזהרה אדומה בלי כפתור
gt.products_spin.setValue(max(1, regs - 1))
gt._update_leftover_hint()
card, btn = shown()
ok("פחות מוצרים מקבועים: האזהרה מוצגת", card and "אין מספיק" in gt.lbl_leftover.text(), gt.lbl_leftover.text())
ok("פחות מוצרים מקבועים: הכפתור 'בחר חד-פעמיים' מוסתר", not btn)

# יותר מוצרים מקבועים → הכפתור חוזר
gt.products_spin.setValue(regs + 3)
gt._update_leftover_hint()
card, btn = shown()
ok("עודף מוצרים: הכרטיס והכפתור מוצגים", card and btn, gt.lbl_leftover.text())

# שוב פחות → שוב מוסתר (אין "דליפת מצב")
gt.products_spin.setValue(max(1, regs - 1))
gt._update_leftover_hint()
ok("חזרה לפחות מוצרים: הכפתור מוסתר שוב", not shown()[1])

# בדיוק כמספר הקבועים → "מספיק לקבועים בלבד" (לא האזהרה)
gt.products_spin.setValue(regs)
gt._update_leftover_hint()
ok("בדיוק כמספר הקבועים: אין אזהרה אדומה", "אין מספיק" not in gt.lbl_leftover.text(), gt.lbl_leftover.text())

# משימה 12: הרמז משקף את השער — 0 בחירות = "לחץ", אחרי >=1 = אפשר להדפיס (בלי "לחץ")
gt.products_spin.setValue(regs + 5)
gt._extra_ids = set(); gt._reserve_ids = set(); gt._persist_extras()
gt._update_leftover_hint()
t0 = gt.lbl_leftover.text()
ok("0 בחירות: הרמז מבקש ללחוץ 'בחר חד-פעמיים'", "לחץ" in t0, t0)
ok("0 בחירות: ההדפסה חסומה (השער)", gt._one_time_remainder() > 0 and gt._main_pick_count() == 0)
gt._extra_ids = {10_001}
gt._update_leftover_hint()
t1 = gt.lbl_leftover.text()
ok("בחירה 1 מתוך 5: הרמז לא כותב 'לחץ' / 'טרם הושלם'", "לחץ" not in t1 and "טרם הושלם" not in t1, t1)
ok("בחירה 1 מתוך 5: הרמז אומר שאפשר להדפיס", "להדפיס" in t1, t1)
ok("בחירה 1 מתוך 5: הרמז מציג 1 מתוך 5", "1" in t1 and "5" in t1, t1)
ok("בחירה 1 מתוך 5: השער מתיר הדפסה", gt._one_time_gate_ok("הדפסה"))
# #szhaf (יהודה 7/10/2026): אחרי בחירה הכפתור נעלם לגמרי — משלימים דרך "＋ הוסף מקבל"
ok("בחירה 1 מתוך 5: הכפתור נעלם אחרי הבחירה (#szhaf)", gt.btn_pick_onetime.isHidden())
gt._extra_ids = {10_001 + i for i in range(5)}
gt._update_leftover_hint()
t5 = gt.lbl_leftover.text()
ok("כל 5 נבחרו: 'נבחרו ✓' בלי 'לחץ'", "✓" in t5 and "לחץ" not in t5, t5)
gt._extra_ids = set()

# משימה 13: קבוע שלא בתורו שנוסף ידנית תופס מקום — "נשאר" יורד, ולא נספר כבחירת חד-פעמי
import selection
db.add_recipient({"full_name": "לוי דו-שבועי", "status": "פעיל", "frequency": "דו-שבועי",
                  "priority": 4, "souls": 3, "phone1": "0521111119",
                  "last_distribution": (selection.upcoming_wednesday() - timedelta(days=7)).isoformat()})
bi = [r for r in db.get_all_recipients() if r["full_name"] == "לוי דו-שבועי"][0]["id"]
gt._extra_ids = set(); gt._reserve_ids = set(); gt._persist_extras()
gt.products_spin.setValue(regs + 5)
gt.refresh()
ok("לפני ההוספה: נשאר 5", gt._one_time_remainder() == 5, str(gt._one_time_remainder()))
gt._extra_ids = {bi}; gt._reserve_ids = set(); gt._persist_extras()
gt.refresh()
ok("דו-שבועי שלא בתורו נוסף ידנית: נשאר 4", gt._one_time_remainder() == 4, str(gt._one_time_remainder()))
ok("הקבוע הידני לא נספר כבחירת חד-פעמי", gt._main_pick_count() == 0, str(gt._main_pick_count()))
t = gt.lbl_leftover.text()
ok("הרמז מציג 'נשאר לחד-פעמיים: 4'", "נשאר לחד-פעמיים: 4" in t, t)
ok("השער עדיין חוסם (טרם נבחר חד-פעמי אמיתי)", gt._one_time_remainder() > 0 and not gt._one_time_gate_ok("הדפסה"))
gt.products_spin.setValue(regs + 1)
gt.refresh()
ok("מוצרים בדיוק לקבועים + הידני: 'מספיק' בלי אזהרה אדומה",
   "מספיק" in gt.lbl_leftover.text() and "אין מספיק" not in gt.lbl_leftover.text(), gt.lbl_leftover.text())
gt.products_spin.setValue(regs)
gt.refresh()
ok("מוצרים רק לקבועים והידני עודף: אזהרה", "⚠" in gt.lbl_leftover.text(), gt.lbl_leftover.text())
gt._extra_ids = set(); gt._reserve_ids = set(); gt._persist_extras()
gt.refresh()

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL ONE-TIME BUTTON CHECKS PASS ✓")
sys.exit(1 if fails else 0)
