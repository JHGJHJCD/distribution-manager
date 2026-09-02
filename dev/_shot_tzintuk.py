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

win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz.refresh()
for _ in range(6):
    app.processEvents()
# Whole tab (scroll body + sticky bottom bar) — empty / not-configured state.
tz.grab().save(os.path.join(out, "tzintuk_tab.png"))

# Loaded state: configured line, week list loaded, a schedule waiting and a
# live-progress strip — every strip of the bottom bar visible at once.
db.set_setting("yemot_system", "0771234567")
db.set_setting("yemot_password", "1234")
db.set_setting("yemot_template_id", "1430692")
tz._load_week_list()
tz.lbl_sched.setText("🕒 צינתוק מתוזמן ל-03/09/2026 · 10:00 — ל-5 נמענים. "
                     "המחשב לא חייב להיות דלוק בשעת השליחה.")
tz.sched_frame.setVisible(True)
tz.prog_frame.setVisible(True)
tz.lbl_prog.setText("שולח בזמן אמת… אפשר להמשיך לעבוד, אל תסגור את התוכנה")
tz.progress.setRange(0, 5); tz.progress.setValue(3)
tz.lbl_conf.setText("✓ אישרו הגעה 1"); tz.lbl_done.setText("הצליחו 3")
tz.lbl_fail.setText("נכשלו 0"); tz.lbl_wait.setText("ממתינים 2")
for _ in range(6):
    app.processEvents()
tz.grab().save(os.path.join(out, "tzintuk_tab_loaded.png"))
print("done")
