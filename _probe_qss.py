"""Verify: (1) the new QSS qproperty-alignment actually right-aligns line edits
(incl. editable combos + spinboxes), (2) QTextEdit empty-cursor side in RTL,
(3) table AlignAbsolute fix works end-to-end through the real tabs."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import (QApplication, QLineEdit, QTextEdit, QComboBox,
                             QSpinBox)
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

def cursor_side(le):
    cr = le.cursorRect()
    return "RIGHT" if cr.center().x() > le.width() / 2 else "LEFT"

le = QLineEdit(); le.resize(400, 34); le.show(); app.processEvents()
print("QLineEdit empty cursor:", cursor_side(le), "| align:", int(le.alignment()))

cb = QComboBox(); cb.setEditable(True); cb.resize(400, 34); cb.show(); app.processEvents()
print("editable QComboBox cursor:", cursor_side(cb.lineEdit()))

sp = QSpinBox(); sp.resize(120, 34); sp.show(); app.processEvents()
print("QSpinBox text visible OK, alignment:", int(sp.lineEdit().alignment()))

te = QTextEdit(); te.resize(400, 80); te.show(); app.processEvents()
cr = te.cursorRect()
print("QTextEdit empty cursor:", "RIGHT" if cr.center().x() > te.width()/2 else "LEFT")

# end-to-end: real one_time table, name item visual position
from main import MainWindow
w = MainWindow()
w.one_time_tab.refresh()
t = w.one_time_tab.table
t.resize(1200, 400); t.show(); app.processEvents()
if t.rowCount():
    img = t.viewport().grab().toImage()
    rect = t.visualRect(t.model().index(0, 1))
    y = rect.center().y()
    xs = [x for x in range(max(0, rect.left()), min(img.width(), rect.right()))
          if img.pixelColor(x, y).lightness() < 120]
    if xs:
        side = "VISUAL-RIGHT" if (sum(xs)/len(xs)) > rect.center().x() else "VISUAL-LEFT"
        print(f"one_time name cell: text x {min(xs)}..{max(xs)} in {rect.left()}..{rect.right()} => {side}")
    else:
        print("one_time name cell: no pixels found (row height / scroll?)")
print("done")
