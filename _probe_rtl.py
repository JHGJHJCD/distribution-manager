"""Runtime probe: why does the one-time table render names visually-left while
the dist table renders them visually-right, given identical AlignRight code?"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
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
db.init_db()

from main import MainWindow
w = MainWindow()
w.one_time_tab.refresh()
w.group_tab.refresh()

def dname(x):
    return {Qt.LayoutDirection.RightToLeft: "RTL",
            Qt.LayoutDirection.LeftToRight: "LTR"}.get(x, "Auto")

for label, t in (("group", w.group_tab.table), ("one_time", w.one_time_tab.table)):
    it = t.item(0, 1)
    print(label,
          "| tableDir:", dname(t.layoutDirection()),
          "| viewportDir:", dname(t.viewport().layoutDirection()),
          "| rows:", t.rowCount(),
          "| item:", repr(it.text()[:12]) if it else None,
          "| align:", int(it.textAlignment()) if it else None,
          "| itemDelegate:", type(t.itemDelegate()).__name__,
          "| colDelegate1:", type(t.itemDelegateForColumn(1)).__name__)
print("AlignRight =", int(Qt.AlignmentFlag.AlignRight),
      "AlignLeft =", int(Qt.AlignmentFlag.AlignLeft),
      "AlignVCenter =", int(Qt.AlignmentFlag.AlignVCenter))
