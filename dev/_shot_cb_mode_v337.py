# -*- coding: utf-8 -*-
"""צילום אימות v3.37 — חלון אישור השליחה עם בחירת "מה ישמע מי שיחייג חזרה לקו".
DB זמני (shot.boot), בלי רשת. אימות רק דרך gemini_task.py -f (לא Read)."""
import os, sys, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location(
    "shot", os.path.join(REPO, ".claude", "skills", "visual-check", "scripts", "shot.py"))
shot = importlib.util.module_from_spec(spec); spec.loader.exec_module(shot)
app, win = shot.boot()
import json
import database as db
from utils import callback_server as cb, yemot
db.set_setting("yemot_system", "0771234567"); db.set_setting("yemot_password", "1234")
db.set_setting(cb.SET_SECRET, "x"); db.set_setting(cb.SET_ENABLED, "1")
db.set_setting(yemot.SET_REC_INFO, json.dumps({"name": "הודעת חלוקה", "at": "2026-09-10T10:00:00+00:00"}))
db.set_setting(cb.SET_REC_STAMP, "2026-09-10T10:00:00+00:00")
from PyQt6.QtCore import Qt
import tabs.tzintukim as tz
out = os.path.join(REPO, "dev", "_shots"); os.makedirs(out, exist_ok=True)

dlg = tz._SendModeDialog("חלוקת פרשת נצבים\n\nעומד לשלוח צינתוק ל-12 משפחות (15 מספרי טלפון).", None)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show()
for _ in range(6): app.processEvents()
assert dlg.cb_box.isVisible() and dlg.cb_box.mode == "both"
dlg.grab().save(os.path.join(out, "cb_mode_v337_send.png"))
dlg.cb_box._buttons["message"].setChecked(True)
dlg._accept()
assert dlg.cb_mode == "message" and cb.last_mode() == "message", (dlg.cb_mode, cb.last_mode())

sd = tz._ScheduleDialog(12, None)
sd.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
sd.show()
for _ in range(6): app.processEvents()
assert sd.cb_box.mode == "message", "last choice not remembered"
sd.grab().save(os.path.join(out, "cb_mode_v337_sched.png"))

# server off → box hidden, mode None
db.set_setting(cb.SET_ENABLED, "0")
d2 = tz._SendModeDialog("x", None)
assert not d2.cb_box.isVisible() and d2.cb_box.mode is None
print("done")
