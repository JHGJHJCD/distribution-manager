# -*- coding: utf-8 -*-
"""Visual check (#uvee0): chat wallpaper must actually paint behind the bubbles."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QImage, QColor, QPainter

import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.CHAT_BG_PATH = os.path.join(d, "chat_bg")
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

OUT = os.path.join(os.path.dirname(__file__), "shots_chatbg")
os.makedirs(OUT, exist_ok=True)


def shot(w, name, w_px, h_px):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.resize(w_px, h_px)
    w.show()
    app.processEvents(); app.processEvents(); app.processEvents()
    w.grab().save(os.path.join(OUT, name + ".png"))
    print("shot:", name)


# A loud test wallpaper (orange/blue gradient stripes) so it's unmissable.
img = QImage(800, 800, QImage.Format.Format_RGB32)
p = QPainter(img)
for i in range(0, 800, 80):
    p.fillRect(0, i, 800, 40, QColor("#f6b26b"))
    p.fillRect(0, i + 40, 800, 40, QColor("#6fa8dc"))
p.end()
bg_file = db.CHAT_BG_PATH + ".png"
img.save(bg_file)
db.set_setting("chat_bg_path", bg_file)

from utils import sync
me = sync.device_id()
db.add_message("שלום, מתי החלוקה השבוע?", author_name="מזכירה", author_device="dev-other")
db.add_message("ביום רביעי כרגיל, בשעה 18:00", author_name="מנהל", author_device=me)

from tabs.messages import MessagesTab
mt = MessagesTab(None)
mt.refresh()
shot(mt, "01_with_bg", 720, 560)

print("DONE:", OUT)
