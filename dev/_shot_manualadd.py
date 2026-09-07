# -*- coding: utf-8 -*-
"""Verify _ManualAddDialog: default 'כולם' shows the whole roster (#bsv8c),
'כל העדיפויות' only tiered people, and hide_frequencies (mode 'בלי קבועים',
#lsyyv) drops weekly/bi-weekly regulars but keeps monthly + everyone else."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
seed = [
    ("קבוע שבועי", 4, "שבועי", "פעיל"),
    ("קבוע דו-שבועי", 4, "דו-שבועי", "פעיל"),
    ("קבוע חודשי", 4, "חודשי", "פעיל"),
    ("ראשונה חדפ", 3, "חד-פעמי", "פעיל"),
    ("שנייה חדפ", 2, "חד-פעמי", "פעיל"),
    ("נתונים בלבד 1", 1, "", "פעיל"),
    ("נתונים בלבד 0", 0, "", "פעיל"),
    ("בירור", None, "", "לא פעיל"),
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

def names(dlg):
    return sorted(dlg._table.item(i, 0).text() for i in range(dlg._table.rowCount()))

all_names = sorted(n for n, *_ in seed)
dlg = _ManualAddDialog()
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.show(); app.processEvents()
assert dlg._prio_filter.currentText() == "כולם", dlg._prio_filter.currentText()
assert names(dlg) == all_names, names(dlg)
dlg._prio_filter.setCurrentText("כל העדיפויות"); app.processEvents()
assert names(dlg) == sorted(n for n, pr, *_ in seed if pr in (2, 3, 4)), names(dlg)
dlg._prio_filter.setCurrentText("ללא עדיפות"); app.processEvents()
assert names(dlg) == sorted(n for n, pr, *_ in seed if pr not in (2, 3, 4)), names(dlg)
dlg._prio_filter.setCurrentText("כולם"); app.processEvents()
OUT = os.path.join(os.path.dirname(__file__), "shots_sync")
os.makedirs(OUT, exist_ok=True)
dlg.grab().save(os.path.join(OUT, "manualadd.png"))

# mode 'בלי קבועים'
dlg2 = _ManualAddDialog(hide_frequencies=_ManualAddDialog.HIDE_FREQ_NO_REGULARS)
dlg2.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg2.show(); app.processEvents()
exp = sorted(n for n, pr, fr, _ in seed if not (pr == 4 and fr in ("שבועי", "דו-שבועי")))
assert names(dlg2) == exp, names(dlg2)
assert "קבוע חודשי" in names(dlg2)
dlg2._prio_filter.setCurrentText("קבוע"); app.processEvents()
assert names(dlg2) == ["קבוע חודשי"], names(dlg2)
dlg2._prio_filter.setCurrentText("כולם"); app.processEvents()
assert dlg2._hidden_count == 2 and "בלי 2 קבועים" in dlg2._lbl_count.text(), dlg2._lbl_count.text()
assert dlg._hidden_count == 0 and "מוסתרים" not in dlg._lbl_count.text(), dlg._lbl_count.text()
dlg2.grab().save(os.path.join(OUT, "manualadd_none.png"))
print("OK: default=all", len(all_names), "| none-mode shows", len(exp))
