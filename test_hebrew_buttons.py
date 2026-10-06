"""Regression test (task 3): every standard Qt dialog button / label / context-menu
entry the app can show is in Hebrew (no Yes / No / OK / Cancel left in English).

The fix is one central place: utils.ui.install_hebrew_ui(app) (a QTranslator), called
once from main._run. This test installs it exactly like the app does and inspects the
real Qt widgets.

Run:  python test_hebrew_buttons.py   (Python 3.12, PYTHONUTF8=1)
"""
import os
import re
import sys

from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QDialogButtonBox, QInputDialog, QFileDialog,
    QColorDialog, QProgressDialog, QLineEdit, QTextEdit, QPlainTextEdit, QPushButton,
    QLabel, QToolButton, QAbstractButton, QWidget,
)
from PyQt6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

_fail = 0


def check(name, cond, extra=""):
    global _fail
    print(("  OK  " if cond else "  XX  ") + name + (f"   {extra}" if (extra and not cond) else ""))
    if not cond:
        _fail += 1


_LATIN = re.compile(r"[A-Za-z]{2,}")
_ALLOWED_LATIN = {"Excel", "PDF", "RGB", "HTML", "HSV", "Qt"}


def latin_words(text: str):
    t = (text or "").split("\t")[0].replace("&", "")   # drop the "\tCtrl+Z" shortcut hint
    return [w for w in _LATIN.findall(t) if w not in _ALLOWED_LATIN]


def english_in(widget: QWidget):
    """Latin words found in the visible texts of buttons/labels of a dialog."""
    bad = []
    for cls in (QAbstractButton, QLabel):
        for w in widget.findChildren(cls):
            t = w.text() if hasattr(w, "text") else ""
            lw = latin_words(t)
            if lw:
                bad.append((type(w).__name__, t))
    return bad


from utils import ui
check("install_hebrew_ui exists", hasattr(ui, "install_hebrew_ui"))
if hasattr(ui, "install_hebrew_ui"):
    ui.install_hebrew_ui(app)

SB = QMessageBox.StandardButton

# ── QMessageBox: every standard button, one by one ──────────────────────────────
names = ("Ok Open Save Cancel Close Discard Apply Reset RestoreDefaults Help SaveAll "
         "Yes YesToAll No NoToAll Abort Retry Ignore").split()
for n in names:
    box = QMessageBox()
    box.setStandardButtons(getattr(SB, n))
    texts = [b.text() for b in box.buttons()]
    check(f"QMessageBox.{n} -> {texts}", texts and not any(latin_words(t) for t in texts), str(texts))

# the common combos the app really uses
box = QMessageBox()
box.setStandardButtons(SB.Yes | SB.No | SB.Cancel)
texts = {box.button(b).text().replace("&", "") for b in (SB.Yes, SB.No, SB.Cancel)}
check("Yes/No/Cancel are the plain words כן / לא / ביטול", texts == {"כן", "לא", "ביטול"}, str(texts))
box = QMessageBox()
box.setStandardButtons(SB.Ok)
check("OK is 'אישור'", box.button(SB.Ok).text().replace("&", "") == "אישור", box.button(SB.Ok).text())
box = QMessageBox()
box.setStandardButtons(SB.Save | SB.Discard | SB.Cancel)
t = {box.button(b).text().replace("&", "") for b in (SB.Save, SB.Discard, SB.Cancel)}
check("Save/Discard/Cancel -> שמור / ביטול + a Hebrew 'discard'", "שמור" in t and "ביטול" in t
      and not any(latin_words(x) for x in t), str(t))

# details button
box = QMessageBox()
box.setText("x")
box.setDetailedText("פרטים")
box.setStandardButtons(SB.Ok)
box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
box.show()
app.processEvents()
check("QMessageBox 'Show Details...' button is Hebrew",
      not any(latin_words(b.text()) for b in box.findChildren(QPushButton)),
      str([b.text() for b in box.findChildren(QPushButton)]))
box.close()

# ── QDialogButtonBox ──────────────────────────────────────────────────────────
for n in ("Ok", "Cancel", "Save", "Close", "Open", "Yes", "No", "Apply", "Reset", "Discard",
          "Help", "Abort", "Retry", "Ignore", "RestoreDefaults", "SaveAll", "YesToAll", "NoToAll"):
    bb = QDialogButtonBox(getattr(QDialogButtonBox.StandardButton, n))
    texts = [b.text() for b in bb.buttons()]
    check(f"QDialogButtonBox.{n} -> {texts}", texts and not any(latin_words(t) for t in texts), str(texts))

# ── QInputDialog (getText & co. build exactly this) ───────────────────────────────
dlg = QInputDialog()
dlg.setLabelText("שם:")
dlg.setInputMode(QInputDialog.InputMode.TextInput)
bad = english_in(dlg)
check("QInputDialog buttons are Hebrew", not bad, str(bad))
dlg = QInputDialog()
dlg.setInputMode(QInputDialog.InputMode.IntInput)
check("QInputDialog (int) buttons are Hebrew", not english_in(dlg), str(english_in(dlg)))

# ── QFileDialog (Qt widget version; the native Windows one follows the OS language) ──
fd = QFileDialog()
fd.setOption(QFileDialog.Option.DontUseNativeDialog, True)
fd.setFileMode(QFileDialog.FileMode.ExistingFile)
fd.setNameFilter("Excel (*.xlsx *.xls)")
bad = english_in(fd)
check("QFileDialog (open file) buttons+labels are Hebrew", not bad, str(bad))
fd2 = QFileDialog()
fd2.setOption(QFileDialog.Option.DontUseNativeDialog, True)
fd2.setFileMode(QFileDialog.FileMode.Directory)
fd2.setOption(QFileDialog.Option.ShowDirsOnly, True)
bad = english_in(fd2)
check("QFileDialog (choose folder) buttons+labels are Hebrew", not bad, str(bad))

# ── QColorDialog (mails.py uses it for text/highlight colour) ────────────────────────
cd = QColorDialog()
cd.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
bad = english_in(cd)
check("QColorDialog buttons+labels are Hebrew", not bad, str(bad))

# ── QProgressDialog ───────────────────────────────────────────────────────────────
pd = QProgressDialog("עובד...", None, 0, 10)
pd2 = QProgressDialog("עובד...", "ביטול", 0, 10)
pd3 = QProgressDialog()
check("QProgressDialog default cancel button is Hebrew", not english_in(pd3), str(english_in(pd3)))

# ── standard text-edit / line-edit context menus (right-click: Undo/Cut/Copy/...) ────────
for cls in (QLineEdit, QTextEdit, QPlainTextEdit):
    w = cls()
    m = w.createStandardContextMenu()
    texts = [a.text() for a in m.actions() if a.text()]
    bad = [t for t in texts if latin_words(t)]
    check(f"{cls.__name__} right-click menu is Hebrew", texts and not bad, str(bad))

# ── print dialogs built by the app (preview toolbar + QPrintDialog) ─────────────────────
try:
    from PyQt6.QtPrintSupport import QPrintPreviewDialog, QPrinter
    pp = QPrintPreviewDialog(QPrinter())
    bad = english_in(pp)
    texts = [a.text() for a in pp.findChildren(__import__("PyQt6.QtGui", fromlist=["QAction"]).QAction) if a.text()]
    bad += [("QAction", t) for t in texts if latin_words(t)]
    check("QPrintPreviewDialog (if used) is Hebrew", not bad, str(bad))
except Exception as e:           # no printer on the machine -> not testable here
    print("  --  QPrintPreviewDialog skipped:", type(e).__name__, e)

# ── static scan: no hard-coded English button caption anywhere in the app code ───────────
root = os.path.dirname(os.path.abspath(__file__))
pat = re.compile(r"""addButton\(\s*["'][A-Za-z][A-Za-z &]*["']"""
                 r"""|setButtonText\([^,]+,\s*["'][A-Za-z][A-Za-z &]*["']""", re.M)
hits = []
for folder in ("tabs", "utils", ""):
    d = os.path.join(root, folder) if folder else root
    for fn in os.listdir(d):
        if fn.endswith(".py") and not fn.startswith("test_"):
            src = open(os.path.join(d, fn), encoding="utf-8").read()
            for m in pat.finditer(src):
                hits.append(f"{fn}: {m.group(0)}")
check("no hard-coded English button captions in the code", not hits, str(hits))

# native Windows file dialogs show the English "All Files (*)" when no filter is given
pat2 = re.compile(r"getOpenFileName\(([^()]|\([^()]*\))*\)", re.S)
nofilter = []
for folder in ("tabs", "utils", ""):
    d = os.path.join(root, folder) if folder else root
    for fn in os.listdir(d):
        if fn.endswith(".py") and not fn.startswith("test_"):
            src = open(os.path.join(d, fn), encoding="utf-8").read()
            for m in pat2.finditer(src):
                args = m.group(0)
                if args.count(",") < 3 and "*" not in args:      # (parent, title) only
                    nofilter.append(f"{fn}: {' '.join(args.split())[:70]}")
check("every getOpenFileName passes a Hebrew filter (no English 'All Files')", not nofilter, str(nofilter))

# the app really installs it at startup
main_src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
check("main._run installs install_hebrew_ui(app)", "install_hebrew_ui(app)" in main_src)

print()
print(f"נכשלו: {_fail}" if _fail else "הכל עבר ✓")
sys.exit(1 if _fail else 0)
