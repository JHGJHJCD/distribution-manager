# -*- coding: utf-8 -*-
"""Verify _ManualAddDialog default 'כל העדיפויות' shows only tiered recipients."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
seed = [
    ("קבוע רגיל", 4, "שבועי", "פעיל"),
    ("ראשונה חדפ", 3, "חד-פעמי", "פעיל"),
    ("שנייה חדפ", 2, "חד-פעמי", "פעיל"),
    ("נתונים בלבד 1", 1, "", "פעיל"),
    ("נתונים בלבד 0", 0, "", "פעיל"),
    ("בירור", None, "", "פעיל"),
]
for name, pr, freq, st in seed:
    rec = {"full_name": name, "status": st, "income": "1500", "children_total": 3,
           "phone1": "0500000000", "area": "הר יונה", "frequency": freq}
    if pr is not None:
        rec["priority"] = pr
    db.add_recipient(rec)

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

from tabs.group_update import _ManualAddDialog
dlg = _ManualAddDialog()
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show(); app.processEvents()

# Report what rows the default filter shows
names = [dlg._table.item(i, 0).text() for i in range(dlg._table.rowCount())]
print("DEFAULT (כל העדיפויות):", names)
# Switch to 'ללא עדיפות'
dlg._prio_filter.setCurrentText("ללא עדיפות"); app.processEvents()
names2 = [dlg._table.item(i, 0).text() for i in range(dlg._table.rowCount())]
print("ללא עדיפות:", names2)

dlg._prio_filter.setCurrentText("כל העדיפויות"); app.processEvents()
OUT = os.path.join(os.path.dirname(__file__), "shots_sync")
os.makedirs(OUT, exist_ok=True)
dlg.grab().save(os.path.join(OUT, "manualadd.png"))
print("saved")
