"""RTL/readability audit shots — names files by the tab's objectName so the
mapping is unambiguous, and focuses a text field to reveal cursor position."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont

import database as db
from styles import EXTRA_QSS, QT_MATERIAL_EXTRA

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
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
win.resize(1360, 860)
win.show()

OUT = os.path.join(os.path.dirname(__file__), "screenshots_test")
os.makedirs(OUT, exist_ok=True)

# index by objectName
tabs = {win.tabs.widget(i).objectName(): i for i in range(win.tabs.count())}
order = ["tab_dist", "tab_recipients", "tab_one_time", "tab_search", "tab_settings"]
seq = [k for k in order if k in tabs]
step = [0]

def go():
    if step[0] >= len(seq):
        app.quit(); return
    key = seq[step[0]]
    win.tabs.setCurrentIndex(tabs[key])
    w = win.tabs.widget(tabs[key])
    if getattr(w, "refresh", None):
        w.refresh()
    # reveal cursor: focus the first editable text field on this tab
    if key == "tab_dist":
        try:
            le = win.group_tab.search_input
            le.setFocus(); le.setText("");
        except Exception:
            pass
    QTimer.singleShot(350, cap)

def cap():
    key = seq[step[0]]
    pix = app.primaryScreen().grabWindow(win.winId())
    pix.save(os.path.join(OUT, f"rtl_{key}.png"))
    print("shot:", key)
    step[0] += 1
    QTimer.singleShot(120, go)

QTimer.singleShot(500, go)
app.exec()
