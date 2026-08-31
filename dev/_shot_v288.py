# -*- coding: utf-8 -*-
"""צילומי אימות ל-v2.88: (1) לשונית צינתוקים — כל המספרים לכל מקבל, בלי קומבו,
כפול-בין-משפחות מסונן; (2) מצב רשימה-מחלוקה-קודמת (#9hgvi) עם רצועת החזרה;
(3) פאנל ההגדרות בלי שדה מספר-הבדיקה (#dx28e)."""
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

db.add_recipient({"full_name": "כהן יוסף", "phone1": "052-1234567",
                  "phone2": "053-9876543", "phone3": "04-6000000",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 5})
db.add_recipient({"full_name": "לוי שרה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 3})
db.add_recipient({"full_name": "אברהם דוד", "phone1": "",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 4})
db.add_recipient({"full_name": "מזרחי חיים", "phone1": "05-12",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 2})
db.add_recipient({"full_name": "מזרחי רבקה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 2})
g = db.add_tzintuk_campaign("חלוקה של 26/08/2026", "2026-08-26", "1117319",
                            "camp-old", 47, device="מחשב המנהל")
db.update_tzintuk_campaign(g, 44, 3, "done")

# חלוקה קודמת עם רישומים — למצב הרשימה-מחלוקה (#9hgvi)
recs = db.get_all_recipients()
batch_id = db.bulk_add_distributions(
    [dict(r) for r in recs[:3]],
    "2026-08-19", "", 1, "מחלק", dist_name="חלוקת חבילות ראש השנה")

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
tz_inner = win.tzintukim_tab.findChild(QScrollArea).widget()
tz_inner.grab().save(os.path.join(out, "v288_tzintuk_week.png"))

# מצב חלוקה קודמת
batch = [b for b in db.get_distribution_batches() if b["id"] == batch_id][0]
win.tzintukim_tab.load_batch(batch)
for _ in range(6):
    app.processEvents()
tz_inner.grab().save(os.path.join(out, "v288_tzintuk_batch.png"))
win.tzintukim_tab._clear_batch()

# הגדרות — פאנל הצינתוקים בלי "מספר לבדיקות"
win.navigate_to_tab(win.settings_tab)
for _ in range(4):
    app.processEvents()
inner = win.settings_tab.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "v288_settings.png"))
print("done")
