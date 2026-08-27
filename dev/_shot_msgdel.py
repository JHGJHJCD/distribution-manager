# -*- coding: utf-8 -*-
"""Visual check: message-delete button on own bubbles + resizable update dialog
with a long, fully-visible changelog. Hebrew-safe capture (WA_DontShowOnScreen)."""
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

OUT = os.path.join(os.path.dirname(__file__), "shots_msgdel")
os.makedirs(OUT, exist_ok=True)


def shot(w, name, w_px, h_px):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(w_px, h_px)
    w.show()
    app.processEvents(); app.processEvents()
    w.grab().save(os.path.join(OUT, name + ".png"))
    print("shot:", name)


# ── Messages tab: mix of my own + a teammate's message ────────────────────────
from utils import sync
me = sync.device_id()
db.add_message("שלום, מתי החלוקה השבוע?", author_name="מזכירה", author_device="dev-other")
db.add_message("ביום רביעי כרגיל, בשעה 18:00", author_name="מנהל", author_device=me)
db.add_message("מעולה, תודה! אעדכן את המתנדבים.", author_name="מנהל", author_device=me)

from tabs.messages import MessagesTab
mt = MessagesTab(None)
mt.refresh()
shot(mt, "01_messages_delete", 720, 560)

# ── Update dialog with a long changelog (must be fully scrollable/visible) ─────
from utils.ui import UpdateOfferDialog
long_notes = "\n".join([
    "גרסה 2.80 — סיכום שינויים:",
    "• לשונית הודעות: אפשר עכשיו למחוק הודעה שכתבת (נמחקת גם אצל שאר הצוות).",
    "• חלון העדכון: מוצג כעת מלוא פירוט השינויים, עם גלילה, וניתן להגדיל את החלון.",
    "• שיפורי יציבות בסנכרון בין המחשבים.",
    "• תיקוני עיצוב קטנים במסך החלוקה.",
    "• שיפור מהירות טעינת רשימת המקבלים.",
    "• תיקון תצוגת תאריכים בדוח החלוקות.",
    "• עדכון טקסטים והבהרות בכפתורים.",
    "• שיפורים בזרימת המתנדבים (ייצוא/ייבוא אקסל).",
    "• תיקון באזור ההגדרות המתקדמות.",
    "• שיפורי נגישות RTL נוספים.",
    "• הכנות לגרסה הבאה.",
])
dlg = UpdateOfferDialog(None, "2.80", "2.79", long_notes)
shot(dlg, "02_update_dialog", 480, 560)

print("DONE:", OUT)
