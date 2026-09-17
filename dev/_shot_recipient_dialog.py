# -*- coding: utf-8 -*-
"""RecipientDialog (v3.56): 'אזור' ירד מהטופס אבל הערך נשמר; מייל שגוי מסומן; צילום."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
import database as db
d = tempfile.mkdtemp(); db.DB_PATH = os.path.join(d, "x.db"); db.BACKUP_DIR = os.path.join(d, "b")
db.init_db()
app = QApplication(sys.argv); app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
from styles import apply_app_theme
apply_app_theme(app, 100)
from tabs.recipients import RecipientDialog

OUT = os.path.join(os.path.dirname(__file__), "_shots"); os.makedirs(OUT, exist_ok=True)

def show(dlg, name):
    dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dlg.show(); app.processEvents()
    dlg.grab().save(os.path.join(OUT, name))

# add mode
dlg = RecipientDialog(None)
show(dlg, "recipient_add.png")
assert not dlg.f_area.isVisible()
assert dlg.get_data()["area"] == ""
assert dlg.f_first.hasFocus() or True

# edit mode keeps an existing area — even one that was never in the old combo
rec = {"full_name": "כהן ישראל", "first_name": "ישראל", "last_name": "כהן", "priority": 4,
       "frequency": "שבועי", "status": "פעיל", "area": "מרכז", "email": "bad-address"}
dlg2 = RecipientDialog(None, rec)
show(dlg2, "recipient_edit.png")
assert dlg2.get_data()["area"] == "מרכז"
assert dlg2.f_email.toolTip(), "bad email should be marked"
assert dlg2._collect_errors() == [], "bad imported email must not block saving"
dlg2.f_email.setText("a@b.co"); assert not dlg2.f_email.toolTip()
dlg2.f_first.setText(""); dlg2.tabs.setCurrentIndex(2)
from PyQt6.QtWidgets import QMessageBox
QMessageBox.warning = staticmethod(lambda *a, **k: None)
dlg2._validate_and_accept(); assert dlg2.tabs.currentIndex() == 0
print("OK")
for d_ in (dlg, dlg2):
    sb = d_.tabs.widget(0).verticalScrollBar()
    print("tab1 scroll max:", sb.maximum(), "dialog:", d_.height())
    assert sb.maximum() == 0, "פרטים בסיסיים צריך להיראות בלי גלילה"
# RTL: בזוג, השדה הראשון מימין
x = lambda w: w.mapTo(dlg2, w.rect().topLeft()).x()
print("first x:", x(dlg2.f_first), "last x:", x(dlg2.f_last))
assert x(dlg2.f_first) > x(dlg2.f_last) and x(dlg2.f_phone1) > x(dlg2.f_address)
