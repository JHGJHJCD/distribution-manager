# -*- coding: utf-8 -*-
"""Visual check of the one-click SyncSetupDialog. Hebrew-safe grab()."""
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

from tabs.settings import SyncSetupDialog
OUT = os.path.join(os.path.dirname(__file__), "shots_sync")
os.makedirs(OUT, exist_ok=True)

dlg = SyncSetupDialog()
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show(); app.processEvents()
dlg.grab().save(os.path.join(OUT, "collapsed.png"))

dlg.btn_advanced.setChecked(True); app.processEvents()
dlg.grab().save(os.path.join(OUT, "expanded.png"))
print("saved to", OUT)
