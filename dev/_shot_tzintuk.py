# -*- coding: utf-8 -*-
"""צילום אימות ללשונית הצינתוקים (v2.81): רשימה מאוכלסת עם מוכנים, חריג בלי
מספר, חריג מספר-שבור, כפול-מספר, והיסטוריית קמפיין אחת. + פאנל ההגדרות."""
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

# Seed: regulars due this week with a mix of phone situations.
db.add_recipient({"full_name": "כהן יוסף", "phone1": "052-1234567",
                  "phone2": "053-9876543", "status": "פעיל", "frequency": "שבועי", "priority": 4,
                  "souls": 5})
db.add_recipient({"full_name": "לוי שרה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 3})
db.add_recipient({"full_name": "פרידמן משה", "phone1": "04-6543210",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 6})
db.add_recipient({"full_name": "אברהם דוד", "phone1": "",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 4})
db.add_recipient({"full_name": "מזרחי חיים", "phone1": "05-12",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 2})
db.add_recipient({"full_name": "מזרחי רבקה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 2})
g = db.add_tzintuk_campaign("חלוקה של 26/08/2026", "2026-08-26", "1117319",
                            "camp-old", 47, device="מחשב המנהל")
db.update_tzintuk_campaign(g, 44, 3, "done")

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
# QScrollArea content can paint empty in WA_DontShowOnScreen grabs (known trap)
# — grab the INNER widget directly for a clean render.
tz_inner = win.tzintukim_tab.findChild(QScrollArea).widget()
tz_inner.grab().save(os.path.join(out, "tzintuk_tab.png"))

# Settings panel (scroll to the Yemot panel by grabbing the inner content).
win.navigate_to_tab(win.settings_tab)
for _ in range(4):
    app.processEvents()
inner = win.settings_tab.findChild(QScrollArea).widget()
inner.grab().save(os.path.join(out, "tzintuk_settings_full.png"))
print("done")
