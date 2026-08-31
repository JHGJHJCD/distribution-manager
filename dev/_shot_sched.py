# -*- coding: utf-8 -*-
"""צילום אימות לתזמון צינתוקים (#xi85i, v2.86): כפתור "תזמן שליחה", רצועת
"צינתוק מתוזמן" עם כפתור ביטול, שורת "מתוזמן" בהיסטוריה, ודיאלוג בחירת המועד."""
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
from datetime import datetime, timedelta, timezone

db.add_recipient({"full_name": "כהן יוסף", "phone1": "052-1234567",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 5})
db.add_recipient({"full_name": "לוי שרה", "phone1": "050-7654321",
                  "status": "פעיל", "frequency": "שבועי", "priority": 4, "souls": 3})
g = db.add_tzintuk_campaign("חלוקה של 26/08/2026", "2026-08-26", "1117319",
                            "camp-old", 47, device="מחשב המנהל")
db.update_tzintuk_campaign(g, 44, 3, "done")
# תזמון ממתין — sent_at עתידי כדי שהרצועה תוצג ושורת ההיסטוריה תסומן "מתוזמן".
future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
db.add_tzintuk_campaign("צינתוק מתוזמן — חלוקה של 02/09/2026", "2026-09-02",
                        "1117319", "777", 2, sent_at=future,
                        device="מחשב המנהל", status="scheduled")

from PyQt6.QtCore import Qt
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 1050)
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
tz_inner.grab().save(os.path.join(out, "sched_tab.png"))

from tabs.tzintukim import _ScheduleDialog
dlg = _ScheduleDialog(2, win)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.resize(420, 240)
dlg.show()
app.processEvents(); app.processEvents()
dlg.grab().save(os.path.join(out, "sched_dialog.png"))
print("done")
