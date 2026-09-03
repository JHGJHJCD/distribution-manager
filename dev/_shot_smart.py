# -*- coding: utf-8 -*-
"""צילום אימות לשיגור החכם (#y7jr0 שלב 2): הכפתור החדש "שגר לפי השעה של כל
אחד" בסרגל התחתון, ודיאלוג בחירת יום החלוקה עם פירוט קבוצות-השעה."""
import os, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shot)

app, win = shot.boot()
import database as db

for i, (nm, ph) in enumerate([("כהן יוסף", "052-1234567"),
                              ("לוי שרה", "050-7654321"),
                              ("מזרחי דוד", "053-9998877"),
                              ("פרץ רבקה", "054-1112233")]):
    db.add_recipient({"full_name": nm, "phone1": ph, "status": "פעיל",
                      "frequency": "שבועי", "priority": 4, "souls": 3 + i})

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 1050)
win.show()
app.processEvents(); app.processEvents()

out = os.path.join(REPO, "dev", "shots_smart")
os.makedirs(out, exist_ok=True)

win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz._list_loaded = True
tz.refresh()
for _ in range(6):
    app.processEvents()
tz_inner = tz.findChild(QScrollArea).widget()
tz_inner.grab().save(os.path.join(out, "smart_tab.png"))

# הדיאלוג עם קבוצות שעה לדוגמה
from tabs.tzintukim import _SmartScheduleDialog
buckets = {8: {"05a": "א", "05b": "ב"}, 10: {"05c": "ג"},
           13: {"05d": "ד", "05e": "ה", "05f": "ו"}, 19: {"05g": "ז", "05h": "ח"}}
n_personal = 6
n_fallback = 2
dlg = _SmartScheduleDialog(buckets, 13, n_personal, n_fallback, win)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.resize(460, 520)
dlg.show()
app.processEvents(); app.processEvents()
dlg.grab().save(os.path.join(out, "smart_dialog.png"))
print("done")
