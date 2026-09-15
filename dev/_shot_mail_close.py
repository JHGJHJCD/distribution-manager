# -*- coding: utf-8 -*-
"""צילום חלון האזהרה "שליחת מיילים פעילה" (v3.46) — הנתיב האמיתי של confirm_close.
מריצים בלי offscreen (עברית) עם WA_DontShowOnScreen. הפלט: dev/_shots/mail_close.png.
לאמת דרך gemini_task.py -f, לא לקרוא את ה-PNG לצ'אט."""
import os, sys, tempfile
os.environ["PYTHONUTF8"] = "1"
sys.path.insert(0, ".")
import database as db
db.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="shot_close_"), "data.db")
db.init_db()
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
import styles
app = QApplication([])
styles.apply_app_theme(app, 100)
import tabs.mails as mmod

out = os.path.join("dev", "_shots", "mail_close.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
res = {}

def _question(parent, title, text, buttons=None, default=None):
    box = QMessageBox(QMessageBox.Icon.Question, title, text,
                      buttons or (QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No), parent)
    box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    if default is not None:
        box.setDefaultButton(default)
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.show()
    for _ in range(5):
        app.processEvents()
    ok = box.grab().save(out)
    res["saved"] = ok
    res["default_no"] = box.defaultButton() is box.button(QMessageBox.StandardButton.No)
    res["text"] = text
    box.close()
    return QMessageBox.StandardButton.No

mmod.QMessageBox.question = staticmethod(_question)
tab = mmod.MailsTab(None)
tab.refresh()

class _FakeWorker:
    finished_rows = type("S", (), {"disconnect": lambda self, *a: None})()
    def stop(self): pass
    def wait(self, ms): return True

tab._worker = _FakeWorker()
tab._sent_n = 120
tab.prog.setRange(0, 500)
r = tab.confirm_close()
assert r is False, r
assert res.get("saved"), "grab failed"
assert res.get("default_no"), "default button must be 'No'"
assert "120 מתוך 500" in res["text"], res["text"]
assert tab._worker is not None
print("OK", out, os.path.getsize(out))
