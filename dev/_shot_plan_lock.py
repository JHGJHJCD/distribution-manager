# -*- coding: utf-8 -*-
"""הכנה קדימה, נעילה (19/10/2026): צילומי מסך החלוקה — רשימה נעולה (באנר, צ'יפ, כפתור 'בטל נעילה'),
תחזית לא נעולה עם אזהרת 'שבוע שלפני לא נעול', ו'חלון התכנונים'. בלי offscreen, DB זמני.
לאמת את ה-PNG דרך gemini_task.py -f — לא Read (מלכודת נטפרי)."""
import os, sys
from datetime import timedelta
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, ".claude", "skills", "visual-check", "scripts"))
from shot import boot
import database as db
import selection
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox, QDialog

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)

app, win = boot()
import tabs.group_update as gu
gu.OneTimePickerDialog.exec = lambda self: QDialog.DialogCode.Accepted   # הצעת החד-פעמיים מאושרת
wed = selection.upcoming_wednesday()
FAM = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "דהן", "אברהם", "פרידמן", "מלכה", "אזולאי"]
n = 0
for freq, count, weeks_ago in (("שבועי", 6, 2), ("דו-שבועי", 4, 2), ("חודשי", 3, 5)):
    for i in range(count):
        db.add_recipient({"full_name": f"{FAM[n % 10]} משפחה{n + 1}", "phone1": f"05012345{n:02d}",
                          "status": "פעיל", "priority": 4, "frequency": freq, "souls": 3 + n % 5,
                          "last_distribution": (wed - timedelta(days=7 * weeks_ago)).isoformat()})
        n += 1
db.set_setting("dist_regulars_mode", "schedule")
db.set_setting("available_products", "14")
db.set_setting("reserve_count", "2")
tab = {t.objectName(): t for t in win._leaf_tabs}["tab_dist"]
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 900); win.show(); app.processEvents()
win.navigate_to_tab(tab); QTest.qWait(450)
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)


def shot(name):
    for _ in range(6):
        app.processEvents()
    QTest.qWait(300)
    p = os.path.join(out, name + ".png")
    win.grab().save(p)
    print(name, os.path.getsize(p), "|", tab.lbl_plan_banner.text() if tab._plan_mode() else tab.lbl_future_note.text())


tab.refresh()
shot("plan_lock_0_unlocked")
tab._lock_plan()                                   # נעילת השבוע הנוכחי
shot("plan_lock_1_locked_current")
tab.date_edit.set_from_iso((wed + timedelta(days=7)).isoformat())
shot("plan_lock_2_forecast_locked_week_before")    # התחזית ל-+7: שבוע לפניה נעול ← בלי אזהרה
db_week = wed + timedelta(days=14)
tab.date_edit.set_from_iso(db_week.isoformat())
shot("plan_lock_3_forecast_warn")                  # +14: השבוע שבאמצע לא נעול ← אזהרה
tab.date_edit.set_from_iso((wed + timedelta(days=7)).isoformat())
tab._lock_plan()                                   # נעילת התחזית
shot("plan_lock_4_locked_forecast")
from tabs.plan_lock import PlansDialog
dlg = PlansDialog(tab)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.resize(820, 360); dlg.show()
for _ in range(6):
    app.processEvents()
dlg.grab().save(os.path.join(out, "plan_lock_5_plans_dialog.png"))
print("done")
