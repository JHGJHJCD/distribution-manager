# -*- coding: utf-8 -*-
"""צילום אימות ל-v3.22: צ'יפ חיבור חי, כפתור מיקרופון, "פירוט לפי שם ומספר",
כפתור "עצור שליחה" בזמן מעקב, ורצועת תזמון עם שני תזמונים ממתינים (שורה+ביטול
לכל אחד). + חלון ההקלטה + חלון הפירוט. אימות הצילומים רק דרך gemini_task.py -f."""
import os, sys, json, importlib.util
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shot)

app, win = shot.boot()
import database as db
import tabs.tzintukim as tzmod
from utils import yemot
tzmod._PollWorker.start = lambda self: None
tzmod._TaskWorker.start = lambda self: None

for nm, p1, p2 in (("כהן יוסף", "052-1234567", "053-9876543"), ("לוי שרה", "050-7654321", ""),
                   ("פרידמן משה", "04-6543210", ""), ("אברהם דוד", "", "")):
    db.add_recipient({"full_name": nm, "phone1": p1, "phone2": p2, "status": "פעיל",
                      "frequency": "שבועי", "priority": 4, "souls": 4})
db.set_setting("yemot_system", "0771234567")
db.set_setting("yemot_password", "1234")
db.set_setting("yemot_template_id", "1430692")
now = datetime.now(timezone.utc)
week = db.next_wednesday().isoformat()
g = db.add_tzintuk_campaign("חלוקה של 02/09/2026", "2026-09-02", "1430692", "camp-old", 4,
                            device="מחשב המנהל", sent_at=(now - timedelta(days=4)).isoformat())
db.update_tzintuk_campaign(g, 2, 1, "done", json.dumps([
    {"phone": "0521234567", "name": "כהן יוסף", "ok": True, "status": "done", "answer": "1",
     "answer_at": (now - timedelta(days=4, hours=-2)).isoformat()},
    {"phone": "0507654321", "name": "לוי שרה", "ok": True, "status": "amd", "answer": ""},
    {"phone": "0466543210", "name": "פרידמן משה", "failed": True, "status": "no_answer", "answer": ""},
    {"phone": "0539876543", "name": "כהן יוסף", "failed": True, "status": "busy", "answer": "2",
     "answer_at": (now - timedelta(days=3)).isoformat()}], ensure_ascii=False))
for i, (name, hrs, tid) in enumerate((("חלוקה של השבוע", 26, "5001"), ("רשימה עצמאית — 12 מספרים", 50, "5002"))):
    db.add_tzintuk_campaign(f"צינתוק מתוזמן — {name}", week if i == 0 else "", tid, f"s-{i}", 4 + i * 8,
                            sent_at=(now + timedelta(hours=hrs)).isoformat(),
                            device="מחשב המנהל" if i == 0 else "מחשב המזכירה", status="scheduled")

from PyQt6.QtCore import Qt
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 980)
win.show()
app.processEvents(); app.processEvents()
out = os.path.join(REPO, "dev", "_shots")
os.makedirs(out, exist_ok=True)

win.navigate_to_tab(win.tzintukim_tab)
tz = win.tzintukim_tab
tz._load_week_list()
tz._apply_conn_state({"ok": True, "units": 1834})
tz._refresh_sched_banner()
gl = db.add_tzintuk_campaign("חלוקה של השבוע", week, "1430692", "camp-live", 4, device="מחשב המנהל")
tz._active_guid = gl
tz._start_tracking("camp-live", 4, now.isoformat())
tz._on_tick({"finished": False, "total": 4, "delivered": 2, "failed": 0, "pending": 2,
             "entries": [], "answers": {"1": 1, "2": 0, "3": 0, "": 0}}, tz._worker)
for _ in range(8):
    app.processEvents()
tz.grab().save(os.path.join(out, "tzintuk_v322_tab.png"))

# חלון ההקלטה (בלי להקליט)
dlg = tzmod.RecordDialog(tz)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show(); app.processEvents(); app.processEvents()
dlg.grab().save(os.path.join(out, "tzintuk_v322_record.png"))
dlg.close()

# חלון הפירוט לפי שם ומספר
camp = db.get_tzintuk_campaign(g)
d2 = tzmod._HistoryDetailDialog(camp, tz._name_by_phone(), tz)
d2.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
d2.show(); app.processEvents(); app.processEvents()
d2.grab().save(os.path.join(out, "tzintuk_v322_detail.png"))
d2.close()
tz._retire_trackers()
print("done", out)
