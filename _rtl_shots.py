"""RTL visual audit — real Hebrew via WA_DontShowOnScreen + grab()."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication, QWidget
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
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(1360, 860)
win.show()

SHOTS = os.path.join(os.path.dirname(__file__), "screenshots_test")
os.makedirs(SHOTS, exist_ok=True)
step = [0]

def go():
    i = step[0]
    if i >= win.tabs.count():
        app.quit(); return
    win.tabs.setCurrentIndex(i)
    w = win.tabs.widget(i)
    if hasattr(w, "refresh"):
        try: w.refresh()
        except Exception as e: print("refresh err", e)
    QTimer.singleShot(400, cap)

def cap():
    i = step[0]
    name = win.tabs.tabText(i).replace(" ", "_").replace("/", "-")
    win.grab().save(os.path.join(SHOTS, f"tab{i}_{name}.png"))
    print("shot", i, name)
    step[0] += 1
    QTimer.singleShot(150, go)

QTimer.singleShot(600, go)
app.exec()
print("done")
