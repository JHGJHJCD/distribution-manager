"""Empirical test: where does AlignRight land visually in an RTL QTableWidget,
with and without AlignAbsolute? And where does the cursor sit in an empty
QLineEdit in an RTL app, with and without explicit alignment?"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QLineEdit
from PyQt6.QtCore import Qt
from styles import EXTRA_QSS

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
app.setStyleSheet(EXTRA_QSS)

# ── table: one wide column, three alignment variants ──
t = QTableWidget(3, 1)
t.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
t.setColumnWidth(0, 500)
t.resize(560, 220)

variants = [
    ("AlignRight",     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ("Right|Absolute", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter),
    ("AlignLeft",      Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
]
for r, (name, al) in enumerate(variants):
    it = QTableWidgetItem("WORD")
    it.setTextAlignment(al)
    t.setItem(r, 0, it)
t.show()
app.processEvents()

pix = t.viewport().grab()
img = pix.toImage()
col_w = t.columnWidth(0)
for r, (name, _) in enumerate(variants):
    rect = t.visualRect(t.model().index(r, 0))
    # scan the row band for dark pixels (text)
    y = rect.center().y()
    xs = [x for x in range(rect.left(), rect.right())
          if img.pixelColor(x, y).lightness() < 120]
    if xs:
        side = "VISUAL-LEFT" if (sum(xs)/len(xs)) < rect.center().x() else "VISUAL-RIGHT"
        print(f"{name:16s} -> text at x {min(xs)}..{max(xs)} of {rect.left()}..{rect.right()}  => {side}")
    else:
        print(f"{name:16s} -> no text pixels found")

# ── line edit: cursor position when empty ──
for label, align in (("no alignment", None),
                     ("AlignRight",   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)):
    le = QLineEdit()
    le.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    if align is not None:
        le.setAlignment(align)
    le.resize(400, 34)
    le.show()
    app.processEvents()
    cr = le.cursorRect()
    side = "LEFT" if cr.center().x() < le.width() / 2 else "RIGHT"
    print(f"empty QLineEdit ({label}): cursor x={cr.center().x()} of {le.width()} => {side}")
print("done")
