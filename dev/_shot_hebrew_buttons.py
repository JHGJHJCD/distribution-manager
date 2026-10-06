"""Screenshot probe (task 3): standard Qt dialogs render with Hebrew buttons.

Builds, with the app's real theme + the central Hebrew translator:
  1. the "תבנית קיימת"-style Yes/No question (QMessageBox.question look)
  2. the import replace/merge question (ui.ask_choice buttons)
  3. QInputDialog (text) — OK/Cancel
  4. Qt file dialog (non-native) — to show the file-dialog labels/buttons
Saves dev/_shots/hebrew_buttons.png (one composite, 2x2).
Run:  python dev/_shot_hebrew_buttons.py   (Python 3.12, PYTHONUTF8=1, NOT offscreen)
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from PyQt6.QtWidgets import (QApplication, QMessageBox, QInputDialog, QFileDialog, QLineEdit)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QImage, QPainter

app = QApplication.instance() or QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
import styles
styles.apply_app_theme(app, 100)
app.setFont(QFont("Segoe UI", 11))

from utils import ui
ui.install_hebrew_ui(app)

shots = []


def snap(w, size=None):
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size:
        w.resize(*size)
    w.show()
    for _ in range(4):
        app.processEvents()
    img = w.grab().toImage()
    shots.append(img)
    w.close()


# 1. exactly what QMessageBox.question(..., Yes|No) builds
b = QMessageBox()
b.setIcon(QMessageBox.Icon.Question)
b.setWindowTitle("מחיקת תבנית")
b.setText("למחוק את התבנית הזו (בשני המחשבים)?")
b.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
b.setDefaultButton(QMessageBox.StandardButton.No)
snap(b)

# 2. replace / merge / cancel (named buttons)
b2 = QMessageBox()
b2.setIcon(QMessageBox.Icon.Question)
b2.setWindowTitle("אופן ייבוא")
b2.setText("להחליף את כל הנתונים הקיימים, או למזג עם הקיים?\n\n"
           "• החלף הכול — מוחק הכל ומייבא מחדש\n"
           "• מזג — מוסיף חדשים; שינויים במקבלים קיימים — רק לאחר אישור")
for cap, role in (("החלף הכול", QMessageBox.ButtonRole.AcceptRole),
                  ("מזג", QMessageBox.ButtonRole.AcceptRole),
                  ("ביטול", QMessageBox.ButtonRole.RejectRole)):
    b2.addButton(cap, role)
snap(b2)

# 3. input dialog
d = QInputDialog()
d.setWindowTitle("שמירת תבנית")
d.setLabelText("שם התבנית:")
d.setTextEchoMode(QLineEdit.EchoMode.Normal)
snap(d)

# 4. Qt file dialog (the native Windows one is already Hebrew via the OS)
f = QFileDialog()
f.setOption(QFileDialog.Option.DontUseNativeDialog, True)
f.setWindowTitle("בחר קובץ גיבוי")
f.setFileMode(QFileDialog.FileMode.ExistingFile)
f.setNameFilter("קבצי גיבוי (*.db);;הכל (*.*)")
snap(f, (760, 460))

W = max(i.width() for i in shots) + 20
H = max(i.height() for i in shots) + 20
canvas = QImage(2 * W, 2 * H, QImage.Format.Format_ARGB32)
canvas.fill(Qt.GlobalColor.lightGray)
p = QPainter(canvas)
for n, img in enumerate(shots):
    p.drawImage((n % 2) * W + 10, (n // 2) * H + 10, img)
p.end()
os.makedirs(os.path.join(REPO, "dev", "_shots"), exist_ok=True)
out = os.path.join(REPO, "dev", "_shots", "hebrew_buttons.png")
canvas.save(out)
print("saved", out, os.path.getsize(out))
