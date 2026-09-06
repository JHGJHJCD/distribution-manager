# -*- coding: utf-8 -*-
"""צילום אימות v3.26: חלון "אישור שליחה" נוקב איזו הקלטה תושמע + אזהרת
"ההודעה של הפעם הקודמת" + "ביטול" כברירת-מחדל; ושורת ההקלטה בלשונית."""
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
from utils import yemot
from datetime import datetime, timezone, timedelta

db.add_recipient({"full_name": "כהן יוסף", "phone1": "052-1234567",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 5})
db.add_recipient({"full_name": "לוי שרה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 3})
db.set_setting("yemot_system", "0771234567")
db.set_setting("yemot_password", "1234")
db.set_setting("yemot_template_id", "1430692")
yemot.set_recording_info("חלוקת פרשת נצבים", source="tts", device="מחשב המנהל")
g = db.add_tzintuk_campaign("חלוקה של 02/09/2026", "2026-09-02", "1430692", "camp-old", 47,
                            sent_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                            device="מחשב המנהל")
db.update_tzintuk_campaign(g, 44, 3, "done")
import time; time.sleep(1.2)

from PyQt6.QtCore import Qt
import tabs.tzintukim as tzmod
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 950)
win.show()
app.processEvents(); app.processEvents()
out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)
win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz._load_week_list()
for _ in range(6):
    app.processEvents()
tz.grab().save(os.path.join(out, "tzintuk_v326_tab.png"))

rows = tz._ready_rows()
phones = tz._phones_map(rows)
prev = tz._prev_campaign(tz._dist_date_iso())
summary = (f"{tz._campaign_name()}\n\n"
           f"עומד לשלוח צינתוק ל-{len(rows)} משפחות "
           f"({len(phones)} מספרי טלפון — כל המספרים של כל משפחה).\n"
           f"חריגים שלא יישלחו: 0."
           + tz._recording_lines() + "\n"
           + tz._callback_line() + "\n"
           f"מי שיחייג חזרה ויקיש {yemot.SURVEY_EXT} יסומן בתוכנה לפי "
           "תשובתו: 1 מגיע / 2 לא מגיע / 3 לא יודע; "
           f"מי שלא יקיש — \"לא הגיב\"." + tz._already_sent_line(prev))
dlg = tzmod._SendModeDialog(summary, tz)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.resize(640, 420)
dlg.show()
for _ in range(6):
    app.processEvents()
dlg.grab().save(os.path.join(out, "tzintuk_v326_confirm.png"))
print("default=cancel:", dlg.btn_cancel.isDefault(), "ok default:", dlg.btn_ok.isDefault())
print("done")
