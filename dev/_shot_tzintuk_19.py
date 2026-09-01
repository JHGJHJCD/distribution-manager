# -*- coding: utf-8 -*-
"""צילום אימות לדוח 1/9: (א) טבלת נמענים בגובה מלא + כפתורי סמן/נקה הכל,
(ב) מסך הטעינה עם כפתור הרשימה העצמאית, (ג) דיאלוג הרשימה העצמאית,
(ד) דיאלוג אישור השליחה עם בחירת צינתוק רגיל/קלאסי."""
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

for i in range(12):
    db.add_recipient({"full_name": f"משפחה {i+1:02d}", "phone1": f"052-12345{i:02d}",
                      "status": "פעיל", "frequency": "שבועי", "priority": 4,
                      "souls": 3 + (i % 4)})
db.add_recipient({"full_name": "אברהם דוד", "phone1": "",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 4})

from PyQt6.QtCore import Qt
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()

out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)

from PyQt6.QtWidgets import QScrollArea
win.navigate_to_tab(win.tzintukim_tab)
win.tzintukim_tab.refresh()
for _ in range(6):
    app.processEvents()
# מסך "לא נטען" — עם כפתור הרשימה העצמאית
inner = win.tzintukim_tab.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "tz19_unloaded.png"))

# טעינת הרשימה — טבלה בגובה מלא + כפתורי סמן/נקה
win.tzintukim_tab._load_week_list()
for _ in range(6):
    app.processEvents()
inner.grab().save(os.path.join(out, "tz19_loaded_full.png"))

# דיאלוג רשימה עצמאית עם תוכן מודבק
from tabs.tzintukim import _FreeListDialog, _SendModeDialog
dlg = _FreeListDialog(win.tzintukim_tab)
dlg.text.setPlainText("0501234567\tמשפחת כהן\n0521111222\n05-99\n0521111222")
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show()
for _ in range(4):
    app.processEvents()
dlg.grab().save(os.path.join(out, "tz19_freelist_dialog.png"))
dlg.close()

# דיאלוג אישור עם בחירת מצב
md = _SendModeDialog("חלוקה של 03/09/2026\n\nעומד לשלוח צינתוק ל-12 משפחות "
                     "(12 מספרי טלפון).\nחריגים שלא יישלחו: 1.", win.tzintukim_tab)
md.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
md.show()
for _ in range(4):
    app.processEvents()
md.grab().save(os.path.join(out, "tz19_sendmode_dialog.png"))
md.close()
print("done")
