# -*- coding: utf-8 -*-
"""Visual check (v2.96): the classic-tzintuk live callback-watch strip —
workers are stubbed, states are fed straight into _on_cb_tick."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
try:
    from qt_material import apply_stylesheet
    from styles import EXTRA_QSS, QT_MATERIAL_EXTRA
    apply_stylesheet(app, theme="light_teal.xml", invert_secondary=True, extra=QT_MATERIAL_EXTRA)
    app.setStyleSheet(app.styleSheet() + EXTRA_QSS)
except Exception:
    pass
app.setFont(QFont("Segoe UI", 11))

OUT = os.path.join(os.path.dirname(__file__), "shots_classic_track")
os.makedirs(OUT, exist_ok=True)

import tabs.tzintukim as tz
tz._CallbackWorker.start = lambda self: None   # no network / thread

tab = tz.TzintukimTab()
tab.resize(1150, 900)
# a fake loaded standalone list so the table has rows
tab._free = [("0521111222", "משפחת כהן"), ("0533334444", "משפחת לוי"),
             ("0541112223", "משפחת מזרחי")]
tab.refresh()

targets = {"0521111222": "משפחת כהן", "0533334444": "משפחת לוי",
           "0541112223": "משפחת מזרחי"}
tab._active_guid = ""            # no DB writes in the probe
tab._start_callback_tracking("", targets, 10**12)

ENT = [
    {"phone": "0521111222", "name": "משפחת כהן", "status": "accepted",
     "ok": True, "confirmed": True, "failed": False},
    {"phone": "0533334444", "name": "משפחת לוי", "status": "callback",
     "ok": True, "confirmed": False, "failed": False},
    {"phone": "0541112223", "name": "משפחת מזרחי", "status": "no_callback",
     "ok": False, "confirmed": False, "failed": False},
]

tab._on_cb_tick({"returned": 2, "confirmed": 1, "entries": ENT, "changed": True,
                 "remaining": 17 * 60, "done": False, "error": ""})
tab.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
tab.show()
app.processEvents(); app.processEvents()
tab.grab().save(os.path.join(OUT, "01_live.png"))

tab._on_cb_tick({"returned": 2, "confirmed": 1, "entries": ENT, "changed": False,
                 "remaining": 0, "done": True, "error": ""})
app.processEvents(); app.processEvents()
tab.grab().save(os.path.join(OUT, "02_done.png"))

# settings checkbox shot
from tabs.settings import SettingsTab
st = SettingsTab()
st.resize(1150, 900)
st.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
st.show()
app.processEvents(); app.processEvents()
st.grab().save(os.path.join(OUT, "03_settings.png"))

print("DONE:", OUT)
