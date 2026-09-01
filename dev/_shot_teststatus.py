# -*- coding: utf-8 -*-
"""Visual check: live test-call status dialog (_TestStatusDialog) — the poll
worker is stubbed so no network is touched; each state is fed via _on_tick."""
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

OUT = os.path.join(os.path.dirname(__file__), "shots_teststatus")
os.makedirs(OUT, exist_ok=True)

import tabs.tzintukim as tz
tz._PollWorker.start = lambda self: None      # no network in the probe

def st(status, ok=False, confirmed=False, failed=False, finished=False, entries=True):
    ent = [{"phone": "0501234567", "name": "בדיקה", "status": status,
            "ok": ok, "confirmed": confirmed, "failed": failed}] if entries else []
    return {"finished": finished, "total": 1, "delivered": int(ok),
            "confirmed": int(confirmed), "failed": int(failed),
            "pending": 0 if finished else 1, "entries": ent}

cases = [
    ("01_ringing",   st("", entries=False)),
    ("02_answered",  st("up", ok=True)),
    ("03_confirmed", st("accepted", ok=True, confirmed=True, finished=True)),
    ("04_no_answer", st("no_answer", failed=True, finished=True)),
]
for name, s in cases:
    dlg = tz._TestStatusDialog("camp-test", "0501234567")
    dlg._on_tick(s)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dlg.show()
    app.processEvents(); app.processEvents()
    dlg.grab().save(os.path.join(OUT, name + ".png"))
    dlg.close()
    print("shot:", name)

print("DONE:", OUT)
