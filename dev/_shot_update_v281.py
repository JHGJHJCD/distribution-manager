# -*- coding: utf-8 -*-
"""Visual check v2.81: restyled UpdateOfferDialog — formatted, right-aligned
release notes (one-line commit style → headline + bullets; multi-line bullets)
and the version pills with the arrow. Hebrew-safe capture (WA_DontShowOnScreen)."""
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

OUT = os.path.join(os.path.dirname(__file__), "shots_upd281")
os.makedirs(OUT, exist_ok=True)


def shot(w, name, w_px, h_px):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(w_px, h_px)
    w.show()
    app.processEvents(); app.processEvents()
    w.grab().save(os.path.join(OUT, name + ".png"))
    print("shot:", name)


from utils.ui import UpdateOfferDialog

# 1. One-line commit-style notes (the real v2.80 release message) — should render
#    as a bold headline + a green bullet per item, right-aligned.
one_line = ("גרסה 2.80 — דוח 30/08: גודל טקסט מיידי באחוזים, "
            "סטטוס סנכרון ויזואלי, הודעות למפתח בתוכנה, ביקורת מגבלות")
shot(UpdateOfferDialog(None, "2.81", "2.80", one_line), "01_one_line_notes", 480, 540)

# 2. Multi-line notes with dash bullets.
multi = "\n".join([
    "גרסה 2.81 — מה חדש:",
    "- חלון עדכון מעוצב מחדש עם פירוט שינויים מיושר לימין",
    "- התראת Windows קופצת כשיש עדכון גם כשהתוכנה פתוחה",
    "- בדיקת עדכונים אוטומטית כל שעה ברקע",
    "- שיפורי יציבות קטנים",
])
shot(UpdateOfferDialog(None, "2.81", "2.80", multi), "02_multi_line_notes", 480, 560)

print("DONE:", OUT)
