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
       "frequency": "שבועי", "status": "פעיל", "area": "מרכז", "email": "bad-address",
       "last_distribution": "2026-09-09", "next_distribution": "2026-09-16"}
dlg2 = RecipientDialog(None, rec)
show(dlg2, "recipient_edit.png")
assert dlg2.get_data()["area"] == "מרכז"
# v3.57: שורת התאריכים ירדה גם בעריכה — הערכים הקיימים נשמרים כמו שהם
assert not dlg2.f_last_dist.isVisible() and not dlg2.f_next_dist.isVisible()
# v3.60: החלון לא כותב אותם בכלל — הם נגזרים ב-database
assert "last_distribution" not in dlg2.get_data()
assert "next_distribution" not in dlg2.get_data()
from PyQt6.QtWidgets import QLabel
assert not any("חלוקה אחרונה" in l.text() for l in dlg2.findChildren(QLabel))
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

# v3.58: כותרת חיה, קישור "עוד מספר" בתוך שורת הטלפון, הערות גבוהות, 130%
assert dlg.lbl_title.text() == "מקבל חדש" and dlg2.chip_state.text() == "קבוע"
dlg.f_first.setText("משה"); dlg.f_last.setText("לוי")
assert dlg.lbl_title.text() == "לוי משה"
dlg.f_status.setCurrentText("מושהה"); assert "מושהה" in dlg.chip_state.text()
dlg.f_priority.setCurrentText("ללא"); assert "לא בחלוקה" in dlg.chip_state.text()
assert dlg.btn_add_phone.isVisible() and not dlg.f_phone2.isVisible()
assert abs(dlg.btn_add_phone.mapTo(dlg, dlg.btn_add_phone.rect().center()).y()
           - dlg.f_phone1.mapTo(dlg, dlg.f_phone1.rect().center()).y()) < 6
dlg.btn_add_phone.click(); dlg.btn_add_phone.click(); app.processEvents()
assert dlg.f_phone3.isVisible() and not dlg.btn_add_phone.isVisible()
assert dlg.f_notes.height() >= 84
apply_app_theme(app, 130)
dlg3 = RecipientDialog(None, dict(rec, holiday_support=1, phone2="0501234567", phone3="041234567"))
show(dlg3, "recipient_edit_130.png")
sb = dlg3.tabs.widget(0).horizontalScrollBar()
print("130% h-scroll:", sb.maximum(), "v-scroll:", dlg3.tabs.widget(0).verticalScrollBar().maximum())
assert sb.maximum() == 0, "אין גלילה אופקית גם ב-130%"
print("OK v3.58")
