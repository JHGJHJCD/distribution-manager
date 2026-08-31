# -*- coding: utf-8 -*-
"""צילום אימות לאישורי ההגעה בצינתוק (v2.85): היסטוריה עם עמודת "אישרו הגעה",
טיפ ההקלטה (מקש 7), ותג "✓ אישר הגעה" במסך "חלוקה ורישום"."""
import os, sys, json, importlib.util

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
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 5})
db.add_recipient({"full_name": "לוי שרה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 3})
db.add_recipient({"full_name": "פרידמן משה", "phone1": "04-6543210",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 6})

# קמפיין של החלוקה הנוכחית, שהסתיים — יוסף אישר (7), שרה קיבלה, משה נכשל.
dist_date = db.next_wednesday().isoformat()
report = json.dumps([
    {"phone": "0521234567", "name": "כהן יוסף", "status": "accepted",
     "ok": True, "confirmed": True, "failed": False},
    {"phone": "0507654321", "name": "לוי שרה", "status": "done",
     "ok": True, "confirmed": False, "failed": False},
    {"phone": "046543210", "name": "פרידמן משה", "status": "no_answer",
     "ok": False, "confirmed": False, "failed": True},
], ensure_ascii=False)
g = db.add_tzintuk_campaign(f"חלוקה של {db.next_wednesday().strftime('%d/%m/%Y')}",
                            dist_date, "1117319", "camp-1", 3, device="מחשב המנהל")
db.update_tzintuk_campaign(g, 2, 1, "done", report)
db.set_setting("yemot_system", "0771234567")
db.set_setting("yemot_password", "123456")
db.set_setting("yemot_template_id", "1117319")

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
tz_inner.grab().save(os.path.join(out, "tzintuk_confirm_tab.png"))

# מסך "חלוקה ורישום" — התג הירוק ליד כהן יוסף.
win.navigate_to_tab(win.group_tab)
win.group_tab.refresh()
for _ in range(6):
    app.processEvents()
win.group_tab.grab().save(os.path.join(out, "tzintuk_confirm_dist.png"))
print("done")
