# -*- coding: utf-8 -*-
"""Visual check (#7b5i3): closed priority-filter combo shows the badge colour."""
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

OUT = os.path.join(os.path.dirname(__file__), "shots_priofilter")
os.makedirs(OUT, exist_ok=True)

db.add_recipient({"full_name": "כהן אברהם", "phone1": "0501111111",
                  "priority": 3, "priority_raw": "3", "status": "פעיל"})
db.add_recipient({"full_name": "לוי יעקב", "phone1": "0502222222",
                  "priority": 4, "priority_raw": "4", "status": "פעיל"})

from tabs.recipients import RecipientsTab
rt = RecipientsTab(None)
rt.refresh()


def shot(name):
    rt.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    rt.resize(1200, 640)
    rt.show()
    app.processEvents(); app.processEvents(); app.processEvents()
    rt.grab().save(os.path.join(OUT, name + ".png"))
    print("shot:", name)


shot("00_all")
rt.priority_filter.setCurrentText("עדיפות ראשונה")
shot("01_rishona")
rt.priority_filter.setCurrentText("קבוע")
shot("02_kavua")
print("DONE:", OUT)
