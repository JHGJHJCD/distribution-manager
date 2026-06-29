"""
בדיקה ויזואלית — מפעיל את החלון הראשי, עובר על כל לשונית, מצלם וסוגר.
מריץ על DB האמיתי (קריאה בלבד — אין שמירה).
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont, QFontDatabase

import database as db
from styles import EXTRA_QSS, QT_MATERIAL_EXTRA

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

# load bundled Rubik so screenshots match the real app
_family = "Segoe UI"
_fonts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
if os.path.isdir(_fonts):
    for _fn in os.listdir(_fonts):
        if _fn.lower().endswith((".ttf", ".otf")):
            _fid = QFontDatabase.addApplicationFont(os.path.join(_fonts, _fn))
            if "Rubik" in (QFontDatabase.applicationFontFamilies(_fid) if _fid != -1 else []):
                _family = "Rubik"

try:
    from qt_material import apply_stylesheet
    apply_stylesheet(app, theme="light_blue.xml", invert_secondary=True, extra=QT_MATERIAL_EXTRA)
    app.setStyleSheet(app.styleSheet() + EXTRA_QSS)
except ImportError:
    app.setStyleSheet(EXTRA_QSS)

app.setFont(QFont("Segoe UI", 11))
db.init_db()

from main import MainWindow
win = MainWindow()
win.resize(1280, 800)
win.show()

SHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots_test")
os.makedirs(SHOTS_DIR, exist_ok=True)

TAB_NAMES = [
    "00_group_update", "01_weekly", "02_recipients", "03_one_time",
    "04_tracking", "05_search", "06_summary", "07_settings"
]

step = [0]

def next_tab():
    i = step[0]
    if i < win.tabs.count():
        win.tabs.setCurrentIndex(i)
        tab = win.tabs.widget(i)
        if hasattr(tab, "refresh"):
            tab.refresh()
        # ממתין עוד פריים אחד לרינדור
        QTimer.singleShot(300, capture)
    else:
        app.quit()

def capture():
    i = step[0]
    screen = app.primaryScreen()
    pix = screen.grabWindow(win.winId())
    path = os.path.join(SHOTS_DIR, f"tab_{TAB_NAMES[i]}.png")
    pix.save(path)
    print(f"  צולם: {path}")
    step[0] += 1
    QTimer.singleShot(100, next_tab)

QTimer.singleShot(500, next_tab)
app.exec()
print(f"\nצילומים נשמרו ב: {SHOTS_DIR}")
