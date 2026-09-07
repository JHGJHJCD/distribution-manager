# -*- coding: utf-8 -*-
"""RecipientDialog with priority 'קבוע' → frequency combo shows תלת-שבועי."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
app = QApplication(sys.argv); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
try:
    from qt_material import apply_stylesheet
    from styles import EXTRA_QSS, QT_MATERIAL_EXTRA
    apply_stylesheet(app, theme="light_teal.xml", invert_secondary=True, extra=QT_MATERIAL_EXTRA)
    app.setStyleSheet(app.styleSheet() + EXTRA_QSS)
except Exception:
    pass
app.setFont(QFont("Segoe UI", 11))
from tabs.recipients import RecipientDialog
dlg = RecipientDialog(None, {"full_name": "כהן ישראל", "priority": 4, "frequency": "תלת-שבועי",
                             "status": "פעיל", "last_distribution": "2026-09-02"})
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); dlg.resize(640, 820); dlg.show(); app.processEvents()
items = [dlg.f_freq.itemText(i) for i in range(dlg.f_freq.count())]
print("items:", items, "| current:", dlg.f_freq.currentText())
assert "תלת-שבועי" in items and dlg.f_freq.currentText() == "תלת-שבועי"
app.processEvents()
OUT = os.path.join(os.path.dirname(__file__), "shots_sync"); os.makedirs(OUT, exist_ok=True)
dlg.grab().save(os.path.join(OUT, "recip_freq.png"))

print("OK")
r = dlg.f_freq.rect(); tl = dlg.f_freq.mapTo(dlg, r.topLeft()); br = dlg.f_freq.mapTo(dlg, r.bottomRight())
print("dialog:", dlg.size(), "| freq field in dialog coords:", tl, br, "| visibleRegion:", dlg.f_freq.visibleRegion().boundingRect())
