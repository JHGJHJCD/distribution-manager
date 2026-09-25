"""צילום חלון "רשימה עצמאית" עם מספר שנראה כמו ת"ז (הכרעת יהודה 25/9/2026).
Run: python dev/_shot_freelist_ids.py  → dev/_shots/freelist_ids.png"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db

db.DB_PATH = os.path.join(tempfile.mkdtemp(), "shot.db")
db.init_db()

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import styles
styles.apply_app_theme(app, 100)
from tabs.tzintukim import _FreeListDialog

dlg = _FreeListDialog()
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
dlg.text.setPlainText("034567891 משפחת כהן\n048671230 לוי\n0501234567 גרין")
dlg.show()
app.processEvents()
assert "034567891" in dlg.lbl_ids.text() and not dlg.chk_ids.isHidden()
assert "034567891" not in [p for p, _ in dlg.entries]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots", "freelist_ids.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
dlg.grab().save(out)
print("saved", out)
